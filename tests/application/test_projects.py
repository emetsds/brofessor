import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from brofessor.application import projects, service
from brofessor.contracts.content import ContentLanguage
from brofessor.contracts.jobs import JobKind, JobStatus
from brofessor.infrastructure.storage import preferences
from brofessor.infrastructure.storage.workspace import Workspace
from brofessor.interfaces.cli.app import app


@pytest.fixture(autouse=True)
def isolated_user(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.delenv("BROFESSOR_WORKSPACE", raising=False)


def test_create_projects_outside_checkout_and_keep_them_isolated(tmp_path):
    first = projects.create("Первая книга")
    assert Path(first["path"]).is_relative_to(tmp_path / "data")
    source = tmp_path / "source.md"
    source.write_text("A bridge carries 1200 kg.")
    original = Workspace(first["path"])
    original.add_source(source)
    citation = original.units()[0]["id"]
    job = service.submit(original, JobKind.ASK, focus="Load?", start_worker=False)
    original.save_draft(job["id"], {"answer": "1200 kg", "citations": [citation]})
    second = projects.create("Second book", root=tmp_path / "external")
    assert not Workspace(second["path"]).sources()
    assert not Workspace(second["path"]).jobs()
    projects.use(first["name"])
    assert projects.selected()["path"] == first["path"]
    assert Workspace(projects.selected()["path"]).draft(job["id"])["data"]["answer"] == "1200 kg"
    assert projects.directory() == tmp_path / "external"
    preferences.save_settings("codex", language=ContentLanguage.EN, speech_model="qwen3-base")
    assert len(projects.list_projects()) == 2
    assert preferences.read()["ui_language"] == "en"


def test_open_existing_and_portable_project_preserves_originals(tmp_path, monkeypatch):
    existing = Workspace(tmp_path / "existing")
    source = tmp_path / "chapter.txt"
    source.write_text("Original source")
    added = existing.add_source(source)
    opened = projects.open_project(existing.path, name="My materials")
    assert projects.open_project(existing.path)["name"] == "My materials"
    assert len(projects.list_projects()) == 1
    moved = tmp_path / "another-computer" / "materials"
    shutil.copytree(existing.path, moved)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "new-config"))
    portable = projects.open_project(moved)
    assert Workspace(portable["path"]).sources()[0]["id"] == added["id"]
    assert Path(opened["path"], added["original"]).read_text() == "Original source"


def test_create_never_overwrites_existing_directory(tmp_path):
    target = tmp_path / "books" / "my-book"
    target.mkdir(parents=True)
    marker = target / "user.txt"
    marker.write_text("Keep me")
    with pytest.raises(FileExistsError):
        projects.create("My book", root=target.parent)
    assert marker.read_text() == "Keep me"
    assert not (target / "workspace.sqlite3").exists()


def test_missing_or_arbitrary_folder_cannot_be_opened_as_project(tmp_path):
    with pytest.raises(ValueError, match="missing"):
        projects.open_project(tmp_path / "missing")
    assert not (tmp_path / "missing").exists()
    assert not projects.list_projects()


def test_deleted_project_can_be_restored_with_its_name_and_saved_contents(tmp_path):
    from brofessor.application import tasks

    w = Workspace(tmp_path / "external-folder")
    project = projects.open_project(w.path, name="My edited project name")
    job = w.submit(JobKind.ASK, {"focus": "Saved question"})
    w.save_draft(job["id"], {"answer": "User's edited answer"})
    w.update_job(job["id"], status=JobStatus.SUCCEEDED)
    tasks.record_open(w, job["id"])
    other = projects.create("Other project")
    projects.use(project["name"])
    projects.delete(project["path"])
    assert projects.selected() is None
    assert [p["path"] for p in projects.list_projects()] == [other["path"]]
    assert tasks.recent_tasks() == []
    assert projects.deleted_projects() == [project]
    assert w.draft(job["id"])["data"]["answer"] == "User's edited answer"
    # An old tab cannot repopulate navigation merely by recording an open.
    tasks.record_open(w, job["id"])
    assert tasks.recent_tasks() == []
    reopened = projects.open_project(w.path)
    assert reopened == project and projects.deleted_projects() == []
    projects.delete(project["name"])
    assert projects.restore(project["name"]) == project


def test_delete_project_blocks_active_work_and_handles_missing_folder_without_recreating_it(
    tmp_path,
):
    project = projects.create("Busy")
    w = Workspace(project["path"])
    w.submit(JobKind.ASK, {})
    with pytest.raises(ValueError, match="Cancel active"):
        projects.delete(project["path"])
    assert projects.selected()["path"] == project["path"]
    moved = tmp_path / "moved-project"
    w.path.rename(moved)
    projects.delete(project["path"])
    with pytest.raises(ValueError, match="missing"):
        projects.restore(project["path"])
    assert not w.path.exists() and projects.deleted_projects() == [project]


def test_cli_uses_selected_project_and_explicit_workspace_overrides_it(tmp_path):
    runner = CliRunner()
    created = runner.invoke(
        app, ["project", "create", "Book", "--directory", str(tmp_path / "books")]
    )
    assert created.exit_code == 0, created.output
    source = tmp_path / "source.txt"
    source.write_text("Source text")
    result = runner.invoke(app, ["source", "add", str(source)])
    assert result.exit_code == 0, result.output
    assert len(Workspace(projects.selected()["path"]).sources()) == 1
    other = tmp_path / "explicit"
    result = runner.invoke(app, ["-w", str(other), "source", "list"])
    assert result.exit_code == 0, result.output
    assert Workspace(other).sources() == []
    assert projects.selected()["name"] == "Book"


def test_unavailable_selection_does_not_create_an_empty_replacement(tmp_path):
    project = projects.create("A book")
    moved = tmp_path / "moved"
    Path(project["path"]).rename(moved)
    result = CliRunner().invoke(app, ["source", "list"])
    assert result.exit_code != 0
    assert not Path(project["path"]).exists()


def test_cli_inherits_saved_text_connection_and_scopes_overrides_to_provider(tmp_path, monkeypatch):
    runner = CliRunner()
    configured = runner.invoke(
        app,
        [
            "config",
            "--provider",
            "ollama",
            "--model",
            "local",
            "--ollama-address",
            "192.0.2.2:11435",
        ],
    )
    assert configured.exit_code == 0, configured.output
    assert not projects.list_projects()
    workspace = Workspace(tmp_path / "project")
    path = tmp_path / "source.txt"
    path.write_text("Test bridge")
    workspace.add_source(path)
    monkeypatch.setattr("brofessor.application.worker.ensure_worker", lambda *_: None)
    ask = ["-w", str(workspace.path), "ask", "Which bridge?"]
    stored = json.loads(runner.invoke(app, ask).output)["params"]
    assert stored["model"] == "local" and stored["ollama_address"] == "192.0.2.2:11435"
    override = json.loads(runner.invoke(app, [*ask, "--provider", "codex"]).output)["params"]
    assert override["provider"] == "codex" and override["model"] is None
    assert "ollama_address" not in override
    assert (
        runner.invoke(
            app, [*ask, "--provider", "claude", "--ollama-address", "127.0.0.1:11434"]
        ).exit_code
        == 2
    )
    assert len(workspace.jobs()) == 2
    assert (
        runner.invoke(app, ["config", "--provider", "claude", "--model", "sonnet"]).exit_code == 0
    )
    assert "ollama_address" not in preferences.text_connection()
    assert runner.invoke(app, ["config", "--provider", "ollama"]).exit_code == 0
    assert preferences.text_connection() == json.loads(configured.output)
    assert workspace.job(workspace.jobs()[0]["id"])["params"] == override


@pytest.mark.parametrize(
    "stored",
    [
        '{"unfinished":',
        '{"text_provider":"missing","ui_language":"ru"}',
        '{"text_models":{"ollama":"local"}}',
        '{"text_provider":"ollama","text_models":["local"]}',
        '{"text_provider":"ollama","ollama_address":false}',
    ],
)
def test_corrupt_text_settings_block_generation_until_explicit_repair(tmp_path, stored):
    file = preferences.path()
    file.parent.mkdir(parents=True)
    file.write_text(stored)
    workspace = Workspace(tmp_path / "workspace")
    source = tmp_path / "chapter.txt"
    source.write_text("The sky is blue.")
    workspace.add_source(source)
    runner = CliRunner()
    result = runner.invoke(app, ["-w", str(workspace.path), "ask", "Color?"])
    assert result.exit_code == 2 and not workspace.jobs()
    assert file.read_text() == stored
    assert preferences.text_connection(for_edit=True)["provider"] in (None, "ollama")
    repaired = runner.invoke(
        app,
        [
            "config",
            "--provider",
            "ollama",
            "--model",
            "tiny",
            "--ollama-address",
            "192.0.2.8:11434",
        ],
    )
    assert repaired.exit_code == 0, repaired.output
    assert preferences.text_connection() == json.loads(repaired.output)
    if "unfinished" in stored:
        assert [p.read_text() for p in file.parent.glob("*.invalid.json")] == [stored]
    if "ui_language" in stored:
        assert preferences.read()["ui_language"] == "ru"
