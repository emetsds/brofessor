import json

import pytest

from brofessor import pipeline, reading, service
from brofessor.executors import CancelledError
from brofessor.workspace import Workspace


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

    monkeypatch.setattr("brofessor.executors.generate", generate)
    job = service.submit(
        workspace, "slides", slide_count=1, focus="Facts throughout the book?", start_worker=False
    )
    pipeline.execute(workspace, job)
    assert len(batches) > 1
    assert [citation for batch in batches for citation in batch] == [u["id"] for u in units]
    report = service.coverage(workspace, job["id"])
    assert report["count"] == len(units)
    assert report["cited_count"] == 3
    assert all(unit["status"] == "read" for unit in report["units"])
    monkeypatch.setattr("brofessor.executors.generate", lambda *a, **k: pytest.fail("Checkpoint"))
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

    monkeypatch.setattr("brofessor.executors.generate", generate)
    job = service.submit(workspace, "slides", slide_count=1, focus="Facts?", start_worker=False)
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

    monkeypatch.setattr("brofessor.executors.generate", generate)
    job = service.submit(workspace, "slides", slide_count=1, focus="Facts?", start_worker=False)
    with pytest.raises(CancelledError):
        pipeline.execute(workspace, job)
    report = service.coverage(workspace, job["id"])
    assert 0 < report["count"] < len(units)
    assert any(unit["status"] == "pending" for unit in report["units"])
    assert workspace.draft(job["id"]) is None


def test_large_note_sets_are_consolidated_without_new_citation_ids(book, monkeypatch):
    workspace, source, units = book
    monkeypatch.setattr(reading, "SYNTHESIS_BUDGET", 3000)
    consolidated = []

    def generate(prompt, schema, *args, **kwargs):
        if schema["title"] == "ReadingBatch":
            return notes_for(prompt)
        if schema["title"] == "SectionNote":
            notes = json.loads(prompt.split("\n", 1)[1])["notes"]
            assert len(reading.encoded(notes)) <= reading.READING_BUDGET
            citations = [item["citations"][0] for item in notes]
            consolidated.append(citations)
            return {"summary": "Retained facts", "citations": citations}
        evidence, _ = json.JSONDecoder().raw_decode(prompt.split("EVIDENCE:\n")[1])
        assert len(reading.encoded(evidence)) <= reading.SYNTHESIS_BUDGET
        assert {c for item in evidence for c in item["citations"]} == {u["id"] for u in units}
        return slide_plan([units[-1]["id"]])

    monkeypatch.setattr("brofessor.executors.generate", generate)
    job = service.submit(workspace, "slides", slide_count=1, focus="Facts?", start_worker=False)
    pipeline.execute(workspace, job)
    assert consolidated
    assert service.coverage(workspace, job["id"])["count"] == len(units)


def test_failed_direct_answer_does_not_claim_sources_were_read(tmp_path, monkeypatch):
    workspace = Workspace(tmp_path / "workspace")
    source = tmp_path / "short.md"
    source.write_text("One fact")
    workspace.add_source(source)
    monkeypatch.setattr(
        "brofessor.executors.generate", lambda *a, **k: {"answer": "x", "citations": ["fake"]}
    )
    job = service.submit(workspace, "ask", focus="Facts?", start_worker=False)
    with pytest.raises(ValueError):
        pipeline.execute(workspace, job)
    assert service.coverage(workspace, job["id"])["count"] == 0


def test_legacy_coverage_and_render_citations_follow_the_pinned_revision(book):
    from brofessor.workspace import atomic_json

    workspace, source, units = book
    job = service.submit(workspace, "podcast", start_worker=False)
    data = {
        "title": "Facts",
        "language": "ru",
        "turns": [
            {"speaker": "host", "text": "Вопрос", "citations": [units[0]["id"]]},
            {"speaker": "guest", "text": "Ответ", "citations": [units[0]["id"]]},
        ],
    }
    workspace.save_draft(job["id"], data)
    atomic_json(
        workspace.path / "jobs" / job["id"] / "coverage.json",
        {"read": [unit["id"] for unit in units], "count": len(units), "excluded": []},
    )
    render = service.render(workspace, job["id"], model="qwen3-0.6b", start_worker=False)
    for turn in data["turns"]:
        turn["citations"] = [units[-1]["id"]]
    service.edit_draft(workspace, job["id"], data, 1)
    latest = service.coverage(workspace, job["id"])
    rendered = service.coverage(workspace, render["id"])
    assert latest["draft_revision"] == 2
    assert rendered["draft_revision"] == 1
    assert [unit["id"] for unit in latest["units"] if unit["cited"]] == [units[-1]["id"]]
    assert [unit["id"] for unit in rendered["units"] if unit["cited"]] == [units[0]["id"]]
