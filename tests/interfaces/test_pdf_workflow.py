import copy
import json

import pytest
from streamlit.testing.v1 import AppTest
from typer.testing import CliRunner

from brofessor.application import pipeline, service, tasks
from brofessor.contracts.content import ContentLanguage
from brofessor.contracts.jobs import JobKind, JobStatus
from brofessor.contracts.text import TextProvider
from brofessor.infrastructure.storage import preferences
from brofessor.interfaces.cli.app import app
from tests.helpers.pdf import workspace_with_pdf
from tests.helpers.ui import UI_APP, create, new_key


def test_pdf_resume_keeps_glossary_and_saved_edits_render_without_model(tmp_path, monkeypatch):
    workspace, source, model = workspace_with_pdf(tmp_path, monkeypatch)
    job = service.submit(
        workspace, JobKind.TRANSLATE_PDF, source_ids=[source["id"]], start_worker=False
    )
    model.fail = True
    with pytest.raises(RuntimeError, match="controlled"):
        pipeline.execute(workspace, job)
    assert workspace.draft(job["id"]) is None
    glossary_calls = model.calls.count("GlossaryBatch")
    model.fail = False
    pipeline.execute(workspace, job)
    first = workspace.draft(job["id"])
    assert model.calls.count("GlossaryBatch") == glossary_calls
    assert service.rendered_file(workspace, job).suffix == ".pdf"
    data = copy.deepcopy(first["data"])
    data["blocks"][0]["text"] = "Приём данных датчиков"
    second = service.edit_draft(workspace, job["id"], data, first["revision"])
    render = service.render(workspace, job["id"], revision=second["revision"], start_worker=False)
    service.edit_draft(workspace, job["id"], second["data"], second["revision"])
    calls = list(model.calls)
    pipeline.execute(workspace, render)
    assert model.calls == calls
    assert render["params"]["revision"] == second["revision"]
    assert workspace.draft(job["id"], 1) == first
    assert tasks.list_tasks(workspace)[0]["kind"] == "translate_pdf"
    artifact = next(a for a in workspace.artifacts(render["id"]) if a["kind"] == "pdf")
    mapping = json.loads((workspace.path / artifact["metadata"]["layout"]).read_text())
    assert {b["id"] for b in mapping["blocks"]} == {b["id"] for b in first["data"]["blocks"]}
    assert mapping["preserved"]


def test_pdf_ui_cli_contract_revision_editor_and_regeneration(tmp_path, monkeypatch):
    workspace, source, model = workspace_with_pdf(tmp_path, monkeypatch)
    preferences.save_settings(
        language=ContentLanguage.RU,
        speech_model="qwen3-base",
        provider=TextProvider.CODEX,
        model="test-model",
    )
    monkeypatch.setattr("sys.argv", ["ui.py", "--workspace", str(workspace.path)])
    ui = AppTest.from_file(UI_APP, default_timeout=30).run()
    create(ui)
    ui.selectbox(key=new_key(ui, "kind")).select("translate_pdf").run()
    assert not ui.exception
    assert not any(w.key and w.key.endswith(":new:focus") for w in ui.text_area)
    ui.button(key="prepare").click().run()
    assert not ui.exception
    job = workspace.jobs()[0]
    result = CliRunner().invoke(
        app,
        [
            "-w",
            str(workspace.path),
            "translate",
            source["id"],
            "--provider",
            "codex",
            "--model",
            "test-model",
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["params"] == job["params"]
    pipeline.execute(workspace, job)
    workspace.update_job(job["id"], status=JobStatus.SUCCEEDED)
    ui.run()
    assert not ui.exception
    assert any(e.label == "Сохранённые объекты PDF" for e in ui.expander)
    ui.button(key="edit-" + job["id"]).click().run()
    key = next(w.key for w in ui.text_area if w.label == "Перевод фрагмента")
    ui.text_area(key=key).set_value("Приём данных датчиков").run()
    ui.button(key="save-" + job["id"]).click().run()
    assert not ui.exception
    assert workspace.draft(job["id"])["revision"] == 2
    ui.button(key=f"book:{workspace.path}:{job['id']}:2:render").click().run()
    assert not ui.exception
    render = next(j for j in workspace.jobs() if j["kind"] == "render_pdf")
    pipeline.execute(workspace, render)
    workspace.update_job(render["id"], status=JobStatus.SUCCEEDED)
    calls = len(model.calls)
    regenerated = tasks.regenerate(workspace, job["id"], start_worker=False)
    assert regenerated["params"]["pdf_projection"] == job["params"]["pdf_projection"]
    assert regenerated["params"]["reuse_glossary"]
    pipeline.execute(workspace, regenerated)
    assert "GlossaryBatch" not in model.calls[calls:]
    assert workspace.draft(job["id"], 2)["data"]["blocks"][0]["text"] == "Приём данных датчиков"
