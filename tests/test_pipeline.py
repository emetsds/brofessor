import json

import pytest

from brofessor import pipeline, service
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
        return {"answer": "1200 kg; flooding was not tested", "citations": [citation]}

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
        lambda *a, **k: {"summary": "A fact", "citations": [units[-1]["id"]]},
    )
    job = service.submit(workspace, "slides", source_ids=[added["id"]], start_worker=False)
    with pytest.raises(ValueError, match="Unknown source"):
        pipeline.execute(workspace, job)
