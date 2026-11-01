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
def offline_streamlit_config(tmp_path, monkeypatch):
    # AppTest otherwise collects page-profile telemetry, including installed
    # agents/skills from the host filesystem. That is outside these UI contracts.
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
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


@pytest.mark.parametrize("command", ["ask", "slides", "podcast"])
def test_cli_saves_custom_ollama_port_with_job(tmp_path, monkeypatch, command):
    workspace = Workspace(tmp_path / "workspace")
    source = tmp_path / "chapter.md"
    source.write_text("A bridge carries 1200 kilograms.")
    workspace.add_source(source)
    monkeypatch.setattr("brofessor.worker.ensure_worker", lambda workspace: None)
    args = ["-w", str(workspace.path), command]
    if command == "ask":
        args.append("What was measured?")
    result = CliRunner().invoke(
        app, [*args, "--provider", "ollama", "--model", "tiny", "--ollama-port", "11435"]
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["params"]["ollama_port"] == 11435
    assert Workspace(workspace.path).jobs()[0]["params"]["ollama_port"] == 11435


def test_cli_doctor_uses_selected_ollama_port(tmp_path, monkeypatch):
    calls = []

    def diagnose(provider, model, *, ollama_port):
        calls.append((provider, model, ollama_port))
        return {"available": True}

    monkeypatch.setattr("brofessor.executors.doctor", diagnose)
    result = CliRunner().invoke(
        app, ["-w", str(tmp_path), "doctor", "--provider", "ollama", "--ollama-port", "11435"]
    )
    assert result.exit_code == 0, result.output
    assert calls == [("ollama", None, 11435)]


def test_ui_launch_passes_both_ports_to_streamlit(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr("brofessor.cli.subprocess.call", lambda args: calls.append(args) or 0)
    result = CliRunner().invoke(
        app, ["-w", str(tmp_path), "ui", "--port", "8502", "--ollama-port", "11435"]
    )
    assert result.exit_code == 0, result.output
    assert len(calls) == 1
    assert "--server.address=127.0.0.1" in calls[0]
    assert "--server.port=8502" in calls[0]
    app_args = calls[0][calls[0].index("--") + 1 :]
    assert app_args == ["--workspace", str(tmp_path), "--ollama-port", "11435"]


@pytest.mark.parametrize("port", ["0", "65536"])
@pytest.mark.parametrize(
    "args", [["ui", "--port"], ["ui", "--ollama-port"], ["doctor", "--ollama-port"]]
)
def test_invalid_cli_ports_fail_before_launch(tmp_path, monkeypatch, args, port):
    monkeypatch.setattr("brofessor.cli.subprocess.call", lambda *a: pytest.fail("Must not launch"))
    monkeypatch.setattr(
        "brofessor.executors.doctor", lambda *a, **k: pytest.fail("Must not connect")
    )
    result = CliRunner().invoke(app, ["-w", str(tmp_path), *args, port])
    assert result.exit_code == 2, result.output
    assert "range" in result.output


def test_ui_uses_selected_port_for_check_and_jobs(tmp_path, monkeypatch):
    workspace = Workspace(tmp_path / "workspace")
    source = tmp_path / "chapter.md"
    source.write_text("A bridge carries 1200 kilograms.")
    workspace.add_source(source)
    monkeypatch.setattr("brofessor.worker.ensure_worker", lambda workspace: None)
    calls = []

    def diagnose(provider, model, *, ollama_port):
        calls.append((provider, model, ollama_port))
        return {"available": True}

    monkeypatch.setattr("brofessor.executors.doctor", diagnose)
    monkeypatch.setattr(
        "sys.argv", ["ui.py", "--workspace", str(workspace.path), "--ollama-port", "11435"]
    )
    ui = AppTest.from_file(
        str(Path(__file__).parents[1] / "src/brofessor/ui.py"), default_timeout=10
    ).run()
    next(field for field in ui.selectbox if field.label == "Исполнитель").select("ollama").run()
    next(field for field in ui.text_input if field.label.startswith("Модель")).set_value(
        "tiny"
    ).run()
    assert not ui.exception
    assert ui.number_input(key="ollama_port").value == 11435
    ui.number_input(key="ollama_port").set_value(11436).run()
    next(field for field in ui.selectbox if field.label == "Исполнитель").select("codex").run()
    next(field for field in ui.selectbox if field.label == "Исполнитель").select("ollama").run()
    assert ui.number_input(key="ollama_port").value == 11436
    for button in ui.button:
        if button.label == "Проверить подключение":
            button.click().run()
            break
    assert calls == [("ollama", "tiny", 11436)]
    for button in ui.button:
        if button.label == "Подготовить":
            button.click().run()
            break
    assert not ui.exception
    assert workspace.jobs()[0]["params"]["ollama_port"] == 11436
    ui.number_input(key="ollama_port").set_value(11437).run()
    for button in ui.button:
        if button.label == "Подготовить":
            button.click().run()
            break
    assert not ui.exception
    assert {job["params"]["ollama_port"] for job in workspace.jobs()} == {11436, 11437}


def test_ui_language_is_remembered_across_sessions_and_workspaces(tmp_path, monkeypatch):
    script = str(Path(__file__).parents[1] / "src/brofessor/ui.py")
    monkeypatch.setattr("sys.argv", ["ui.py", "--workspace", str(tmp_path / "first")])
    ui = AppTest.from_file(script, default_timeout=10).run()
    ui.selectbox(key="ui_language").select("en").run()
    assert not ui.exception
    assert [tab.label for tab in ui.tabs] == ["Sources", "Create", "Jobs and results"]
    assert ui.selectbox(key="output_language").value == "ru"
    monkeypatch.setattr("sys.argv", ["ui.py", "--workspace", str(tmp_path / "second")])
    reopened = AppTest.from_file(script, default_timeout=10).run()
    assert not reopened.exception
    assert reopened.selectbox(key="ui_language").value == "en"
    assert reopened.tabs[0].label == "Sources"
    reopened.selectbox(key="ui_language").select("ru").run()
    assert not reopened.exception
    assert reopened.tabs[0].label == "Источники"


def test_language_switch_preserves_form_inputs_and_unsaved_draft(tmp_path, monkeypatch):
    workspace = Workspace(tmp_path / "workspace")
    source = tmp_path / "chapter.md"
    source.write_text("A bridge carries 1200 kilograms.")
    added = workspace.add_source(source)
    citation = workspace.units()[0]["id"]
    job = service.submit(workspace, "slides", start_worker=False)
    workspace.save_draft(
        job["id"],
        {
            "title": "Original title",
            "language": "ru",
            "slides": [
                {
                    "title": "Load",
                    "bullets": ["1200 kg"],
                    "notes": "Review source",
                    "citations": [citation],
                },
            ],
        },
    )
    workspace.update_job(job["id"], status="succeeded")
    monkeypatch.setattr("sys.argv", ["ui.py", "--workspace", str(workspace.path)])
    monkeypatch.setattr("brofessor.worker.ensure_worker", lambda workspace: None)
    ui = AppTest.from_file(
        str(Path(__file__).parents[1] / "src/brofessor/ui.py"), default_timeout=10
    ).run()
    buffer_key = f"editor:{workspace.path}:{job['id']}:text"
    data = workspace.draft(job["id"])["data"]
    data["title"] = "Unsaved user edit"
    unsaved = json.dumps(data)
    ui.text_area(key=buffer_key).set_value(unsaved).run()
    ui.selectbox(key="provider").select("ollama").run()
    ui.text_input(key="model").set_value("tiny").run()
    ui.number_input(key="ollama_port").set_value(11435).run()
    ui.multiselect(key="source_ids").set_value([added["id"]])
    ui.selectbox(key="kind").select("slides")
    ui.selectbox(key="output_language").select("en")
    ui.text_area(key="focus").set_value("Keep my focus")
    ui.number_input(key="slide_count").set_value(4)
    ui.selectbox(key="ui_language").select("en").run()
    assert not ui.exception
    assert ui.selectbox(key="project_selector").value == str(workspace.path)
    assert ui.selectbox(key="provider").value == "ollama"
    assert ui.text_input(key="model").value == "tiny"
    assert ui.number_input(key="ollama_port").value == 11435
    assert ui.multiselect(key="source_ids").value == [added["id"]]
    assert ui.selectbox(key="kind").value == "slides"
    assert ui.selectbox(key="output_language").value == "en"
    assert ui.text_area(key="focus").value == "Keep my focus"
    assert ui.number_input(key="slide_count").value == 4
    assert ui.text_area(key=buffer_key).value == unsaved
    assert workspace.draft(job["id"])["data"]["title"] == "Original title"
    assert any("Slide outline · Ready" in expander.label for expander in ui.expander)
    ui.button(key=f"save-{job['id']}").click().run()
    assert not ui.exception
    assert workspace.draft(job["id"])["data"]["title"] == "Unsaved user edit"


def test_language_save_error_is_visible_but_ui_still_switches(tmp_path, monkeypatch):
    def fail_save(language):
        raise OSError("Read-only settings directory")

    monkeypatch.setattr("brofessor.ui_language.save_language", fail_save)
    monkeypatch.setattr("sys.argv", ["ui.py", "--workspace", str(tmp_path / "workspace")])
    ui = AppTest.from_file(
        str(Path(__file__).parents[1] / "src/brofessor/ui.py"), default_timeout=10
    ).run()
    ui.selectbox(key="ui_language").select("en").run()
    assert not ui.exception
    assert ui.tabs[0].label == "Sources"
    assert any("Could not remember" in warning.value for warning in ui.warning)


def test_ui_creates_external_projects_and_keeps_their_sources_separate(tmp_path, monkeypatch):
    from brofessor import projects

    monkeypatch.setattr("sys.argv", ["ui.py"])
    script = str(Path(__file__).parents[1] / "src/brofessor/ui.py")
    ui = AppTest.from_file(script, default_timeout=10).run()
    assert not ui.exception
    assert ui.selectbox(key="project_selector").value is None
    ui.text_input(key="project_name").set_value("First book")
    ui.text_input(key="projects_directory").set_value(str(tmp_path / "external"))
    ui.button(key="create_project").click().run()
    assert not ui.exception
    first = projects.selected()
    source = tmp_path / "first.md"
    source.write_text("Only in the first project")
    Workspace(first["path"]).add_source(source)
    ui.run()
    assert any(expander.label == "first.md" for expander in ui.expander)
    ui.text_input(key="project_name").set_value("Second book")
    ui.button(key="create_project").click().run()
    assert not ui.exception
    assert projects.selected()["name"] == "Second book"
    assert not any(expander.label == "first.md" for expander in ui.expander)
    ui.selectbox(key="project_selector").select(first["path"]).run()
    assert not ui.exception
    assert any(expander.label == "first.md" for expander in ui.expander)
    reopened = AppTest.from_file(script, default_timeout=10).run()
    assert reopened.selectbox(key="project_selector").value == first["path"]


def test_switching_projects_keeps_unsaved_draft_buffer(tmp_path, monkeypatch):
    from brofessor import projects

    first = projects.create("First")
    workspace = Workspace(first["path"])
    source = tmp_path / "source.txt"
    source.write_text("One measured result")
    workspace.add_source(source)
    citation = workspace.units()[0]["id"]
    job = service.submit(workspace, "ask", focus="Evidence?", start_worker=False)
    workspace.save_draft(job["id"], {"answer": "Original answer", "citations": [citation]})
    workspace.update_job(job["id"], status="succeeded")
    second = projects.create("Second")
    projects.use("First")
    monkeypatch.setattr("sys.argv", ["ui.py"])
    ui = AppTest.from_file(
        str(Path(__file__).parents[1] / "src/brofessor/ui.py"), default_timeout=10
    ).run()
    buffer_key = f"editor:{workspace.path}:{job['id']}:text"
    unsaved = json.dumps({"answer": "Unsaved answer", "citations": [citation]})
    ui.text_area(key=buffer_key).set_value(unsaved).run()
    ui.selectbox(key="project_selector").select(second["path"]).run()
    assert not ui.exception
    assert not any(job["id"] in expander.label for expander in ui.expander)
    ui.selectbox(key="project_selector").select(first["path"]).run()
    assert not ui.exception
    assert ui.text_area(key=buffer_key).value == unsaved
    assert workspace.draft(job["id"])["data"]["answer"] == "Original answer"


def test_ui_download_uses_chosen_model_and_shared_job_queue(tmp_path, monkeypatch):
    from brofessor import speech_models

    workspace = Workspace(tmp_path / "workspace")
    monkeypatch.setattr("sys.argv", ["ui.py", "--workspace", str(workspace.path)])
    monkeypatch.setattr("brofessor.worker.ensure_worker", lambda workspace: None)
    entries = speech_models.list_models()
    monkeypatch.setattr(
        speech_models, "list_models", lambda: [{**item, "compatible": True} for item in entries]
    )
    ui = AppTest.from_file(
        str(Path(__file__).parents[1] / "src/brofessor/ui.py"), default_timeout=10
    ).run()
    ui.selectbox(key="tts_model").select("qwen3-1.7b").run()
    ui.button(key="download_tts_model").click().run()
    assert not ui.exception
    assert speech_models.selected() == "qwen3-1.7b"
    assert workspace.jobs()[0]["kind"] == "download_model"
    assert workspace.jobs()[0]["params"]["model"] == "qwen3-1.7b"
    assert ui.button(key="download_tts_model").disabled
