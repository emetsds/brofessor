import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from brofessor import preferences, projects, service, ui_language
from brofessor.cli import app
from brofessor.workspace import Workspace


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
    job = service.submit(original, "ask", focus="Load?", start_worker=False)
    original.save_draft(job["id"], {"answer": "1200 kg", "citations": [citation]})
    second = projects.create("Second book", root=tmp_path / "external")
    assert not Workspace(second["path"]).sources()
    assert not Workspace(second["path"]).jobs()
    projects.use(first["name"])
    assert projects.selected()["path"] == first["path"]
    assert Workspace(projects.selected()["path"]).draft(job["id"])["data"]["answer"] == "1200 kg"
    assert projects.directory() == tmp_path / "external"
    ui_language.save_language("en")
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
