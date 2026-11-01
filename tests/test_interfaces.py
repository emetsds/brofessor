import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest
from streamlit.testing.v1.util import patch_config_options
from typer.testing import CliRunner

from brofessor import service
from brofessor.cli import app
from brofessor.workspace import Workspace


@pytest.fixture(autouse=True)
def offline_streamlit_config():
    # AppTest otherwise collects page-profile telemetry, including installed
    # agents/skills from the host filesystem. That is outside these UI contracts.
    with patch_config_options({"browser.gatherUsageStats": False}):
        yield


def test_cli_import_is_visible_in_ui(tmp_path, monkeypatch):
    path = tmp_path / "workspace"
    source = tmp_path / "chapter.md"
    source.write_text("A reliable bridge carries 1200 kilograms.")
    runner = CliRunner()
    result = runner.invoke(app, ["-w", str(path), "source", "add", str(source)])
    assert result.exit_code == 0, result.output
    monkeypatch.setattr("sys.argv", ["ui.py", "--workspace", str(path)])
    ui = AppTest.from_file(
        str(Path(__file__).parents[1] / "src/brofessor/ui.py"), default_timeout=10
    ).run()
    assert not ui.exception
    assert any(expander.label == "chapter.md" for expander in ui.expander)
    assert Workspace(path).sources()[0]["name"] == "chapter.md"


def test_cli_and_ui_submit_same_service(tmp_path, monkeypatch):
    path = tmp_path / "workspace"
    source = tmp_path / "chapter.md"
    source.write_text("Testing assumptions matters.")
    Workspace(path).add_source(source)
    monkeypatch.setattr("brofessor.worker.ensure_worker", lambda workspace: None)
    runner = CliRunner()
    result = runner.invoke(app, ["-w", str(path), "podcast", "--focus", "Testing"])
    assert result.exit_code == 0, result.output
    monkeypatch.setattr("sys.argv", ["ui.py", "--workspace", str(path)])
    ui = AppTest.from_file(
        str(Path(__file__).parents[1] / "src/brofessor/ui.py"), default_timeout=10
    ).run()
    for button in ui.button:
        if button.label == "Подготовить":
            button.click().run()
            break
    assert not ui.exception
    jobs = Workspace(path).jobs()
    assert len(jobs) == 2
    assert jobs[0]["kind"] == jobs[1]["kind"] == "podcast"
    assert jobs[0]["params"]["source_ids"] == jobs[1]["params"]["source_ids"]
    for button in ui.button:
        if button.label == "Подготовить":
            button.click().run()
            break
    assert len(Workspace(path).jobs()) == 2


def test_external_edit_preserves_unsaved_ui_buffer(tmp_path, monkeypatch):
    workspace = Workspace(tmp_path / "workspace")
    source = tmp_path / "chapter.md"
    source.write_text("A bridge carries 1200 kilograms.")
    workspace.add_source(source)
    citation = workspace.units()[0]["id"]
    job = service.submit(workspace, "ask", focus="Load?", start_worker=False)
    workspace.save_draft(job["id"], {"answer": "1200 kg", "citations": [citation]})
    workspace.update_job(job["id"], status="succeeded")
    monkeypatch.setattr("sys.argv", ["ui.py", "--workspace", str(workspace.path)])
    ui = AppTest.from_file(
        str(Path(__file__).parents[1] / "src/brofessor/ui.py"), default_timeout=10
    ).run()
    buffer_key = f"editor:{workspace.path}:{job['id']}:text"
    unsaved = json.dumps({"answer": "Unsaved wording", "citations": [citation]})
    ui.text_area(key=buffer_key).set_value(unsaved).run()
    service.edit_draft(
        workspace, job["id"], {"answer": "CLI correction", "citations": [citation]}, 1
    )
    ui.run()
    assert ui.text_area(key=buffer_key).value == unsaved
    ui.button(key=f"save-{job['id']}").click().run()
    assert not ui.exception
    assert any("Draft changed" in error.value for error in ui.error)
    assert workspace.draft(job["id"])["data"]["answer"] == "CLI correction"
