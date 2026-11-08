import json
import shutil
from concurrent.futures import ThreadPoolExecutor

import pytest

from brofessor.application import service, worker
from brofessor.contracts.content import ContentLanguage
from brofessor.contracts.jobs import JobKind, JobStatus
from brofessor.contracts.text import TextProvider
from brofessor.features import questions
from brofessor.infrastructure.storage.workspace import Workspace


@pytest.fixture
def study(tmp_path):
    w = Workspace(tmp_path / "workspace")
    source = tmp_path / "report.md"
    source.write_text(
        "Alder bridge carried 1200 kilograms. Wind speed was 18 metres per second. The maximum safe load is unknown."
    )
    source_id = w.add_source(source)["id"]
    citation = w.units()[0]["id"]
    parent = service.submit(
        w,
        JobKind.ASK,
        focus="What load did Alder bridge carry?",
        source_ids=[source_id],
        language=ContentLanguage.EN,
        provider=TextProvider.OLLAMA,
        model="local-test",
        ollama_address="192.168.50.10:11435",
        start_worker=False,
    )
    w.save_draft(
        parent["id"],
        {
            "answer": "It carried 1200 kilograms.",
            "citations": [citation],
            "evidence_status": "supported",
            "quotes": [{"citation": citation, "text": "Alder bridge carried 1200 kilograms."}],
        },
    )
    w.update_job(parent["id"], status=JobStatus.SUCCEEDED)
    return w, parent, citation


def test_note_revisions_conflicts_and_closed_workspace_move(study, tmp_path):
    w, parent, citation = study
    note = service.save_note(
        w,
        {
            "title": "My observation",
            "text": "I want to check the wind measurement.",
            "citations": [citation],
        },
    )
    edited = service.save_note(
        w,
        {**note["data"], "text": "My edited observation."},
        note_id=note["id"],
        expected_revision=1,
    )
    with pytest.raises(ValueError, match="Note changed"):
        service.save_note(w, note["data"], note_id=note["id"], expected_revision=1)
    assert w.note(note["id"], 1)["data"] == note["data"]
    assert edited["revision"] == 2 and len(w.notes()) == 1
    shutil.copytree(w.path, tmp_path / "moved")
    moved = Workspace(tmp_path / "moved")
    assert moved.note(note["id"])["data"] == edited["data"]
    assert service.note_evidence(moved, note["id"])[0]["source"] == "report.md"
    assert Workspace(tmp_path / "other").notes() == []


def test_answer_to_note_pins_revision_and_repeated_concurrent_save_preserves_edits(study):
    w, parent, citation = study
    with ThreadPoolExecutor(max_workers=4) as pool:
        notes = list(
            pool.map(lambda _: service.note_from_answer(w, parent["id"], revision=1), range(4))
        )
    assert len({note["id"] for note in notes}) == len(w.notes()) == 1
    note = notes[0]
    assert note["origin"] == {"job_id": parent["id"], "revision": 1}
    assert note["data"]["text"] == w.draft(parent["id"], 1)["data"]["answer"]
    service.save_note(
        w,
        {**note["data"], "text": "My commentary, not a primary source."},
        note_id=note["id"],
        expected_revision=1,
    )
    assert service.note_from_answer(w, parent["id"], revision=1)["revision"] == 2
    assert w.note(note["id"])["data"]["text"].startswith("My commentary")
    updated = {**w.draft(parent["id"])["data"], "answer": "A new interpretation."}
    service.edit_draft(w, parent["id"], updated, 1)
    assert w.note(note["id"])["origin"]["revision"] == 1
    assert service.note_from_answer(w, parent["id"])["id"] != note["id"]


@pytest.mark.parametrize(
    "change",
    [
        {"title": " "},
        {"text": "\n"},
        {"citations": ["other-project:1"]},
        {"origin": {"job_id": "other", "revision": 1}},
    ],
)
def test_invalid_notes_do_not_create_a_record(study, change):
    w, _, _ = study
    with pytest.raises(ValueError):
        service.save_note(w, {"title": "Note", "text": "My text", "citations": [], **change})
    assert w.notes() == []


def test_two_note_editors_have_one_winner_and_keep_the_initial_revision(study):
    from threading import Barrier

    w, _, _ = study
    note = service.save_note(
        w, {"title": "Shared note", "text": "Initial wording", "citations": []}
    )
    barrier = Barrier(2)

    def edit(text):
        barrier.wait()
        try:
            return service.save_note(
                w, {**note["data"], "text": text}, note_id=note["id"], expected_revision=1
            )
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        values = list(pool.map(edit, ["First writer", "Second writer"]))
    winners = [v for v in values if v is not None]
    assert len(winners) == 1 and w.note(note["id"])["data"] == winners[0]["data"]
    assert w.note(note["id"], 1)["data"]["text"] == "Initial wording"


@pytest.mark.parametrize("revision", [None, 0, True])
def test_history_never_resolves_an_unpinned_or_invalid_revision(study, revision):
    w, parent, _ = study
    with pytest.raises(ValueError, match="pinned"):
        questions.history(
            w, [{"job_id": parent["id"], "revision": revision}], parent["params"]["source_ids"]
        )


def test_follow_up_inherits_scope_and_provider_and_pins_context_before_edit(
    study, tmp_path, monkeypatch
):
    w, parent, citation = study
    child = service.follow_up(
        w, parent["id"], "And what was the wind speed?", request_key="wind", start_worker=False
    )
    assert child["params"]["provider"] == "ollama"
    assert child["params"]["model"] == "local-test"
    assert child["params"]["ollama_address"] == "192.168.50.10:11435"
    assert child["params"]["conversation"] == [{"job_id": parent["id"], "revision": 1}]
    more = tmp_path / "other.md"
    more.write_text("A completely unrelated source.")
    w.add_source(more)
    assert child["params"]["source_ids"] == parent["params"]["source_ids"]
    changed = {**w.draft(parent["id"])["data"], "answer": "EDITED AFTER FOLLOW-UP SUBMISSION"}
    service.edit_draft(w, parent["id"], changed, 1)
    calls = []

    def generate(prompt, schema, provider, model, **kw):
        calls.append(prompt)
        assert (
            provider == "ollama"
            and model == "local-test"
            and kw["ollama_address"] == "192.168.50.10:11435"
        )
        assert "It carried 1200 kilograms." in prompt and "EDITED AFTER" not in prompt
        assert "not factual evidence" in prompt
        return {
            "answer": "18 metres per second.",
            "citations": [citation],
            "quotes": [{"citation": citation, "text": "Wind speed was 18 metres per second."}],
        }

    monkeypatch.setattr("brofessor.infrastructure.text.runners.generate", generate)
    worker.run(w, once=True)
    assert w.job(child["id"])["status"] == "succeeded"
    assert w.draft(child["id"])["data"]["quotes"][0]["text"] in next(
        u["text"] for u in w.units() if u["id"] == citation
    )
    assert (
        service.follow_up(
            w,
            parent["id"],
            "And what was the wind speed?",
            revision=1,
            request_key="wind",
            start_worker=False,
        )["id"]
        == child["id"]
    )
    assert len(calls) == 1


def test_follow_up_search_expansion_receives_conversation_but_notes_are_not_evidence(
    study, tmp_path, monkeypatch
):
    w, parent, citation = study
    service.save_note(
        w,
        {
            "title": "Private thought",
            "text": "PRIVATE NOTE IS NOT SOURCE EVIDENCE",
            "citations": [],
        },
    )
    monkeypatch.setattr(questions, "DIRECT_BUDGET", 1)
    job = service.follow_up(w, parent["id"], "And its maximum?", start_worker=False)
    seen = []

    def generate(prompt, schema, *a, **kw):
        assert "PRIVATE NOTE" not in prompt
        seen.append(schema["title"])
        if schema["title"] == "SearchQueries":
            assert "Alder bridge" in prompt and "1200" in prompt
            return {"queries": ["Alder bridge maximum safe load"]}
        evidence, _ = json.JSONDecoder().raw_decode(prompt.split("EVIDENCE:\n")[1])
        assert all("It carried 1200 kilograms." not in item["text"] for item in evidence)
        return {
            "answer": "The maximum is unknown.",
            "citations": [citation],
            "quotes": [{"citation": citation, "text": "The maximum safe load is unknown."}],
        }

    monkeypatch.setattr("brofessor.infrastructure.text.runners.generate", generate)
    worker.run(w, once=True)
    assert w.job(job["id"])["status"] == "succeeded"
    assert seen == ["SearchQueries", "Answer"]


def test_follow_up_chain_keeps_recent_pinned_turns_with_visible_omission(study):
    w, parent, _ = study
    last = parent
    for i in range(8):
        last = service.follow_up(w, last["id"], f"Follow-up {i}?", start_worker=False)
        w.save_draft(last["id"], w.draft(parent["id"], 1)["data"])
        w.update_job(last["id"], status=JobStatus.SUCCEEDED)
    assert len(last["params"]["conversation"]) == questions.HISTORY_TURNS
    assert last["params"]["conversation_omitted"] == 2
    assert (
        len(questions.history(w, last["params"]["conversation"], last["params"]["source_ids"])) == 6
    )


def test_long_parent_answer_requires_explicit_shortening_instead_of_truncation(study):
    w, parent, _ = study
    data = {**w.draft(parent["id"])["data"], "answer": "Long previous answer. " * 1000}
    service.edit_draft(w, parent["id"], data, 1)
    with pytest.raises(ValueError, match="too long"):
        service.follow_up(w, parent["id"], "Why?", start_worker=False)
    assert len(w.jobs()) == 1


@pytest.mark.parametrize("status", ["running", "failed", "cancelled"])
def test_follow_up_rejects_incomplete_parent_without_queueing(study, status):
    w, parent, _ = study
    w.update_job(parent["id"], status=status)
    with pytest.raises(ValueError, match="completed"):
        service.follow_up(w, parent["id"], "Why?", start_worker=False)
    assert len(w.jobs()) == 1
