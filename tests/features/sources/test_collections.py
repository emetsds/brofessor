import json
import shutil

import pytest
from typer.testing import CliRunner

from brofessor.application import pipeline, service
from brofessor.contracts.jobs import JobKind, JobStatus
from brofessor.features.sources import collections
from brofessor.features.sources import navigation as source_navigation
from brofessor.infrastructure.storage.workspace import Workspace
from brofessor.interfaces.cli.app import app
from tests.helpers.collections import Navigator, navigation_context, vault
from tests.helpers.ui import UI_APP


def setup(tmp_path, monkeypatch):
    root = vault(tmp_path)
    w = Workspace(tmp_path / "workspace")
    collection = collections.connect(w, root)
    model = Navigator()
    monkeypatch.setattr("brofessor.infrastructure.text.runners.generate", model)
    monkeypatch.setattr("brofessor.application.worker.ensure_worker", lambda _: None)
    return w, root, collection, model


def test_connect_registers_only_a_path_without_extracting_or_selecting(tmp_path, monkeypatch):
    root = vault(tmp_path)
    w = Workspace(tmp_path / "workspace")

    def forbidden(*args, **kwargs):
        raise AssertionError("Connection must not read/index/summarize documents")

    monkeypatch.setattr(w, "add_source", forbidden)
    monkeypatch.setattr("brofessor.infrastructure.formats.ingestion.extract_source", forbidden)
    entry = collections.connect(w, root)
    assert collections.connect(w, root / "Studies/..") == entry
    assert w.sources() == w.jobs() == []
    assert not (w.path / "originals").exists()
    assert collections.choices(w)[0]["id"] == entry["id"]


@pytest.mark.parametrize(
    "provider,text_model", [("codex", None), ("claude", None), ("ollama", "local-test")]
)
def test_prompt_task_reads_linked_originals_and_does_not_make_snapshots_default_sources(
    tmp_path, monkeypatch, provider, text_model
):
    w, root, collection, model = setup(tmp_path, monkeypatch)
    before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*.md")}
    job = service.submit(
        w,
        JobKind.ASK,
        focus="What latency was actually measured?",
        provider=provider,
        model=text_model,
        start_worker=False,
    )
    assert (
        job["params"]["source_ids"] == []
        and job["params"]["collections"][0]["id"] == collection["id"]
    )
    pipeline.execute(w, job)
    answer = w.draft(job["id"])
    assert set(model.providers) == {(provider, text_model)}
    assert "7 ms" in answer["data"]["answer"]
    citation = service.answer_evidence(w, job["id"])[0]
    assert citation["source"].endswith("vault/Studies/Experiment.md")
    assert citation["quotes"] == ["Measured latency was 7 ms. This was a single-machine test."]
    assert {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*.md")} == before
    assert [c["id"] for c in collections.choices(w)] == [collection["id"]]
    assert service.search(w, "Measured latency") == []
    updated = service.edit_draft(w, job["id"], answer["data"], answer["revision"])
    assert updated["data"] == answer["data"]
    assert service.coverage(w, job["id"])["units"]


def test_recovery_uses_saved_navigation_even_after_directory_is_deleted(tmp_path, monkeypatch):
    w, root, _, model = setup(tmp_path, monkeypatch)
    job = service.submit(w, JobKind.ASK, focus="Measured latency?", start_worker=False)
    model.fail_answer = True
    with pytest.raises(RuntimeError, match="controlled"):
        pipeline.execute(w, job)
    count = model.calls.count("NavigationStep")
    frozen = source_navigation.report(w, job)
    assert frozen["status"] == "complete"
    shutil.rmtree(root)
    model.fail_answer = False
    pipeline.execute(w, job)
    assert model.calls.count("NavigationStep") == count
    assert source_navigation.report(w, job) == frozen
    assert "7 ms" in service.answer_evidence(w, job["id"])[0]["text"]


def test_new_task_sees_changed_bytes_while_previous_citations_keep_original(tmp_path, monkeypatch):
    w, root, _, model = setup(tmp_path, monkeypatch)
    job = service.submit(w, JobKind.ASK, focus="Measured latency?", start_worker=False)
    pipeline.execute(w, job)
    original = service.answer_evidence(w, job["id"])
    (root / "Studies/Experiment.md").write_text(
        "# Experiment\n## Result\nMeasured latency was 9 ms.\n"
    )
    other = service.submit(w, JobKind.ASK, focus="Measured latency now?", start_worker=False)
    model.fail_answer = True
    with pytest.raises(RuntimeError):
        pipeline.execute(w, other)
    assert "9 ms" in "".join(u["text"] for u in source_navigation.units(w, other))
    assert service.answer_evidence(w, job["id"]) == original
    assert source_navigation.source_ids(w, job) != source_navigation.source_ids(w, other)


def test_catalog_search_metadata_links_and_ambiguous_names(tmp_path):
    root = vault(tmp_path)
    (root / "A").mkdir()
    (root / "B").mkdir()
    (root / "A/Same.md").write_text("# First\nAlpha.\n")
    (root / "B/Same.md").write_text("# Second\nBeta.\n")
    (root / "References.md").write_text(
        "[[Same]]\n[Result](Studies/Experiment.md#Result)\n`[[not-a-link]]`\n```md\n[[not-a-link-either]]\n```\n"
    )
    w = Workspace(tmp_path / "workspace")
    r = collections.connect(w, root)
    f = w.path / "jobs/test"
    f.mkdir(parents=True)
    c = collections.Catalog(w, [r], f)
    found = c.search("Latency study", r["id"])
    assert any(m["path"] == "Studies/Experiment.md" for m in found["matches"])
    links = c.links(r["id"], "References.md")
    assert links["outgoing"][0]["status"] == "ambiguous"
    assert set(links["outgoing"][0]["paths"]) == {"A/Same.md", "B/Same.md"}
    assert links["outgoing"][1]["paths"] == ["Studies/Experiment.md"]
    assert len(links["outgoing"]) == 2
    assert "References.md" in c.links(r["id"], "Studies/Experiment.md", incoming=True)["incoming"]


def test_symlinks_and_escaped_paths_never_read_outside_collection(tmp_path):
    root = vault(tmp_path)
    outside = tmp_path / "private.md"
    outside.write_text("secret")
    (root / "leak.md").symlink_to(outside)
    (root / "leak-directory").symlink_to(tmp_path, target_is_directory=True)
    w = Workspace(tmp_path / "workspace")
    r = collections.connect(w, root)
    f = w.path / "jobs/test"
    f.mkdir(parents=True)
    c = collections.Catalog(w, [r], f)
    with pytest.raises(ValueError, match="escapes"):
        c.key(r["id"], "../private.md")
    assert not any("leak" in item["path"] for item in c.documents.values())
    (root / "Studies/Experiment.md").unlink()
    (root / "Studies/Experiment.md").symlink_to(outside)
    with pytest.raises(ValueError, match="no longer belongs"):
        c.load(c.key(r["id"], "Studies/Experiment.md"))
    assert w.sources() == []


def test_disconnect_keeps_previous_evidence_and_followup_scope(tmp_path, monkeypatch):
    w, root, r, model = setup(tmp_path, monkeypatch)
    job = service.submit(w, JobKind.ASK, focus="Latency?", start_worker=False)
    pipeline.execute(w, job)
    w.update_job(job["id"], status=JobStatus.SUCCEEDED)
    child = service.follow_up(w, job["id"], "What was the test scope?", start_worker=False)
    assert child["params"]["collections"] == job["params"]["collections"]
    assert service.question_context(w, child["id"])["turns"]
    collections.disconnect(w, r["id"])
    assert collections.choices(w) == []
    assert service.answer_evidence(w, job["id"])
    pipeline.execute(w, child)
    assert w.draft(child["id"])


def test_cli_adds_directory_and_starts_prompt_task_with_no_file_selection(tmp_path, monkeypatch):
    root = vault(tmp_path)
    path = tmp_path / "workspace"
    runner = CliRunner()
    monkeypatch.setattr("brofessor.infrastructure.text.runners.generate", Navigator())
    monkeypatch.setattr("brofessor.application.worker.ensure_worker", lambda _: None)
    add = runner.invoke(app, ["-w", str(path), "source", "add", str(root)])
    assert add.exit_code == 0, add.output
    listing = runner.invoke(app, ["-w", str(path), "source", "list"])
    assert json.loads(listing.output)[0]["root"] == str(root)
    ask = runner.invoke(app, ["-w", str(path), "ask", "What was measured?"])
    assert ask.exit_code == 0, ask.output
    job = json.loads(ask.output)
    assert job["params"]["collections"] and job["params"]["source_ids"] == []
    workspace = Workspace(path)
    pipeline.execute(workspace, job)
    assert "7 ms" in workspace.draft(job["id"])["data"]["answer"]


def test_full_reading_cannot_finish_with_unread_originals(tmp_path, monkeypatch):
    from pydantic_ai.exceptions import UsageLimitExceeded

    w, root, r, _ = setup(tmp_path, monkeypatch)

    def premature(prompt, schema, *args, **kwargs):
        return {
            "memory": "all done",
            "exhaustive": True,
            "scope": [r["id"] + ":Studies"],
            "actions": [{"operation": "finish"}],
        }

    monkeypatch.setattr("brofessor.infrastructure.text.runners.generate", premature)
    monkeypatch.setattr(source_navigation, "MAX_STEPS", 2)
    job = service.submit(w, JobKind.ASK, focus="Read all Studies notes", start_worker=False)
    with pytest.raises(UsageLimitExceeded):
        pipeline.execute(w, job)
    assert w.draft(job["id"]) is None
    state = source_navigation.report(w, job)
    assert state["status"] != "complete"
    assert state["steps"][-1][0]["result"]["unread"][0]["path"] == "Studies/Experiment.md"


def test_full_reading_verifies_every_fragment_of_the_requested_scope(tmp_path, monkeypatch):
    w, root, r, normal = setup(tmp_path, monkeypatch)

    def full(prompt, schema, *args, **kwargs):
        if schema["title"] != "NavigationStep":
            verification = json.JSONDecoder().raw_decode(
                prompt.split("HOST RETRIEVAL COVERAGE:", 1)[1].split("\n", 1)[1]
            )[0]
            assert verification["exhaustive"] and verification["documents"] == 1
            assert verification["fragments"] == 1
            return normal(prompt, schema, *args, **kwargs)
        context = navigation_context(prompt)
        return {
            "memory": "read",
            "exhaustive": True,
            "scope": [r["id"] + ":Studies"],
            "actions": [
                {
                    "operation": "read",
                    "collection_id": r["id"],
                    "path": "Studies/Experiment.md",
                },
                {"operation": "read", "collection_id": r["id"], "path": "Главная.md"},
            ]
            if not context["memory"]
            else [{"operation": "finish"}],
        }

    monkeypatch.setattr("brofessor.infrastructure.text.runners.generate", full)
    job = service.submit(w, JobKind.ASK, focus="Read all Studies notes", start_worker=False)
    pipeline.execute(w, job)
    state = source_navigation.report(w, job)
    assert state["status"] == "complete" and state["exhaustive"]
    assert {d["path"] for d in state["documents"].values()} == {
        "Studies/Experiment.md",
        "Главная.md",
    }


def test_relative_markdown_aliases_and_blocks_resolve_without_following_external_files(tmp_path):
    root = vault(tmp_path)
    (root / "Studies/Links.md").write_text(
        "[Home](../Главная.md)\n[[Latency study#^finding]]\n[External](file:///tmp/private.md)\n"
    )
    w = Workspace(tmp_path / "workspace")
    r = collections.connect(w, root)
    f = w.path / "jobs/test"
    f.mkdir(parents=True)
    c = collections.Catalog(w, [r], f)
    links = c.links(r["id"], "Studies/Links.md")["outgoing"]
    assert links[0]["paths"] == ["Главная.md"]
    assert links[1]["paths"] == ["Studies/Experiment.md"] and links[1]["anchor"] == "^finding"
    assert links[2]["status"] == "external"


def test_pdf_epub_and_txt_are_searched_only_during_a_task(tmp_path):
    from tests.helpers.sources import make_epub, make_pdf

    root = tmp_path / "documents"
    root.mkdir()
    make_pdf(root / "Report.pdf", ["The sensor threshold is 12 volts."])
    make_epub(root / "Book.epub")
    (root / "Plain.txt").write_text("The sensor limit is 9 amperes.")
    w = Workspace(tmp_path / "workspace")
    r = collections.connect(w, root)
    assert w.sources() == []
    folder = w.path / "jobs/test"
    folder.mkdir(parents=True)
    c = collections.Catalog(w, [r], folder)
    matches = c.search("sensor", r["id"])["matches"]
    assert {m["path"] for m in matches} == {"Report.pdf", "Plain.txt"}
    assert next(m for m in matches if m["path"] == "Report.pdf")["locator"] == "page 1"
    assert c.load(c.key(r["id"], "Book.epub"))["units"]


def test_identical_notes_keep_both_paths_in_task_provenance(tmp_path, monkeypatch):
    first = tmp_path / "one"
    second = tmp_path / "two"
    first.mkdir()
    second.mkdir()
    for root in (first, second):
        (root / "Note.md").write_text("Measured latency was 7 ms. This was a single-machine test.")
    w = Workspace(tmp_path / "workspace")
    roots = [collections.connect(w, r) for r in (first, second)]
    normal = Navigator()

    def model(prompt, schema, *args, **kwargs):
        if schema["title"] != "NavigationStep":
            return normal(prompt, schema, *args, **kwargs)
        context = navigation_context(prompt)
        return {
            "memory": "read",
            "actions": [
                {"operation": "read", "collection_id": r["id"], "path": "Note.md"} for r in roots
            ]
            if not context["memory"]
            else [{"operation": "finish"}],
        }

    monkeypatch.setattr("brofessor.infrastructure.text.runners.generate", model)
    job = service.submit(w, JobKind.ASK, focus="Latency?", start_worker=False)
    pipeline.execute(w, job)
    item = service.answer_evidence(w, job["id"])[0]
    assert "one/Note.md" in item["source"] and "two/Note.md" in item["source"]
    assert len(w.sources()) == 1  # Original-byte deduplication still holds.


def test_collection_slides_render_from_saved_sources_after_vault_disappears(tmp_path, monkeypatch):
    w, root, _, normal = setup(tmp_path, monkeypatch)

    def model(prompt, schema, *args, **kwargs):
        if schema["title"] != "Slides":
            return normal(prompt, schema, *args, **kwargs)
        evidence = json.JSONDecoder().raw_decode(prompt.split("EVIDENCE:\n", 1)[1])[0]
        identifier = next(e["id"] for e in evidence if "Measured latency" in e.get("text", ""))
        return {
            "title": "Measurement",
            "language": "ru",
            "slides": [
                {
                    "title": "Latency",
                    "bullets": ["7 ms on a single machine"],
                    "notes": "",
                    "citations": [identifier],
                    "table": None,
                    "steps": [],
                }
            ],
        }

    monkeypatch.setattr("brofessor.infrastructure.text.runners.generate", model)
    job = service.submit(
        w, JobKind.SLIDES, focus="Latency measurement", slide_count=1, start_worker=False
    )
    pipeline.execute(w, job)
    saved = w.draft(job["id"])
    shutil.rmtree(root)
    render = service.render(w, job["id"], revision=saved["revision"], start_worker=False)
    monkeypatch.setattr(
        "brofessor.infrastructure.text.runners.generate",
        lambda *a, **kw: pytest.fail("Rendering must not call a model"),
    )
    pipeline.execute(w, render)
    w.update_job(render["id"], status=JobStatus.SUCCEEDED)
    from pptx import Presentation

    output = service.rendered_file(w, render)
    assert output is not None
    deck = Presentation(output)
    assert "Experiment.md" in deck.slides[0].notes_slide.notes_text_frame.text


def test_ui_connects_with_only_a_path_and_submits_same_prompt_contract(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    from tests.helpers.ui import create, new_key, section

    w = Workspace(tmp_path / "workspace")
    root = vault(tmp_path)
    monkeypatch.setattr("brofessor.infrastructure.text.runners.generate", Navigator())
    monkeypatch.setattr("brofessor.application.worker.ensure_worker", lambda _: None)
    monkeypatch.setattr("sys.argv", ["ui.py", "--workspace", str(w.path)])
    ui = AppTest.from_file(UI_APP, default_timeout=30).run()
    section(ui, "sources")
    ui.button(key="sources-add-source").click().run()
    ui.radio(key=f"ui:{w.path}:source-import:mode").set_value("folder").run()
    ui.text_input(key=f"directory:{w.path}").set_value(str(root)).run()
    ui.button(key="connect_directory").click().run()
    assert not ui.exception and not w.sources()
    create(ui)
    assert ui.selectbox(key=new_key(ui, "kind")).value == "ask"
    ui.text_area(key=new_key(ui, "focus")).set_value("What was measured?").run()
    ui.button(key="prepare").click().run()
    assert not ui.exception
    ui_job = w.jobs()[0]
    other = service.submit(
        w,
        JobKind.ASK,
        focus="What was measured?",
        title="",
        provider=ui_job["params"]["provider"],
        model=ui_job["params"]["model"],
        language=ui_job["params"]["language"],
        start_worker=False,
    )
    assert ui_job["params"] == other["params"]
    pipeline.execute(w, ui_job)
    w.update_job(ui_job["id"], status=JobStatus.SUCCEEDED)
    ui.run()
    assert not ui.exception
    assert any("7 ms" in element.proto.body for element in ui.get("html"))


@pytest.mark.parametrize("unreadable", ["Studies/Private", "."])
def test_full_reading_refuses_an_unreadable_subdirectory(tmp_path, monkeypatch, unreadable):
    w, root, r, _ = setup(tmp_path, monkeypatch)
    walk = collections.os.walk

    def inaccessible(base, *, followlinks, onerror):
        yield from walk(base, followlinks=followlinks, onerror=onerror)
        onerror(PermissionError(13, "Denied", str(root / unreadable)))

    monkeypatch.setattr(collections.os, "walk", inaccessible)
    monkeypatch.setattr(
        "brofessor.infrastructure.text.runners.generate",
        lambda *a, **kw: (
            {
                "exhaustive": True,
                "scope": [r["id"] + ":Studies"],
                "actions": [{"operation": "finish"}],
            }
        ),
    )
    job = service.submit(w, JobKind.ASK, focus="Read all Studies notes", start_worker=False)
    with pytest.raises(ValueError, match="unreadable directory"):
        pipeline.execute(w, job)
    assert w.draft(job["id"]) is None
    state = source_navigation.report(w, job)
    assert state["status"] != "complete"
    assert state["issues"][0]["path"] == unreadable


def test_failed_read_does_not_select_part_of_an_over_budget_packet(tmp_path, monkeypatch):
    w, root, r, _ = setup(tmp_path, monkeypatch)
    (root / "Studies/Big.md").write_text("a\n" * 100 + "b" * 2000 + "\n")
    monkeypatch.setattr(source_navigation, "MAX_SELECTED", 1000)

    def read_then_finish(prompt, schema, *a, **kw):
        assert schema["title"] == "NavigationStep"
        ctx = navigation_context(prompt)
        return {
            "memory": "read attempted",
            "actions": [
                {"operation": "finish"}
                if ctx["memory"]
                else {
                    "operation": "read",
                    "collection_id": r["id"],
                    "path": "Studies/Big.md",
                    "limit": 2,
                }
            ],
        }

    monkeypatch.setattr("brofessor.infrastructure.text.runners.generate", read_then_finish)
    job = service.submit(w, JobKind.ASK, focus="Read big file", start_worker=False)
    pipeline.execute(w, job)
    state = source_navigation.report(w, job)
    assert "budget" in state["steps"][0][0]["result"]["error"]
    assert state["units"] == state["documents"] == {}
    assert w.draft(job["id"])["data"]["evidence_status"] == "insufficient_evidence"
