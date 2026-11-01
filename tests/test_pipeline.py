import hashlib
import json

import pytest

from brofessor import pipeline, service, worker
from brofessor.workspace import Workspace


@pytest.fixture
def workspace(tmp_path):
    workspace = Workspace(tmp_path / "workspace")
    source = tmp_path / "source.md"
    source.write_text("# Test\nA bridge carried 1200 kilograms. Flood resistance is unknown.")
    workspace.add_source(source)
    return workspace


def test_pipeline_references_original_and_reuses_checkpoint(workspace, monkeypatch):
    calls = []
    citation = workspace.units()[0]["id"]

    def generate(prompt, *args, **kwargs):
        calls.append(prompt)
        return {
            "answer": "1200 kg; flooding is unknown",
            "citations": [citation],
            "quotes": [{"citation": citation, "text": "1200 kilograms"}],
        }

    monkeypatch.setattr("brofessor.executors.generate", generate)
    job = service.submit(workspace, "ask", focus="How much load?", start_worker=False)
    pipeline.execute(workspace, job)
    draft = workspace.draft(job["id"])
    service.edit_draft(workspace, job["id"], {**draft["data"], "answer": "My correction"}, 1)
    pipeline.execute(workspace, job)
    assert len(calls) == 1
    assert "1200 kilograms" in calls[0]
    assert workspace.draft(job["id"])["data"]["answer"] == "My correction"
    edited = next(a for a in workspace.artifacts(job["id"]) if a["metadata"]["revision"] == 2)
    assert json.loads((workspace.path / edited["path"]).read_text())["answer"] == "My correction"
    coverage = json.loads((workspace.path / "jobs" / job["id"] / "coverage.json").read_text())
    assert coverage["read"] == [citation]


def test_fabricated_citation_is_not_saved(workspace, monkeypatch):
    monkeypatch.setattr(
        "brofessor.executors.generate",
        lambda *a, **k: {"answer": "Wrong", "citations": ["made-up"]},
    )
    job = service.submit(workspace, "ask", focus="Question?", start_worker=False)
    with pytest.raises(ValueError, match="Unknown source"):
        pipeline.execute(workspace, job)
    assert workspace.draft(job["id"]) is None


def test_render_is_pinned_to_draft_revision(workspace):
    citation = workspace.units()[0]["id"]
    job = service.submit(workspace, "slides", start_worker=False)
    value = {
        "title": "Bridge",
        "language": "en",
        "slides": [
            {
                "title": "Load",
                "bullets": ["1200 kg"],
                "notes": "Not tested in floods",
                "citations": [citation],
            }
        ],
    }
    workspace.save_draft(job["id"], value)
    render = service.render(workspace, job["id"], start_worker=False)
    value["title"] = "Edited later"
    service.edit_draft(workspace, job["id"], value, 1)
    assert render["params"]["revision"] == 1
    assert workspace.draft(job["id"], 1)["data"]["title"] == "Bridge"


def test_cancel_before_generation(workspace, monkeypatch):
    calls = []
    monkeypatch.setattr("brofessor.executors.generate", lambda *a, **k: calls.append(1))
    job = service.submit(workspace, "slides", start_worker=False)
    with pytest.raises(RuntimeError, match="Cancelled"):
        pipeline.execute(workspace, job, lambda: True)
    assert not calls


def test_supported_answer_needs_citations():
    from brofessor.models import Answer

    with pytest.raises(ValueError, match="requires source citations"):
        Answer(answer="1200 kg", citations=[])
    assert (
        Answer(
            answer="Not in the source", citations=[], evidence_status="insufficient_evidence"
        ).citations
        == []
    )


@pytest.mark.parametrize("language,count,message", [("ru", 1, "language"), ("en", 1, "count")])
def test_generated_slides_must_match_request(workspace, monkeypatch, language, count, message):
    citation = workspace.units()[0]["id"]
    value = {
        "title": "Bridge",
        "language": language,
        "slides": [
            {
                "title": "Load",
                "bullets": ["1200 kg"],
                "notes": "Not tested in floods",
                "citations": [citation],
            }
        ]
        * count,
    }
    monkeypatch.setattr("brofessor.executors.generate", lambda *a, **k: value)
    job = service.submit(workspace, "slides", language="en", slide_count=4, start_worker=False)
    with pytest.raises(ValueError, match=message):
        pipeline.execute(workspace, job)
    assert workspace.draft(job["id"]) is None


def test_chapter_summary_cannot_cite_unseen_chapter(workspace, tmp_path, monkeypatch):
    source = tmp_path / "long.md"
    source.write_text("A measured fact. " * 1800)
    added = workspace.add_source(source)
    units = workspace.units([added["id"]])
    monkeypatch.setattr(
        "brofessor.executors.generate",
        lambda *a, **k: {"notes": [{"summary": "A fact", "citations": [units[-1]["id"]]}]},
    )
    job = service.submit(workspace, "slides", source_ids=[added["id"]], start_worker=False)
    with pytest.raises(ValueError, match="Unknown source"):
        pipeline.execute(workspace, job)


@pytest.mark.parametrize("port", [0, -1, 65536, True, 11435.0, "11435", None])
def test_invalid_ollama_port_is_rejected_before_queueing(workspace, monkeypatch, port):
    started = []
    monkeypatch.setattr(worker, "ensure_worker", lambda *_: started.append(True))
    with pytest.raises(ValueError, match="Ollama port"):
        service.submit(workspace, "ask", focus="Load?", provider="ollama", ollama_port=port)
    assert workspace.jobs() == []
    assert started == []


def test_ollama_port_is_persisted_and_part_of_request_identity(workspace):
    options = dict(focus="Load?", provider="ollama", model="tiny", start_worker=False)
    job = service.submit(workspace, "ask", ollama_port=11435, request_key="same", **options)
    reopened = Workspace(workspace.path)
    assert reopened.job(job["id"])["params"]["ollama_port"] == 11435
    repeated = service.submit(reopened, "ask", ollama_port=11435, request_key="same", **options)
    assert repeated["id"] == job["id"]
    with pytest.raises(ValueError, match="different operation"):
        service.submit(reopened, "ask", ollama_port=11436, request_key="same", **options)


@pytest.mark.parametrize("provider", ["codex", "ollama"])
def test_default_ollama_port_preserves_legacy_request_identity(workspace, provider):
    params = {
        "source_ids": [source["id"] for source in workspace.sources()],
        "focus": "Load?",
        "language": "ru",
        "provider": provider,
        "model": None,
        "minutes": 20,
        "slide_count": 8,
    }
    legacy = workspace.submit("ask", params, "legacy")
    repeated = service.submit(
        workspace,
        "ask",
        focus="Load?",
        provider=provider,
        ollama_port=11434,
        request_key="legacy",
        start_worker=False,
    )
    assert repeated["id"] == legacy["id"]
    assert "ollama_port" not in repeated["params"]


def test_custom_ollama_port_survives_worker_restart_and_resume(workspace, monkeypatch):
    citation = workspace.units()[0]["id"]
    calls = []

    def generate(prompt, schema, provider, model, **kwargs):
        calls.append((prompt, provider, model, kwargs["ollama_port"]))
        if len(calls) == 2:
            raise RuntimeError("Synthetic interruption after the first checkpoint")
        return {
            "title": "Bridge",
            "language": "ru",
            "turns": [
                {"speaker": "host", "text": "What load?", "citations": [citation]},
                {"speaker": "guest", "text": "1200 kilograms", "citations": [citation]},
            ],
        }

    monkeypatch.setattr("brofessor.executors.generate", generate)
    job = service.submit(
        workspace,
        "podcast",
        provider="ollama",
        model="tiny",
        ollama_port=11435,
        minutes=10,
        start_worker=False,
    )
    assert worker.run(Workspace(workspace.path), once=True)
    assert workspace.job(job["id"])["status"] == "failed"
    reopened = Workspace(workspace.path)
    reopened.resume(job["id"])
    assert worker.run(reopened, once=True)
    assert reopened.job(job["id"])["status"] == "succeeded"
    assert len(calls) == 3
    assert calls[1] == calls[2]
    assert all(call[1:] == ("ollama", "tiny", 11435) for call in calls)
    assert len(reopened.draft(job["id"])["data"]["turns"]) == 4


@pytest.mark.parametrize("provider", ["codex", "ollama"])
def test_legacy_job_reuses_original_checkpoint_identity(workspace, monkeypatch, provider):
    citation = workspace.units()[0]["id"]
    calls = []

    def generate(prompt, schema, provider, model, **kwargs):
        calls.append((prompt, schema, kwargs["ollama_port"]))
        return {
            "answer": "1200 kg",
            "citations": [citation],
            "quotes": [{"citation": citation, "text": "1200 kilograms"}],
        }

    monkeypatch.setattr("brofessor.executors.generate", generate)
    job = service.submit(workspace, "ask", focus="Load?", provider=provider, start_worker=False)
    assert "ollama_port" not in job["params"]
    pipeline.execute(workspace, job)
    assert calls[0][2] == 11434
    legacy_fingerprint = hashlib.sha256(
        json.dumps(
            {"prompt": calls[0][0], "schema": calls[0][1], "provider": provider, "model": None},
            sort_keys=True,
        ).encode()
    ).hexdigest()
    assert (
        workspace.path / "jobs" / job["id"] / "checkpoints" / f"{legacy_fingerprint}.json"
    ).exists()
    job["params"]["ollama_port"] = 11434
    pipeline.execute(workspace, job)
    assert len(calls) == 1


@pytest.mark.parametrize("provider,expected_calls", [("ollama", 2), ("codex", 1)])
def test_checkpoint_identity_changes_with_ollama_port_only(
    workspace, monkeypatch, provider, expected_calls
):
    citation = workspace.units()[0]["id"]
    calls = []

    def generate(*args, **kwargs):
        calls.append(kwargs["ollama_port"])
        return {
            "answer": "1200 kg",
            "citations": [citation],
            "quotes": [{"citation": citation, "text": "1200 kilograms"}],
        }

    monkeypatch.setattr("brofessor.executors.generate", generate)
    job = service.submit(
        workspace, "ask", focus="Load?", provider=provider, ollama_port=11435, start_worker=False
    )
    assert ("ollama_port" in job["params"]) is (provider == "ollama")
    pipeline.execute(workspace, job)
    job["params"]["ollama_port"] = 11436
    pipeline.execute(workspace, job)
    job["params"]["ollama_port"] = 11435
    pipeline.execute(workspace, job)
    assert len(calls) == expected_calls
    if provider == "ollama":
        assert calls == [11435, 11436]


@pytest.mark.parametrize("kind", ["flashcards", "render_flashcards"])
def test_unknown_job_kind_fails_before_generation(workspace, monkeypatch, kind):
    from brofessor import executors, worker

    monkeypatch.setattr(executors, "generate", lambda *a, **kw: pytest.fail("Unexpected inference"))
    job = workspace.submit(kind, {})
    worker.run(workspace, once=True)
    result = workspace.job(job["id"])
    assert result["status"] == "failed"
    assert "Unsupported job kind" in result["error"]
    assert workspace.draft(job["id"]) is None
    assert not workspace.artifacts(job["id"])
