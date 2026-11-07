import json

import pytest
from streamlit.testing.v1 import AppTest
from streamlit.testing.v1.util import patch_config_options
from typer.testing import CliRunner

from brofessor.application import pipeline, service
from brofessor.contracts.content import ContentLanguage
from brofessor.contracts.jobs import JobKind, JobStatus
from brofessor.contracts.text import TextProvider
from brofessor.infrastructure.storage import preferences
from brofessor.interfaces.cli.app import app
from tests.helpers.books import FakeBookModel, workspace_with_book
from tests.helpers.ui import UI_APP, choose_language, create, new_key


@pytest.fixture(autouse=True)
def offline_interfaces(monkeypatch):
    monkeypatch.setattr("brofessor.application.worker.ensure_worker", lambda workspace: None)
    monkeypatch.setattr("brofessor.infrastructure.text.runners.generate", FakeBookModel())
    with patch_config_options({"browser.gatherUsageStats": False}):
        yield


def load_ui(workspace, monkeypatch):
    monkeypatch.setattr("sys.argv", ["ui.py", "--workspace", str(workspace.path)])
    ui = AppTest.from_file(UI_APP, default_timeout=30).run()
    assert not ui.exception
    return ui


def cli(workspace, *args):
    result = CliRunner().invoke(app, ["-w", str(workspace.path), *args])
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def test_ui_and_cli_create_same_translation_contract_and_show_same_glossary(tmp_path, monkeypatch):
    workspace, source = workspace_with_book(tmp_path)
    preferences.save_settings(
        language=ContentLanguage.RU,
        speech_model="qwen3-base",
        provider=TextProvider.CODEX,
        model="test-model",
    )
    ui = load_ui(workspace, monkeypatch)
    create(ui)
    ui.selectbox(key=new_key(ui, "kind")).select("translate_epub").run()
    assert not ui.exception
    assert not any(widget.key and widget.key.endswith(":new:focus") for widget in ui.text_area)
    ui.button(key="prepare").click().run()
    assert not ui.exception
    from_ui = workspace.jobs()[0]
    from_cli = cli(
        workspace, "translate", source["id"], "--provider", "codex", "--model", "test-model"
    )
    assert from_ui["kind"] == from_cli["kind"] == "translate_epub"
    assert from_ui["params"] == from_cli["params"]
    pipeline.execute(workspace, from_ui)
    workspace.update_job(from_ui["id"], status=JobStatus.SUCCEEDED)
    ui.run()
    assert not ui.exception
    glossary = cli(workspace, "book", "glossary", from_ui["id"])
    assert glossary["terms"] == workspace.draft(from_ui["id"])["data"]["terms"]
    assert any(expander.label == "Словарь книги" for expander in ui.expander)
    choose_language(ui, "en")
    assert any(expander.label == "Book terminology" for expander in ui.expander)


def test_ui_correction_is_same_durable_operation_as_cli_and_keeps_saved_revision(
    tmp_path, monkeypatch
):
    workspace, source = workspace_with_book(tmp_path)
    job = service.submit(
        workspace, JobKind.TRANSLATE_EPUB, source_ids=[source["id"]], start_worker=False
    )
    pipeline.execute(workspace, job)
    workspace.update_job(job["id"], status=JobStatus.SUCCEEDED)
    saved = workspace.draft(job["id"])
    term = next(term for term in saved["data"]["terms"] if term["sense"] == "database journal")
    ui = load_ui(workspace, monkeypatch)
    prefix = f"book:{workspace.path}:{job['id']}:1"
    ui.selectbox(key="ui:" + prefix + ":meaning").select(term["id"]).run()
    ui.text_input(key="ui:" + prefix + ":target:" + term["id"]).set_value("реестр").run()
    ui.button(key=prefix + ":update").click().run()
    assert not ui.exception
    correction = workspace.jobs()[0]
    through_cli = cli(workspace, "book", "term", job["id"], term["id"], "реестр", "--revision", "1")
    assert through_cli["id"] == correction["id"]
    assert correction["params"]["regeneration"] == {"job_id": job["id"], "revision": 1}
    pipeline.execute(workspace, correction)
    workspace.update_job(correction["id"], status=JobStatus.SUCCEEDED)
    ui.run()
    assert not ui.exception
    assert ui.session_state[f"ui:{workspace.path}:selected-job"] == correction["id"]
    assert workspace.draft(job["id"], 1) == saved
    assert any(
        term["translation"] == "реестр"
        for term in workspace.draft(correction["id"])["data"]["terms"]
    )


def test_ui_translation_editor_protects_unsaved_block_text_and_saves_a_revision(
    tmp_path, monkeypatch
):
    workspace, source = workspace_with_book(tmp_path)
    job = service.submit(
        workspace, JobKind.TRANSLATE_EPUB, source_ids=[source["id"]], start_worker=False
    )
    pipeline.execute(workspace, job)
    workspace.update_job(job["id"], status=JobStatus.SUCCEEDED)
    first = workspace.draft(job["id"])
    ui = load_ui(workspace, monkeypatch)
    ui.button(key="edit-" + job["id"]).click().run()
    key = next(widget.key for widget in ui.text_area if widget.label == "Перевод фрагмента")
    ui.text_area(key=key).set_value(ui.text_area(key=key).value + " Авторская правка.").run()
    assert list((workspace.path / "recovery" / job["id"]).glob("*.json"))
    ui.button(key="save-" + job["id"]).click().run()
    assert not ui.exception
    second = workspace.draft(job["id"])
    assert second["revision"] == 2
    assert any("Авторская правка." in block["text"] for block in second["data"]["blocks"])
    assert workspace.draft(job["id"], 1) == first


def test_existing_epub_can_be_rebuilt_locally_and_latest_export_is_downloaded(
    tmp_path, monkeypatch
):
    from brofessor.features.books import translation as book_translation

    workspace, source = workspace_with_book(tmp_path)
    model = FakeBookModel()
    monkeypatch.setattr("brofessor.infrastructure.text.runners.generate", model)
    job = service.submit(
        workspace, JobKind.TRANSLATE_EPUB, source_ids=[source["id"]], start_worker=False
    )
    pipeline.execute(workspace, job)
    workspace.update_job(job["id"], status=JobStatus.SUCCEEDED)
    saved = workspace.draft(job["id"])
    original_export = service.rendered_file(workspace, job)
    original_bytes = original_export.read_bytes()
    calls = len(model.calls)
    ui = load_ui(workspace, monkeypatch)
    ui.button(key=f"book:{workspace.path}:{job['id']}:1:render").click().run()
    assert not ui.exception
    rendered = next(item for item in workspace.jobs() if item["kind"] == "render_epub")
    pipeline.execute(workspace, rendered)
    workspace.update_job(rendered["id"], status=JobStatus.SUCCEEDED)
    ui.run()
    assert not ui.exception
    chosen = book_translation.rendered_artifact(workspace, job, 1)
    assert chosen["job_id"] == rendered["id"]
    assert service.rendered_file(workspace, job) == service.artifact_path(workspace, chosen["path"])
    assert original_export.read_bytes() == original_bytes
    assert workspace.draft(job["id"]) == saved
    assert len(model.calls) == calls


def test_original_passage_shows_protected_math_instead_of_hiding_it(tmp_path):
    from brofessor.features.books import translation as book_translation
    from brofessor.infrastructure.storage.workspace import Workspace
    from tests.helpers.epub import make_book

    book = make_book(
        tmp_path,
        {
            "EPUB/chapter.xhtml": b"""<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Math</title></head><body><p>Compute square(4) before reading.</p></body></html>"""
        },
    )
    workspace = Workspace(tmp_path / "original-view")
    source = workspace.add_source(book.source)
    job = service.submit(
        workspace, JobKind.TRANSLATE_EPUB, source_ids=[source["id"]], start_worker=False
    )
    original = book_translation.source_book(workspace, job["params"])
    block = next(b for b in original.blocks if "square(4)" in b.protected.values())
    ui = AppTest.from_string(f"""
from brofessor.infrastructure.storage.workspace import Workspace
from brofessor.interfaces.web.components.translation import original
w = Workspace({str(workspace.path)!r})
original(w, w.job({job["id"]!r}), {block.id!r}, lambda message: message)
""").run()
    assert not ui.exception
    assert any(
        "Compute square(4) before reading." in element.proto.body for element in ui.get("html")
    )
    assert workspace.draft(job["id"]) is None


@pytest.mark.parametrize("kind", ["translate_epub", "translate_pdf"])
def test_history_reads_original_job_without_changing_current_translation_edits(
    tmp_path, monkeypatch, kind
):
    import copy

    from brofessor.infrastructure.storage.workspace import Workspace
    from tests.helpers.pdf import PdfModel, make_pdf

    if kind == "translate_epub":
        workspace, source = workspace_with_book(tmp_path, paragraphs=2)
        model = FakeBookModel()
    else:
        workspace = Workspace(tmp_path / "workspace")
        source = workspace.add_source(make_pdf(tmp_path / "book.pdf", pages=1))
        model = PdfModel()
    monkeypatch.setattr("brofessor.infrastructure.text.runners.generate", model)
    job = service.submit(workspace, kind, source_ids=[source["id"]], start_worker=False)
    pipeline.execute(workspace, job)
    workspace.update_job(job["id"], status=JobStatus.SUCCEEDED)
    first = workspace.draft(job["id"])
    old_path = service.rendered_file(workspace, job)
    old_file = old_path.read_bytes()
    updated = copy.deepcopy(first["data"])
    updated["blocks"][-1]["text"] += " Saved author edit."
    second = service.edit_draft(workspace, job["id"], updated, 1)
    ui = load_ui(workspace, monkeypatch)
    ui.button(key="edit-" + job["id"]).click().run()
    key = f"editor:{workspace.path}:{job['id']}"
    ui.selectbox(key=key + ":item:selected").select(len(updated["blocks"]) - 1).run()
    field = next(w for w in ui.text_area if w.label == "Перевод фрагмента")
    field.set_value(field.value + " Unsaved author edit.").run()
    buffer = ui.session_state[key + ":text"]
    copies = {
        p.name: p.read_bytes() for p in (workspace.path / "recovery" / job["id"]).glob("*.json")
    }
    calls = copy.deepcopy(model.calls)
    jobs = workspace.jobs()
    ui.selectbox(key=key + ":history").select(1).run()
    ui.button(key=key + ":show-history").click().run()
    assert not ui.exception
    historical = key + ":history:1:item:selected"
    assert ui.selectbox(key=historical).value == 0
    ui.selectbox(key=historical).select(1).run()
    assert not ui.exception
    assert ui.session_state[key + ":text"] == buffer
    assert ui.selectbox(key=key + ":item:selected").value == len(updated["blocks"]) - 1
    assert {
        p.name: p.read_bytes() for p in (workspace.path / "recovery" / job["id"]).glob("*.json")
    } == copies
    assert workspace.draft(job["id"]) == second
    assert workspace.draft(job["id"], 1) == first
    assert old_path.read_bytes() == old_file
    assert model.calls == calls and workspace.jobs() == jobs


@pytest.mark.parametrize("kind", ["translate_epub", "translate_pdf"])
def test_first_book_file_remains_available_while_a_rebuild_is_queued_or_failed(
    tmp_path, monkeypatch, kind
):
    from brofessor.infrastructure.storage.workspace import Workspace
    from tests.helpers.pdf import PdfModel, make_pdf

    if kind == "translate_epub":
        workspace, source = workspace_with_book(tmp_path)
        model = FakeBookModel()
    else:
        workspace = Workspace(tmp_path / "workspace")
        source = workspace.add_source(make_pdf(tmp_path / "book.pdf", pages=1))
        model = PdfModel()
    monkeypatch.setattr("brofessor.infrastructure.text.runners.generate", model)
    job = service.submit(workspace, kind, source_ids=[source["id"]], start_worker=False)
    pipeline.execute(workspace, job)
    workspace.update_job(job["id"], status=JobStatus.SUCCEEDED)
    old_file = service.rendered_file(workspace, job)
    content = old_file.read_bytes()
    ui = load_ui(workspace, monkeypatch)
    ui.button(key=f"book:{workspace.path}:{job['id']}:1:render").click().run()
    render = next(j for j in workspace.jobs() if j["kind"].startswith("render_"))
    choice = f"ui:{workspace.path}:render:{job['id']}"
    for status in ("queued", "failed"):
        workspace.update_job(render["id"], status=status)
        ui.run()
        assert not ui.exception
        assert ui.selectbox(key=choice).value == job["id"]
        assert any(b.label.endswith(old_file.name) for b in ui.get("download_button"))
        assert old_file.read_bytes() == content
