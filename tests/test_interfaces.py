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


@pytest.mark.parametrize("status", ["supported", "insufficient_evidence", "conflicting_evidence"])
def test_cli_and_ui_show_exact_quotes_status_and_original_locations(tmp_path, monkeypatch, status):
    from brofessor import pipeline

    w = Workspace(tmp_path / "workspace")
    path = tmp_path / "report.txt"
    path.write_text("Report A: capacity 80 kg. Report B: capacity 120 kg.")
    w.add_source(path)
    citation = w.units()[0]["id"]
    value = {
        "answer": "The source contains both reported capacities.",
        "evidence_status": status,
        "citations": [citation],
        "quotes": [
            {"citation": citation, "text": "Report A: capacity 80 kg."},
            {"citation": citation, "text": "Report B: capacity 120 kg."},
        ],
    }
    monkeypatch.setattr("brofessor.executors.generate", lambda *a, **kw: value)
    job = service.submit(w, "ask", focus="Capacity?", start_worker=False)
    pipeline.execute(w, job)
    w.update_job(job["id"], status="succeeded")
    result = CliRunner().invoke(app, ["-w", str(w.path), "draft", "show", job["id"]])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["data"]["quotes"] == value["quotes"]
    assert data["evidence"] == service.answer_evidence(w, job["id"])
    assert data["evidence"][0]["source"] == "report.txt"
    monkeypatch.setattr("sys.argv", ["ui.py", "--workspace", str(w.path)])
    ui = AppTest.from_file(
        str(Path(__file__).parents[1] / "src/brofessor/ui.py"), default_timeout=30
    ).run()
    assert not ui.exception
    assert any(text.value == value["quotes"][0]["text"] for text in ui.text)
    assert any("report.txt · lines 1-1" in c.value for c in ui.caption)
    if status == "conflicting_evidence":
        assert any("противоречие" in warning.value for warning in ui.warning)
    if status == "insufficient_evidence":
        assert any("недостаточно" in info.value for info in ui.info)
    ui.selectbox(key="ui_language").select("en").run()
    assert not ui.exception
    assert any(text.value == value["quotes"][1]["text"] for text in ui.text)


def test_cli_and_ui_search_selected_sources(tmp_path, monkeypatch):
    w = Workspace(tmp_path / "workspace")
    for name in ("a", "b"):
        path = tmp_path / f"{name}.txt"
        path.write_text(f"The {name} beacon is blue.")
        w.add_source(path)
    source = next(s for s in w.sources() if s["name"] == "b.txt")
    result = CliRunner().invoke(
        app, ["-w", str(w.path), "search", "blue", "--source", source["id"], "--limit", "1"]
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == service.search(
        w, "blue", source_ids=[source["id"]], limit=1
    )
    monkeypatch.setattr("sys.argv", ["ui.py", "--workspace", str(w.path)])
    ui = AppTest.from_file(
        str(Path(__file__).parents[1] / "src/brofessor/ui.py"), default_timeout=30
    ).run()
    ui.multiselect(key="search_source_ids").set_value([source["id"]])
    ui.text_input(key="source_query").set_value("blue").run()
    assert not ui.exception
    assert any("b.txt · lines 1-1" in item.value for item in ui.markdown)
    assert not any("a.txt · lines 1-1" in item.value for item in ui.markdown)
    ui.text_input(key="source_query").set_value("zirconium").run()
    assert any("не найдены" in item.value for item in ui.info)


def test_ui_shows_search_selection_without_claiming_unread_fragments_were_read(
    tmp_path, monkeypatch
):
    from brofessor import pipeline, questions

    w = Workspace(tmp_path / "workspace")
    for name, text in [("beacon", "A beacon is blue."), ("granite", "Unrelated granite." * 50)]:
        path = tmp_path / f"{name}.txt"
        path.write_text(text)
        w.add_source(path)
    citation = next(u["id"] for u in w.units() if "blue" in u["text"])
    monkeypatch.setattr(questions, "EVIDENCE_BUDGET", 500)
    monkeypatch.setattr(
        "brofessor.executors.generate",
        lambda prompt, schema, *a, **k: (
            {"queries": ["beacon blue"]}
            if schema["title"] == "SearchQueries"
            else {
                "answer": "Blue",
                "citations": [citation],
                "quotes": [{"citation": citation, "text": "A beacon is blue."}],
            }
        ),
    )
    job = service.submit(w, "ask", focus="beacon colour", start_worker=False)
    pipeline.execute(w, job)
    w.update_job(job["id"], status="succeeded")
    monkeypatch.setattr("sys.argv", ["ui.py", "--workspace", str(w.path)])
    ui = AppTest.from_file(
        str(Path(__file__).parents[1] / "src/brofessor/ui.py"), default_timeout=30
    ).run()
    assert not ui.exception
    assert set(ui.dataframe[0].value["Статус чтения"]) == {"Прочитан", "Не выбран поиском"}
    assert any("не прочитаны" in info.value for info in ui.info)
    ui.selectbox(key="ui_language").select("en").run()
    assert not ui.exception
    assert set(ui.dataframe[0].value["Reading status"]) == {"Read", "Not selected by search"}


def test_cli_import_is_visible_in_ui(tmp_path, monkeypatch):
    path = tmp_path / "workspace"
    source = tmp_path / "chapter.md"
    source.write_text("A reliable bridge carries 1200 kilograms.")
    runner = CliRunner()
    result = runner.invoke(app, ["-w", str(path), "source", "add", str(source)])
    assert result.exit_code == 0, result.output
    monkeypatch.setattr("sys.argv", ["ui.py", "--workspace", str(path)])
    ui = AppTest.from_file(
        str(Path(__file__).parents[1] / "src/brofessor/ui.py"), default_timeout=30
    ).run()
    assert not ui.exception
    assert any(expander.label == "chapter.md" for expander in ui.expander)
    assert Workspace(path).sources()[0]["name"] == "chapter.md"


def test_cli_and_both_ui_languages_show_shared_coverage(tmp_path, monkeypatch):
    from brofessor import pipeline

    workspace = Workspace(tmp_path / "workspace")
    source = tmp_path / "chapter.md"
    source.write_text("A reliable bridge carries 1200 kilograms.")
    workspace.add_source(source)
    partial = tmp_path / "partial.txt"
    partial.write_text("\n" * 100 + "A second fact.")
    workspace.add_source(partial)
    citation = next(unit["id"] for unit in workspace.units() if unit["status"] == "ready")
    monkeypatch.setattr(
        "brofessor.executors.generate",
        lambda *a, **k: {
            "answer": "1200 kilograms",
            "citations": [citation],
            "quotes": [{"citation": citation, "text": "1200 kilograms"}],
        },
    )
    job = service.submit(workspace, "ask", focus="Load?", start_worker=False)
    pipeline.execute(workspace, job)
    workspace.update_job(job["id"], status="succeeded")
    result = CliRunner().invoke(app, ["-w", str(workspace.path), "job", "coverage", job["id"]])
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report == service.coverage(workspace, job["id"])
    assert report["count"] == 2
    assert report["cited_count"] == len(report["excluded"]) == 1
    monkeypatch.setattr("sys.argv", ["ui.py", "--workspace", str(workspace.path)])
    ui = AppTest.from_file(
        str(Path(__file__).parents[1] / "src/brofessor/ui.py"), default_timeout=30
    ).run()
    assert not ui.exception
    assert any("Прочитано 2 из 2" in caption.value for caption in ui.caption)
    assert len(ui.dataframe) == 1
    assert set(ui.dataframe[0].value["Статус чтения"]) == {"Прочитан", "Исключён"}
    ui.selectbox(key="ui_language").select("en").run()
    assert not ui.exception
    assert any("Read 2 of 2" in caption.value for caption in ui.caption)
    assert set(ui.dataframe[0].value["Reading status"]) == {"Read", "Excluded"}


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
        str(Path(__file__).parents[1] / "src/brofessor/ui.py"), default_timeout=30
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
        str(Path(__file__).parents[1] / "src/brofessor/ui.py"), default_timeout=30
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
def test_cli_saves_custom_ollama_address_with_job(tmp_path, monkeypatch, command):
    workspace = Workspace(tmp_path / "workspace")
    source = tmp_path / "chapter.md"
    source.write_text("A bridge carries 1200 kilograms.")
    workspace.add_source(source)
    monkeypatch.setattr("brofessor.worker.ensure_worker", lambda workspace: None)
    args = ["-w", str(workspace.path), command]
    if command == "ask":
        args.append("What was measured?")
    result = CliRunner().invoke(
        app,
        [
            *args,
            "--provider",
            "ollama",
            "--model",
            "tiny",
            "--ollama-address",
            "192.168.50.10:11435",
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["params"]["ollama_address"] == "192.168.50.10:11435"
    assert Workspace(workspace.path).jobs()[0]["params"]["ollama_address"] == "192.168.50.10:11435"


def test_cli_doctor_uses_selected_ollama_address(tmp_path, monkeypatch):
    calls = []

    def diagnose(provider, model, *, ollama_address):
        calls.append((provider, model, ollama_address))
        return {"available": True}

    monkeypatch.setattr("brofessor.executors.doctor", diagnose)
    result = CliRunner().invoke(
        app,
        [
            "-w",
            str(tmp_path),
            "doctor",
            "--provider",
            "ollama",
            "--ollama-address",
            "192.168.50.10:11435",
        ],
    )
    assert result.exit_code == 0, result.output
    assert calls == [("ollama", None, "192.168.50.10:11435")]


def test_ui_launch_passes_both_ports_to_streamlit(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr("brofessor.cli.subprocess.call", lambda args: calls.append(args) or 0)
    result = CliRunner().invoke(
        app,
        ["-w", str(tmp_path), "ui", "--port", "8502", "--ollama-address", "192.168.50.10:11435"],
    )
    assert result.exit_code == 0, result.output
    assert len(calls) == 1
    assert "--server.address=127.0.0.1" in calls[0]
    assert "--server.port=8502" in calls[0]
    app_args = calls[0][calls[0].index("--") + 1 :]
    assert app_args == ["--workspace", str(tmp_path), "--ollama-address", "192.168.50.10:11435"]


@pytest.mark.parametrize("port", ["0", "65536"])
@pytest.mark.parametrize(
    "args", [["ui", "--port"], ["ui", "--ollama-address"], ["doctor", "--ollama-address"]]
)
def test_invalid_cli_ports_fail_before_launch(tmp_path, monkeypatch, args, port):
    monkeypatch.setattr("brofessor.cli.subprocess.call", lambda *a: pytest.fail("Must not launch"))
    monkeypatch.setattr(
        "brofessor.executors.doctor", lambda *a, **k: pytest.fail("Must not connect")
    )
    result = CliRunner().invoke(app, ["-w", str(tmp_path), *args, port])
    assert result.exit_code == 2, result.output
    assert ("range" if "--port" in args else "IP:port") in result.output


def test_ui_uses_selected_port_for_check_and_jobs(tmp_path, monkeypatch):
    workspace = Workspace(tmp_path / "workspace")
    source = tmp_path / "chapter.md"
    source.write_text("A bridge carries 1200 kilograms.")
    workspace.add_source(source)
    monkeypatch.setattr("brofessor.worker.ensure_worker", lambda workspace: None)
    calls = []

    def diagnose(provider, model, *, ollama_address):
        calls.append((provider, model, ollama_address))
        return {"available": True}

    monkeypatch.setattr("brofessor.executors.doctor", diagnose)
    monkeypatch.setattr(
        "sys.argv",
        ["ui.py", "--workspace", str(workspace.path), "--ollama-address", "192.168.50.10:11435"],
    )
    ui = AppTest.from_file(
        str(Path(__file__).parents[1] / "src/brofessor/ui.py"), default_timeout=30
    ).run()
    next(field for field in ui.selectbox if field.label == "Исполнитель").select("ollama").run()
    next(field for field in ui.text_input if field.label.startswith("Модель")).set_value(
        "tiny"
    ).run()
    assert not ui.exception
    assert ui.text_input(key="ollama_address").value == "192.168.50.10:11435"
    ui.text_input(key="ollama_address").set_value("192.168.50.11:11436").run()
    next(field for field in ui.selectbox if field.label == "Исполнитель").select("codex").run()
    next(field for field in ui.selectbox if field.label == "Исполнитель").select("ollama").run()
    assert ui.text_input(key="ollama_address").value == "192.168.50.11:11436"
    for button in ui.button:
        if button.label == "Проверить подключение":
            button.click().run()
            break
    assert calls == [("ollama", "tiny", "192.168.50.11:11436")]
    for button in ui.button:
        if button.label == "Подготовить":
            button.click().run()
            break
    assert not ui.exception
    assert workspace.jobs()[0]["params"]["ollama_address"] == "192.168.50.11:11436"
    ui.text_input(key="ollama_address").set_value("192.168.50.12:11437").run()
    for button in ui.button:
        if button.label == "Подготовить":
            button.click().run()
            break
    assert not ui.exception
    assert {job["params"]["ollama_address"] for job in workspace.jobs()} == {
        "192.168.50.11:11436",
        "192.168.50.12:11437",
    }


def test_create_form_uses_only_relevant_options_and_keeps_question_identity(tmp_path, monkeypatch):
    w = Workspace(tmp_path / "workspace")
    source = tmp_path / "source.txt"
    source.write_text("A load test was performed.")
    w.add_source(source)
    monkeypatch.setattr("sys.argv", ["ui.py", "--workspace", str(w.path)])
    monkeypatch.setattr("brofessor.worker.ensure_worker", lambda *_: None)
    ui = AppTest.from_file(
        str(Path(__file__).parents[1] / "src/brofessor/ui.py"), default_timeout=30
    ).run()
    ui.selectbox(key="kind").select("ask").run()
    ui.text_area(key="focus").set_value("What was tested?")
    ui.button(key="prepare").click().run()
    assert not ui.exception and len(w.jobs()) == 1
    original = w.jobs()[0]["id"]
    assert not any(e.key == "minutes" for e in ui.select_slider)
    assert not any(e.key == "slide_count" for e in ui.number_input)
    ui.selectbox(key="kind").select("podcast").run()
    ui.select_slider(key="minutes").set_value(60).run()
    assert not any(e.key == "slide_count" for e in ui.number_input)
    ui.selectbox(key="kind").select("slides").run()
    ui.number_input(key="slide_count").set_value(4).run()
    assert not any(e.key == "minutes" for e in ui.select_slider)
    ui.selectbox(key="kind").select("ask").run()
    ui.button(key="prepare").click().run()
    assert not ui.exception and [j["id"] for j in w.jobs()] == [original]
    ui.selectbox(key="kind").select("podcast").run()
    assert ui.select_slider(key="minutes").value == 60
    ui.selectbox(key="kind").select("slides").run()
    assert ui.number_input(key="slide_count").value == 4


def test_ui_language_is_remembered_across_sessions_and_workspaces(tmp_path, monkeypatch):
    script = str(Path(__file__).parents[1] / "src/brofessor/ui.py")
    monkeypatch.setattr("sys.argv", ["ui.py", "--workspace", str(tmp_path / "first")])
    ui = AppTest.from_file(script, default_timeout=30).run()
    ui.selectbox(key="ui_language").select("en").run()
    assert not ui.exception
    assert [tab.label for tab in ui.tabs] == ["Sources", "Create", "Jobs and results", "Notes"]
    assert ui.selectbox(key="output_language").value == "ru"
    monkeypatch.setattr("sys.argv", ["ui.py", "--workspace", str(tmp_path / "second")])
    reopened = AppTest.from_file(script, default_timeout=30).run()
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
        str(Path(__file__).parents[1] / "src/brofessor/ui.py"), default_timeout=30
    ).run()
    buffer_key = f"editor:{workspace.path}:{job['id']}:text"
    data = workspace.draft(job["id"])["data"]
    data["title"] = "Unsaved user edit"
    unsaved = json.dumps(data)
    ui.text_area(key=buffer_key).set_value(unsaved).run()
    ui.selectbox(key="provider").select("ollama").run()
    ui.text_input(key="model").set_value("tiny").run()
    ui.text_input(key="ollama_address").set_value("192.168.50.10:11435").run()
    ui.multiselect(key="source_ids").set_value([added["id"]])
    ui.selectbox(key="kind").select("slides").run()
    ui.selectbox(key="output_language").select("en")
    ui.text_area(key="focus").set_value("Keep my focus")
    ui.number_input(key="slide_count").set_value(4)
    ui.selectbox(key="ui_language").select("en").run()
    assert not ui.exception
    assert ui.selectbox(key="project_selector").value == str(workspace.path)
    assert ui.selectbox(key="provider").value == "ollama"
    assert ui.text_input(key="model").value == "tiny"
    assert ui.text_input(key="ollama_address").value == "192.168.50.10:11435"
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
        str(Path(__file__).parents[1] / "src/brofessor/ui.py"), default_timeout=30
    ).run()
    ui.selectbox(key="ui_language").select("en").run()
    assert not ui.exception
    assert ui.tabs[0].label == "Sources"
    assert any("Could not remember" in warning.value for warning in ui.warning)


def test_ui_creates_external_projects_and_keeps_their_sources_separate(tmp_path, monkeypatch):
    from brofessor import projects

    monkeypatch.setattr("sys.argv", ["ui.py"])
    script = str(Path(__file__).parents[1] / "src/brofessor/ui.py")
    ui = AppTest.from_file(script, default_timeout=30).run()
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
    reopened = AppTest.from_file(script, default_timeout=30).run()
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
        str(Path(__file__).parents[1] / "src/brofessor/ui.py"), default_timeout=30
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


@pytest.mark.parametrize(
    "choice", ["qwen3-1.7b", "silero-cis-base", "f5-tts", "f5-tts-russian", "espeech-rl-v2"]
)
def test_ui_download_uses_chosen_model_and_shared_job_queue(tmp_path, monkeypatch, choice):
    from brofessor import speech_models

    workspace = Workspace(tmp_path / "workspace")
    monkeypatch.setattr("sys.argv", ["ui.py", "--workspace", str(workspace.path)])
    monkeypatch.setattr("brofessor.worker.ensure_worker", lambda workspace: None)
    entries = speech_models.list_models()
    monkeypatch.setattr(
        speech_models, "list_models", lambda: [{**item, "compatible": True} for item in entries]
    )
    ui = AppTest.from_file(
        str(Path(__file__).parents[1] / "src/brofessor/ui.py"), default_timeout=30
    ).run()
    ui.selectbox(key="tts_model").select(choice).run()
    ui.button(key="download_tts_model").click().run()
    assert not ui.exception
    assert speech_models.selected() == choice
    assert workspace.jobs()[0]["kind"] == "download_model"
    assert workspace.jobs()[0]["params"]["model"] == choice
    assert (
        workspace.jobs()[0]["params"]["model_spec"]["revision"]
        == speech_models.get(choice)["revision"]
    )
    assert ui.button(key="download_tts_model").disabled


def test_audio_result_shows_recorded_model_even_if_default_changes(tmp_path, monkeypatch):
    from brofessor import speech_models

    workspace = Workspace(tmp_path / "workspace")
    source = tmp_path / "source.txt"
    source.write_text("A measured result")
    workspace.add_source(source)
    citation = workspace.units()[0]["id"]
    original = service.submit(workspace, "podcast", start_worker=False)
    workspace.save_draft(
        original["id"],
        {
            "title": "Voice check",
            "language": "ru",
            "turns": [
                {"speaker": "host", "text": "Question?", "citations": [citation]},
                {"speaker": "guest", "text": "Answer.", "citations": [citation]},
            ],
        },
    )
    rendered = service.render(workspace, original["id"], model="qwen3-1.7b", start_worker=False)
    workspace.update_job(rendered["id"], status="succeeded")
    speech_models.use("qwen3-0.6b")
    monkeypatch.setattr("sys.argv", ["ui.py", "--workspace", str(workspace.path)])
    workspace.update_job(original["id"], status="succeeded")
    ui = AppTest.from_file(
        str(Path(__file__).parents[1] / "src/brofessor/ui.py"), default_timeout=30
    ).run()
    assert not ui.exception
    assert ui.selectbox(key="tts_model").value == "qwen3-0.6b"
    assert any("Модель озвучки: Qwen3-TTS 1.7B" in caption.value for caption in ui.caption)


def test_duration_feedback_is_available_in_cli_and_both_ui_languages(tmp_path, monkeypatch):
    import wave
    from brofessor.podcasts import duration_feedback

    workspace = Workspace(tmp_path / "workspace")
    source = tmp_path / "source.txt"
    source.write_text("A measured result")
    workspace.add_source(source)
    citation = workspace.units()[0]["id"]
    original = service.submit(workspace, "podcast", minutes=60, start_worker=False)
    data = {
        "title": "Duration check",
        "language": "ru",
        "turns": [
            {"speaker": "host", "text": "Вопрос", "citations": [citation]},
            {"speaker": "guest", "text": "Ответ", "citations": [citation]},
        ],
    }
    workspace.save_draft(original["id"], data)
    rendered = service.render(workspace, original["id"], model="qwen3-0.6b", start_worker=False)
    path = workspace.path / "jobs" / rendered["id"] / "test.wav"
    path.parent.mkdir(parents=True)
    with wave.open(str(path), "wb") as stream:
        stream.setparams((1, 2, 24000, 0, "NONE", "none"))
        stream.writeframes(b"\x01\x00" * 240)
    # Synthetic UI metadata: the short fixture is not a real 61-minute render.
    workspace.add_artifact(
        rendered["id"],
        path,
        "audio",
        {
            "duration_seconds": 3700,
            **duration_feedback(data, 60, 3700),
        },
    )
    for job in (original, rendered):
        workspace.update_job(job["id"], status="succeeded")
    cli = CliRunner().invoke(app, ["-w", str(workspace.path), "job", "show", rendered["id"]])
    assert cli.exit_code == 0
    metadata = json.loads(cli.output)["artifacts"][0]["metadata"]
    assert metadata["duration_matches"] is False
    assert metadata["script_words"] == 2
    monkeypatch.setattr("sys.argv", ["ui.py", "--workspace", str(workspace.path)])
    ui = AppTest.from_file(
        str(Path(__file__).parents[1] / "src/brofessor/ui.py"), default_timeout=30
    ).run()
    assert not ui.exception
    assert any("61:40" in caption.value for caption in ui.caption)
    assert any("Слов в сценарии: 2" in caption.value for caption in ui.caption)
    assert any("от 20 до 60 минут" in warning.value for warning in ui.warning)
    ui.selectbox(key="ui_language").select("en").run()
    assert not ui.exception
    assert any("Audio duration 61:40" in caption.value for caption in ui.caption)
    assert any("Script: 2 words" in caption.value for caption in ui.caption)


def test_series_cli_ui_share_plan_episode_and_unsaved_edit_protection(tmp_path, monkeypatch):
    from brofessor import worker

    workspace = Workspace(tmp_path / "workspace")
    source = tmp_path / "chapter.md"
    source.write_text("A bridge carries 1200 kilograms. Flood resistance is unknown.")
    workspace.add_source(source)
    citation = workspace.units()[0]["id"]
    monkeypatch.setattr(worker, "ensure_worker", lambda *_: None)
    runner = CliRunner()
    prefix = ["-w", str(workspace.path)]
    result = runner.invoke(
        app, [*prefix, "series", "plan", "--episodes", "2", "--focus", "Testing"]
    )
    assert result.exit_code == 0, result.output
    parent = json.loads(result.output)
    monkeypatch.setattr("sys.argv", ["ui.py", "--workspace", str(workspace.path)])
    ui = AppTest.from_file(
        str(Path(__file__).parents[1] / "src/brofessor/ui.py"), default_timeout=30
    ).run()
    ui.selectbox(key="kind").select("podcast_series").run()
    ui.number_input(key="episode_count").set_value(2).run()
    ui.text_area(key="focus").set_value("Testing").run()
    ui.button(key="prepare").click().run()
    assert not ui.exception
    assert workspace.jobs()[0]["params"] == parent["params"]
    assert workspace.jobs()[0]["kind"] == "podcast_series"
    value = {
        "title": "Испытания моста",
        "language": "ru",
        "terms": [{"term": "Нагрузка", "meaning": "Измеренный вес", "citations": [citation]}],
        "topics": [
            {"id": "t1", "title": "Испытания", "brief": "Что известно", "citations": [citation]},
            {
                "id": "t2",
                "title": "Ограничения",
                "brief": "Что неизвестно",
                "citations": [citation],
            },
        ],
        "episodes": [
            {"title": "Факты", "topic_ids": ["t1"]},
            {"title": "Вопросы", "topic_ids": ["t2"]},
        ],
    }
    monkeypatch.setattr("brofessor.executors.generate", lambda *a, **kw: value)
    worker.run(workspace, once=True)
    ui.run()
    assert any(expander.label == "Общая терминология" for expander in ui.expander)
    assert any(
        "Цель для каждого: 20 мин · Исполнитель текста: codex" in c.value for c in ui.caption
    )
    ui.button(key=f"prepare-episode-{parent['id']}").click().run()
    assert not ui.exception
    result = runner.invoke(
        app, [*prefix, "series", "episode", parent["id"], "1", "--revision", "1"]
    )
    assert result.exit_code == 0, result.output
    episode = json.loads(result.output)
    assert len([j for j in workspace.jobs() if j["kind"] == "podcast"]) == 1
    assert episode["params"]["series"] == {"job_id": parent["id"], "revision": 1, "episode": 1}
    buffer = f"editor:{workspace.path}:{parent['id']}:text"
    changed = json.loads(ui.text_area(key=buffer).value)
    changed["terms"][0]["term"] = "Допустимая нагрузка"
    edited = json.dumps(changed, ensure_ascii=False)
    ui.text_area(key=buffer).set_value(edited).run()
    assert ui.button(key=f"prepare-episode-{parent['id']}").disabled
    ui.selectbox(key="ui_language").select("en").run()
    assert not ui.exception and ui.text_area(key=buffer).value == edited
    assert any("Save or load the latest plan" in c.value for c in ui.caption)
    assert any("Target per episode: 20 min · Text provider: codex" in c.value for c in ui.caption)
    ui.button(key=f"save-{parent['id']}").click().run()
    assert not ui.exception
    ui.button(key=f"prepare-episode-{parent['id']}").click().run()
    assert not ui.exception
    new = next(
        j
        for j in workspace.jobs()
        if j["kind"] == "podcast" and j["params"]["series"]["revision"] == 2
    )
    assert new["id"] != episode["id"]
    assert workspace.draft(parent["id"], 1)["data"] == value


def test_ui_edit_and_cli_render_share_table_and_sequence_contract(tmp_path, monkeypatch):
    from pptx import Presentation
    from brofessor import worker

    w = Workspace(tmp_path / "workspace")
    source = tmp_path / "source.md"
    source.write_text("The original text supports a comparison and a sequence.")
    w.add_source(source)
    citation = w.units()[0]["id"]
    job = service.submit(w, "slides", slide_count=2, start_worker=False)
    value = {
        "title": "Материал",
        "language": "ru",
        "slides": [
            {
                "title": "Сравнение",
                "bullets": [],
                "notes": "Сохранить пояснение",
                "citations": [citation],
                "table": {"headers": ["Тип", "Смысл"], "rows": [["Факт", "Проверяемый вывод"]]},
            },
            {
                "title": "Последовательность",
                "bullets": [],
                "notes": "Порядок действий",
                "citations": [citation],
                "steps": ["Источник", "Проверка", "Результат"],
            },
        ],
    }
    monkeypatch.setattr("brofessor.executors.generate", lambda *a, **kw: value)
    monkeypatch.setattr(worker, "ensure_worker", lambda *_: None)
    worker.run(w, once=True)
    monkeypatch.setattr("sys.argv", ["ui.py", "--workspace", str(w.path)])
    ui = AppTest.from_file(
        str(Path(__file__).parents[1] / "src/brofessor/ui.py"), default_timeout=30
    ).run()
    key = f"editor:{w.path}:{job['id']}:text"
    edited = json.loads(ui.text_area(key=key).value)
    edited["slides"][0]["table"]["rows"][0][1] = "Уточнённый вывод"
    edited["slides"][1]["steps"][1] = "Сверка с оригиналом"
    ui.text_area(key=key).set_value(json.dumps(edited, ensure_ascii=False)).run()
    ui.selectbox(key="ui_language").select("en").run()
    assert not ui.exception
    ui.button(key=f"save-{job['id']}").click().run()
    assert not ui.exception
    result = CliRunner().invoke(app, ["-w", str(w.path), "draft", "render", job["id"]])
    assert result.exit_code == 0, result.output
    rendered = json.loads(result.output)
    assert rendered["params"]["revision"] == 2
    worker.run(w, once=True)
    artifact = w.artifacts(rendered["id"])[0]
    deck = Presentation(w.path / artifact["path"])
    assert (
        next(s.table for s in deck.slides[0].shapes if s.has_table).cell(1, 1).text
        == "Уточнённый вывод"
    )
    assert any(s.has_text_frame and s.text == "Сверка с оригиналом" for s in deck.slides[1].shapes)
    assert "source.md" in deck.slides[1].notes_slide.notes_text_frame.text
