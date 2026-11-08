import copy
from zipfile import ZipFile

import pytest

from brofessor.application import pipeline, service, tasks
from brofessor.contracts.jobs import JobKind
from brofessor.contracts.text import TextProvider
from brofessor.features.books import terminology
from brofessor.features.books import translation as book_translation
from tests.helpers.books import FakeBookModel, payloads, text_edits, workspace_with_book


def submit(workspace, source, **kwargs):
    return service.submit(
        workspace,
        JobKind.TRANSLATE_EPUB,
        source_ids=[source["id"]],
        provider=TextProvider.CODEX,
        model="frozen-text-model",
        start_worker=False,
        **kwargs,
    )


def run(workspace, job):
    pipeline.execute(workspace, job)
    return workspace.draft(job["id"])


def test_automatic_meanings_are_grounded_and_user_choice_takes_precedence(tmp_path, monkeypatch):
    workspace, source = workspace_with_book(tmp_path)
    model = FakeBookModel()
    monkeypatch.setattr("brofessor.infrastructure.text.runners.generate", model)
    seed = [{"term": "log", "sense": "database journal", "translation": "реестр"}]
    job = submit(workspace, source, glossary=seed, request_key="book")
    seed[0]["translation"] = "changed after submission"
    saved = run(workspace, job)
    terms = {term["sense"]: term for term in saved["data"]["terms"]}
    assert terms["database journal"]["translation"] == "реестр"
    assert terms["database journal"]["origin"] == "user"
    assert terms["wood in the river"]["translation"] == "бревно"
    assert all(item["surface"] == "log" for item in saved["data"]["occurrences"])
    text = "\n".join(block["text"] for block in saved["data"]["blocks"])
    assert "реестр" in text and "бревно" in text
    assert (workspace.path / source["original"]).read_bytes()
    artifact = next(item for item in workspace.artifacts(job["id"]) if item["kind"] == "epub")
    with ZipFile(workspace.path / artifact["path"]) as archive:
        assert archive.read("EPUB/flow.svg")
    assert (
        submit(workspace, source, glossary=job["params"]["glossary_seed"], request_key="book")["id"]
        == job["id"]
    )


def test_projection_snapshot_survives_render_and_regeneration(tmp_path, monkeypatch):
    from brofessor.infrastructure.storage.workspace import Workspace
    from tests.helpers.epub import epub2_entries, make_book

    book = make_book(tmp_path, epub2_entries())
    workspace = Workspace(tmp_path / "workspace")
    source = workspace.add_source(book.source)
    model = FakeBookModel()
    monkeypatch.setattr("brofessor.infrastructure.text.runners.generate", model)
    job = submit(workspace, source)
    saved = run(workspace, job)
    rendered = book_translation.render(workspace, job["id"], start_worker=False)
    assert rendered["params"]["epub_projection"] == 3
    calls = len(model.calls)
    run(workspace, rendered)
    assert any(item["kind"] == "epub" for item in workspace.artifacts(rendered["id"]))
    assert len(model.calls) == calls
    child = tasks.regenerate(workspace, job["id"], start_worker=False)
    assert run(workspace, child)["data"]["blocks"] == saved["data"]["blocks"]


def test_late_discovered_glossary_meaning_applies_to_earlier_unanchored_packet(monkeypatch):
    from types import SimpleNamespace

    from brofessor.infrastructure.formats.epub import TextBlock

    book = SimpleNamespace(
        blocks=[
            TextBlock(
                "early", "chapter", "early", "Move indicator. " + "Narrative context. " * 100, {}
            ),
            TextBlock(
                "late", "chapter", "late", "Read indicator. " + "Narrative context. " * 100, {}
            ),
        ]
    )
    terms = [
        {
            "id": "cursor",
            "term": "indicator",
            "sense": "slide rule cursor",
            "translation": "бегунок",
            "origin": "automatic",
        }
    ]
    occurrences = [
        {
            "id": "found-late",
            "term_id": "cursor",
            "block_id": "late",
            "start": 5,
            "end": 14,
            "quote": "Read indicator.",
            "surface": "indicator",
        }
    ]
    monkeypatch.setattr(terminology, "PROMPT_BUDGET", 5800)

    def generate(prompt, schema, validate):
        data, links = payloads(prompt)
        target = next((term["translation"] for term in data["glossary"]), "указатель")
        value = {
            "blocks": [
                {
                    "id": block["id"],
                    "text": block["text"].replace("indicator", target),
                    "targets": [
                        {
                            "occurrence_id": item["id"],
                            "quote": target,
                            "surface": target,
                            "match": 1,
                        }
                        for item in links["occurrences"]
                        if item["block_id"] == block["id"]
                    ],
                }
                for block in data["blocks"]
            ]
        }
        validate(value)
        return value

    result = terminology.translate(
        book, terms, occurrences, "ru", generate, lambda: None, lambda _: None
    )
    assert result[0]["text"].startswith("Move бегунок.")


def test_term_correction_preserves_other_meaning_manual_words_and_prior_revisions(
    tmp_path, monkeypatch
):
    workspace, source = workspace_with_book(tmp_path)
    monkeypatch.setattr("brofessor.infrastructure.text.runners.generate", FakeBookModel())
    job = submit(workspace, source)
    first = run(workspace, job)
    original = copy.deepcopy(first)
    edited = service.edit_draft(
        workspace,
        job["id"],
        text_edits(
            first,
            lambda text: text.replace("records;", "AUTHOR WORDING;").replace(
                "The журнал records", "The авторский термин records"
            ),
        ),
        1,
    )
    journal = next(term for term in edited["data"]["terms"] if term["sense"] == "database journal")
    correction = book_translation.revise_term(
        workspace, job["id"], journal["id"], "протокол", revision=2, start_worker=False
    )
    result = run(workspace, correction)
    text = "\n".join(block["text"] for block in result["data"]["blocks"])
    assert "протокол" in text and "бревно" in text
    assert "AUTHOR WORDING" in text and "авторский термин" in text
    assert result["data"]["retained_manual"]
    for before, after in zip(edited["data"]["blocks"], result["data"]["blocks"], strict=True):
        assert after["text"] == before["text"].replace("журнал", "протокол")
    assert workspace.draft(job["id"], 1) == original
    assert workspace.draft(job["id"], 2) == edited
    assert tasks.root_job(correction, {j["id"]: j for j in workspace.jobs()}) == job["id"]
    assert (
        book_translation.revise_term(
            workspace, job["id"], journal["id"], "протокол", revision=2, start_worker=False
        )["id"]
        == correction["id"]
    )


def test_resume_reuses_accepted_glossary_and_translation_packets(tmp_path, monkeypatch):
    workspace, source = workspace_with_book(tmp_path, paragraphs=35)
    monkeypatch.setattr(terminology, "PROMPT_BUDGET", 10000)
    model = FakeBookModel(review=True)
    translated_calls = []

    def fail(name, prompt):
        if name == "AlignedBatch":
            translated_calls.append(prompt)
            return len(translated_calls) == 2
        return False

    model.fail = fail
    monkeypatch.setattr("brofessor.infrastructure.text.runners.generate", model)
    job = submit(workspace, source)
    with pytest.raises(RuntimeError, match="controlled"):
        run(workspace, job)
    accepted = [(call["schema"], call["prompt"]) for call in model.calls[:-1]]
    assert any(name == "AlignedBatch" for name, _ in accepted)
    model.fail = None
    saved = run(workspace, job)
    assert any(t["term"] == "database" for t in saved["data"]["terms"])
    assert any(o["surface"] == "database" for o in saved["data"]["occurrences"])
    for name, prompt in accepted:
        assert sum(call["schema"] == name and call["prompt"] == prompt for call in model.calls) == 1
    assert all(call["model"] == "frozen-text-model" for call in model.calls)
    assert all(len(call["prompt"]) <= terminology.PROMPT_BUDGET for call in model.calls)


def test_invalid_alignment_is_repaired_without_regenerating_or_rewriting_prose(
    tmp_path, monkeypatch
):
    workspace, source = workspace_with_book(tmp_path)
    model = FakeBookModel(bad_alignment=True)
    monkeypatch.setattr("brofessor.infrastructure.text.runners.generate", model)
    job = submit(workspace, source)
    saved = run(workspace, job)
    repairs = [c for c in model.calls if c["schema"] == "AlignmentBatch"]
    assert repairs
    accepted = {b["id"]: b["text"] for b in saved["data"]["blocks"]}
    for call in repairs:
        for b in payloads(call["prompt"])[0]["blocks"]:
            assert accepted[b["id"]] == b["text"]
    translated = [c["prompt"] for c in model.calls if c["schema"] == "AlignedBatch"]
    assert len(translated) == len(set(translated))
    assert any(a["kind"] == "epub" for a in workspace.artifacts(job["id"]))


def test_unconfirmed_alignment_repair_cannot_publish_a_draft_or_epub(tmp_path, monkeypatch):
    workspace, source = workspace_with_book(tmp_path)
    model = FakeBookModel(bad_alignment=True, bad_repair=True)
    monkeypatch.setattr("brofessor.infrastructure.text.runners.generate", model)
    job = submit(workspace, source)
    with pytest.raises(ValueError, match="quote"):
        run(workspace, job)
    assert workspace.draft(job["id"]) is None
    assert not any(a["kind"] == "epub" for a in workspace.artifacts(job["id"]))
    repairs = [c for c in model.calls if c["schema"] == "AlignmentBatch"]
    assert len(repairs) == 1  # One bounded repair; no retry loop accepts guessed links.


def test_resume_after_export_failure_keeps_saved_manual_edits_and_avoids_models(
    tmp_path, monkeypatch
):
    workspace, source = workspace_with_book(tmp_path)
    monkeypatch.setattr("brofessor.infrastructure.text.runners.generate", FakeBookModel())
    job = submit(workspace, source)
    render = book_translation.export
    monkeypatch.setattr(
        book_translation,
        "export",
        lambda *args: (_ for _ in ()).throw(OSError("controlled disk fault")),
    )
    with pytest.raises(OSError):
        run(workspace, job)
    first = workspace.draft(job["id"])
    service.edit_draft(
        workspace,
        job["id"],
        text_edits(first, lambda text: text.replace("floats", "AUTHOR OBSERVATION")),
        1,
    )
    monkeypatch.setattr(book_translation, "export", render)
    monkeypatch.setattr(
        "brofessor.infrastructure.text.runners.generate",
        lambda *args, **kwargs: pytest.fail("accepted text must be reused"),
    )
    result = run(workspace, job)
    assert result["revision"] == 2
    artifact = next(item for item in workspace.artifacts(job["id"]) if item["kind"] == "epub")
    assert artifact["metadata"]["revision"] == 2


def test_invented_quote_is_not_checkpointed_or_published(tmp_path, monkeypatch):
    workspace, source = workspace_with_book(tmp_path)
    model = FakeBookModel()
    model.invalid_quote = True
    monkeypatch.setattr("brofessor.infrastructure.text.runners.generate", model)
    job = submit(workspace, source)
    with pytest.raises(ValueError, match="quote"):
        run(workspace, job)
    assert workspace.draft(job["id"]) is None
    assert not workspace.artifacts(job["id"])
    assert not list((workspace.path / "jobs" / job["id"]).rglob("checkpoints/*.json"))


def test_source_change_after_submission_fails_before_inference(tmp_path, monkeypatch):
    workspace, source = workspace_with_book(tmp_path)
    job = submit(workspace, source)
    path = workspace.path / source["original"]
    with ZipFile(path, "a") as archive:
        archive.writestr("new.txt", "external modification")
    monkeypatch.setattr(
        "brofessor.infrastructure.text.runners.generate",
        lambda *args, **kwargs: pytest.fail("source changed"),
    )
    with pytest.raises(ValueError, match="changed"):
        run(workspace, job)


def test_manual_editor_cannot_reassign_meanings_or_forge_provenance(tmp_path, monkeypatch):
    workspace, source = workspace_with_book(tmp_path)
    monkeypatch.setattr("brofessor.infrastructure.text.runners.generate", FakeBookModel())
    job = submit(workspace, source)
    first = run(workspace, job)
    data = copy.deepcopy(first["data"])
    data["terms"][0]["translation"] = "bad reassignment"
    with pytest.raises(ValueError, match="text only"):
        service.edit_draft(workspace, job["id"], data, 1)
    data = copy.deepcopy(first["data"])
    block = next(block for block in data["blocks"] if block["anchors"])
    block["anchors"][0]["start"] += 1
    with pytest.raises(ValueError, match="provenance"):
        service.edit_draft(workspace, job["id"], data, 1)
    assert workspace.draft(job["id"]) == first


def test_render_pins_revision_and_never_calls_a_text_model(tmp_path, monkeypatch):
    workspace, source = workspace_with_book(tmp_path)
    monkeypatch.setattr("brofessor.infrastructure.text.runners.generate", FakeBookModel())
    job = submit(workspace, source)
    first = run(workspace, job)
    render = service.render(workspace, job["id"], revision=1, start_worker=False)
    service.edit_draft(
        workspace,
        job["id"],
        text_edits(first, lambda text: text.replace("floats", "LATER EDIT")),
        1,
    )
    monkeypatch.setattr(
        "brofessor.infrastructure.text.runners.generate",
        lambda *args, **kwargs: pytest.fail("render is local"),
    )
    pipeline.execute(workspace, render)
    output = service.rendered_file(workspace, render)
    with ZipFile(output) as archive:
        assert b"LATER EDIT" not in archive.read("EPUB/chapter.xhtml")
    assert render["params"]["revision"] == 1


def test_user_glossary_and_translation_only_options_are_validated_before_enqueue(tmp_path):
    workspace, source = workspace_with_book(tmp_path)
    entry = {"term": "log", "sense": "journal", "translation": "журнал"}
    with pytest.raises(ValueError, match="repeats"):
        submit(workspace, source, glossary=[entry, entry])
    with pytest.raises(ValueError, match="glossary applies"):
        service.submit(workspace, JobKind.SLIDES, glossary=[entry], start_worker=False)
    with pytest.raises(ValueError, match="Book translation takes"):
        submit(workspace, source, minutes=20)
    assert workspace.jobs() == []


def test_regeneration_reuses_the_pinned_glossary_and_keeps_the_previous_run(tmp_path, monkeypatch):
    workspace, source = workspace_with_book(tmp_path)
    monkeypatch.setattr("brofessor.infrastructure.text.runners.generate", FakeBookModel())
    job = submit(workspace, source)
    first = run(workspace, job)
    model = FakeBookModel()
    model.fail = lambda name, prompt: name == "GlossaryBatch"
    monkeypatch.setattr("brofessor.infrastructure.text.runners.generate", model)
    regenerated = tasks.regenerate(workspace, job["id"], revision=1, start_worker=False)
    result = run(workspace, regenerated)
    assert result["data"]["terms"] == first["data"]["terms"]
    assert result["data"]["occurrences"] == first["data"]["occurrences"]
    assert workspace.draft(job["id"]) == first
    assert regenerated["params"]["regeneration"] == {"job_id": job["id"], "revision": 1}


def test_a_failed_correction_preserves_parent_and_reuses_accepted_phrase_packets(
    tmp_path, monkeypatch
):
    workspace, source = workspace_with_book(tmp_path, paragraphs=20)
    monkeypatch.setattr("brofessor.infrastructure.text.runners.generate", FakeBookModel())
    job = submit(workspace, source)
    first = run(workspace, job)
    term = next(term for term in first["data"]["terms"] if term["sense"] == "database journal")
    correction = book_translation.revise_term(
        workspace, job["id"], term["id"], "протокол", start_worker=False
    )
    monkeypatch.setattr(terminology, "PROMPT_BUDGET", 7000)
    model = FakeBookModel()
    attempts = []

    def fail(name, prompt):
        attempts.append(prompt)
        return len(attempts) == 2

    model.fail = fail
    monkeypatch.setattr("brofessor.infrastructure.text.runners.generate", model)
    with pytest.raises(RuntimeError, match="controlled"):
        run(workspace, correction)
    assert workspace.draft(job["id"]) == first
    assert workspace.draft(correction["id"]) is None
    model.fail = None
    run(workspace, correction)
    assert sum(call["prompt"] == attempts[0] for call in model.calls) == 1


def test_conflicting_or_overlapping_glossary_proposals_are_rejected(tmp_path):
    workspace, source = workspace_with_book(tmp_path)
    book = book_translation.source_book(
        workspace, {"source_ids": [source["id"]], "epub_projection": 3}
    )
    block = next(block for block in book.blocks if "wooden log" in block.text)
    quote = terminology.MARKER.sub("", block.text)
    proposal = {
        "term": "log",
        "sense": "journal",
        "translation": "журнал",
        "existing_id": None,
        "occurrences": [{"block_id": block.id, "quote": quote, "surface": "log", "match": 1}],
    }
    bad = {"assessed_blocks": [block.id], "terms": [proposal, copy.deepcopy(proposal)]}
    with pytest.raises(ValueError, match="overlap"):
        terminology.merge_proposals(bad, [block], [], [], book.source_hash)
    supplied = terminology.seeds([{k: proposal[k] for k in ("term", "sense", "translation")}])
    proposal["translation"] = "другой перевод"
    with pytest.raises(ValueError, match="Conflicting"):
        terminology.merge_proposals(
            {"assessed_blocks": [block.id], "terms": [proposal]},
            [block],
            supplied,
            [],
            book.source_hash,
        )
