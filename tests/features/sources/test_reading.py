import json

import pytest

from brofessor.application import pipeline, service
from brofessor.contracts.jobs import JobKind
from brofessor.features.sources import reading
from brofessor.infrastructure.storage.workspace import Workspace
from brofessor.infrastructure.text.runners import CancelledError


@pytest.fixture
def book(tmp_path):
    workspace = Workspace(tmp_path / "workspace")
    source = tmp_path / "book.txt"
    source.write_text("\n".join(f"SECTION {i}: " + "A measured fact. " * 70 for i in range(180)))
    added = workspace.add_source(source)
    return workspace, added, workspace.units([added["id"]])


def notes_for(prompt):
    data = json.loads(prompt.split("\n", 1)[1])
    assert len(reading.encoded(data["fragments"])) <= reading.READING_BUDGET
    return {
        "notes": [
            {"summary": unit["text"][:1100], "citations": [unit["id"]]}
            for unit in data["fragments"]
        ]
    }


def slide_plan(citations):
    return {
        "title": "Evidence",
        "language": "ru",
        "slides": [
            {
                "title": "Retained facts",
                "bullets": ["Beginning, middle and end"],
                "notes": "Original evidence.",
                "citations": citations,
            }
        ],
    }


def test_whole_book_is_read_in_order_and_resumes_without_model_calls(book, monkeypatch):
    workspace, source, units = book
    batches = []
    final_citations = [units[index]["id"] for index in (0, len(units) // 2, -1)]

    def generate(prompt, schema, *args, **kwargs):
        if schema["title"] == "ReadingBatch":
            result = notes_for(prompt)
            batches.append([note["citations"][0] for note in result["notes"]])
            return result
        evidence, _ = json.JSONDecoder().raw_decode(prompt.split("EVIDENCE:\n")[1])
        assert len(reading.encoded(evidence)) <= reading.SYNTHESIS_BUDGET
        assert {item["citations"][0] for item in evidence} == {u["id"] for u in units}
        return slide_plan(final_citations)

    monkeypatch.setattr("brofessor.infrastructure.text.runners.generate", generate)
    job = service.submit(
        workspace,
        JobKind.SLIDES,
        slide_count=1,
        focus="Facts throughout the book?",
        start_worker=False,
    )
    pipeline.execute(workspace, job)
    assert len(batches) > 1
    assert [citation for batch in batches for citation in batch] == [u["id"] for u in units]
    report = service.coverage(workspace, job["id"])
    assert report["count"] == len(units)
    assert report["cited_count"] == 3
    assert all(unit["status"] == "read" for unit in report["units"])
    monkeypatch.setattr(
        "brofessor.infrastructure.text.runners.generate", lambda *a, **k: pytest.fail("Checkpoint")
    )
    pipeline.execute(workspace, job)
    service.edit_draft(workspace, job["id"], slide_plan([units[0]["id"]]), 1)
    assert service.coverage(workspace, job["id"])["cited_count"] == 1
    assert service.coverage(workspace, job["id"])["draft_revision"] == 2


@pytest.mark.parametrize("problem", ["missing", "duplicate", "oversized"])
def test_invalid_reading_batch_is_not_checkpointed(book, monkeypatch, problem):
    workspace, source, units = book

    def generate(prompt, *args, **kwargs):
        result = notes_for(prompt)
        if problem == "missing":
            result["notes"].pop()
        elif problem == "duplicate":
            result["notes"][-1] = result["notes"][0]
        else:
            result["notes"][0]["summary"] = "x" * 1201
        return result

    monkeypatch.setattr("brofessor.infrastructure.text.runners.generate", generate)
    job = service.submit(
        workspace, JobKind.SLIDES, slide_count=1, focus="Facts?", start_worker=False
    )
    with pytest.raises(ValueError):
        pipeline.execute(workspace, job)
    assert not list((workspace.path / "jobs" / job["id"]).glob("checkpoints/*.json"))
    assert service.coverage(workspace, job["id"])["count"] == 0


def test_cancelled_book_keeps_accepted_reading_progress(book, monkeypatch):
    workspace, source, units = book
    calls = 0

    def generate(prompt, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise CancelledError("Cancelled")
        return notes_for(prompt)

    monkeypatch.setattr("brofessor.infrastructure.text.runners.generate", generate)
    job = service.submit(
        workspace, JobKind.SLIDES, slide_count=1, focus="Facts?", start_worker=False
    )
    with pytest.raises(CancelledError):
        pipeline.execute(workspace, job)
    report = service.coverage(workspace, job["id"])
    assert 0 < report["count"] < len(units)
    assert any(unit["status"] == "pending" for unit in report["units"])
    assert workspace.draft(job["id"]) is None


def test_reduction_keeps_each_fact_attached_to_one_source_and_resumes(book, monkeypatch):
    workspace, source, units = book
    monkeypatch.setattr(reading, "SYNTHESIS_BUDGET", 3000)
    reading_calls = []
    ambiguous = True

    def generate(prompt, schema, *args, **kwargs):
        if schema["title"] == "ReadingBatch":
            reading_calls.append(prompt)
            return notes_for(prompt)
        if schema["title"] == "SectionNotes":
            notes = json.loads(prompt.split("\n", 1)[1])["notes"]
            if ambiguous:
                return {
                    "notes": [
                        {
                            "summary": "Two unrelated facts",
                            "citations": [notes[0]["citations"][0], notes[-1]["citations"][0]],
                        }
                    ]
                }
            return {
                "notes": [
                    {
                        "summary": "Retained fact from " + note["citations"][0],
                        "citations": note["citations"],
                    }
                    for note in (notes[0], notes[-1])
                ]
            }
        evidence, _ = json.JSONDecoder().raw_decode(prompt.split("EVIDENCE:\n")[1])
        assert len(reading.encoded(evidence)) <= reading.SYNTHESIS_BUDGET
        for note in evidence:
            assert len(note["citations"]) == 1
            assert note["text"] == "Retained fact from " + note["citations"][0]
        return slide_plan(evidence[-1]["citations"])

    monkeypatch.setattr("brofessor.infrastructure.text.runners.generate", generate)
    job = service.submit(
        workspace, JobKind.SLIDES, slide_count=1, focus="Facts?", start_worker=False
    )
    with pytest.raises(ValueError, match="citations"):
        pipeline.execute(workspace, job)
    accepted = len(reading_calls)
    assert service.coverage(workspace, job["id"])["count"] == len(units)
    assert workspace.draft(job["id"]) is None
    ambiguous = False
    pipeline.execute(workspace, job)
    assert len(reading_calls) == accepted
    monkeypatch.setattr(
        "brofessor.infrastructure.text.runners.generate", lambda *a, **k: pytest.fail("Checkpoint")
    )
    pipeline.execute(workspace, job)


def test_failed_direct_answer_does_not_claim_sources_were_read(tmp_path, monkeypatch):
    workspace = Workspace(tmp_path / "workspace")
    source = tmp_path / "short.md"
    source.write_text("One fact")
    workspace.add_source(source)
    monkeypatch.setattr(
        "brofessor.infrastructure.text.runners.generate",
        lambda *a, **k: {"answer": "x", "citations": ["fake"]},
    )
    job = service.submit(workspace, JobKind.ASK, focus="Facts?", start_worker=False)
    with pytest.raises(ValueError):
        pipeline.execute(workspace, job)
    assert service.coverage(workspace, job["id"])["count"] == 0


def test_coverage_and_render_citations_follow_the_pinned_revision(preset_voices, book):
    from brofessor.infrastructure.storage.workspace import atomic_json

    workspace, source, units = book
    job = service.submit(workspace, JobKind.PODCAST, start_worker=False)
    data = {
        "title": "Facts",
        "language": "ru",
        "turns": [
            {"speaker": "host", "text": "Вопрос", "citations": [units[0]["id"]]},
            {"speaker": "guest", "text": "Ответ", "citations": [units[1]["id"]]},
        ],
    }
    workspace.save_draft(job["id"], data)
    atomic_json(
        workspace.path / "jobs" / job["id"] / "coverage.json",
        {
            "read": [unit["id"] for unit in units],
            "count": len(units),
            "excluded": [],
            "units": [
                {
                    "id": u["id"],
                    "source_id": u["source_id"],
                    "locator": u["locator"],
                    "status": "read",
                    "reason": "",
                }
                for u in units
            ],
        },
    )
    render = service.render(workspace, job["id"], model="qwen3-base", start_worker=False)
    probe = service.render(workspace, job["id"], model="qwen3-base", turn=2, start_worker=False)
    for turn in data["turns"]:
        turn["citations"] = [units[-1]["id"]]
    service.edit_draft(workspace, job["id"], data, 1)
    latest = service.coverage(workspace, job["id"])
    rendered = service.coverage(workspace, render["id"])
    assert latest["draft_revision"] == 2
    assert rendered["draft_revision"] == 1
    assert [unit["id"] for unit in latest["units"] if unit["cited"]] == [units[-1]["id"]]
    assert [unit["id"] for unit in rendered["units"] if unit["cited"]] == [
        units[0]["id"],
        units[1]["id"],
    ]
    preview = service.coverage(workspace, probe["id"])
    assert [unit["id"] for unit in preview["units"] if unit["cited"]] == [units[1]["id"]]
