"""Task names and global search preserve original requests, results and history."""

import json

from typer.testing import CliRunner

from brofessor.application import projects, service, tasks
from brofessor.contracts.jobs import JobKind, JobStatus
from brofessor.infrastructure.storage import preferences
from brofessor.infrastructure.storage.workspace import Workspace
from brofessor.interfaces.cli.app import app


def source(w, tmp_path):
    path = tmp_path / "source.txt"
    path.write_text("A bridge supports eighty kilograms.")
    w.add_source(path)


def test_named_task_survives_result_edits_rename_and_reopening(tmp_path, monkeypatch):
    monkeypatch.setattr("brofessor.application.worker.ensure_worker", lambda *_: None)
    monkeypatch.setattr(
        "brofessor.infrastructure.text.runners.generate",
        lambda *_a, **_kw: (_ for _ in ()).throw(AssertionError("No model call")),
    )
    w = Workspace(tmp_path / "workspace")
    source(w, tmp_path)
    job = service.submit(
        w,
        JobKind.SLIDES,
        title="Load experiment",
        focus="Compare measured bridge capacity",
        start_worker=False,
    )
    assert tasks.title(w, job) == "Load experiment"
    w.save_draft(job["id"], {"title": "A generated material title"})
    w.update_job(job["id"], status=JobStatus.SUCCEEDED)
    w.save_draft(job["id"], {"title": "An edited material title"}, 1)
    result = CliRunner().invoke(
        app, ["-w", str(w.path), "task", "rename", job["id"], "Bridge review"]
    )
    assert result.exit_code == 0, result.output
    reopened = Workspace(w.path)
    assert tasks.title(reopened, reopened.job(job["id"])) == "Bridge review"
    assert reopened.draft(job["id"], 1)["data"]["title"] == "A generated material title"
    assert reopened.draft(job["id"])["data"]["title"] == "An edited material title"
    assert tasks.list_tasks(reopened, query="MEAS CAP")[0]["root_id"] == job["id"]
    assert tasks.list_tasks(reopened, query="bri rev")[0]["title"] == "Bridge review"
    auto = service.submit(
        w,
        JobKind.SLIDES,
        title="",
        focus="One two three four five six seven eight nine",
        start_worker=False,
    )
    assert tasks.title(w, auto) == "One two three four five six seven"
    legacy = service.submit(w, JobKind.SLIDES, focus="Legacy prompt", start_worker=False)
    w.save_draft(legacy["id"], {"title": "Existing saved result"})
    assert tasks.title(w, legacy) == "Existing saved result"


def test_global_prefix_search_groups_child_matches_and_finds_empty_projects(tmp_path, monkeypatch):
    monkeypatch.setattr("brofessor.application.worker.ensure_worker", lambda *_: None)
    empty = projects.create("Empty bridge archive", root=tmp_path / "projects")
    project = projects.create("Research", root=tmp_path / "projects")
    w = Workspace(project["path"])
    source(w, tmp_path)
    parent = service.submit(
        w, JobKind.ASK, title="Initial load", focus="What was measured?", start_worker=False
    )
    unit = w.units()[0]["id"]
    w.save_draft(parent["id"], {"answer": "Eighty kilograms.", "citations": [unit]})
    w.update_job(parent["id"], status=JobStatus.SUCCEEDED)
    child = service.follow_up(
        w, parent["id"], "Explain bridge assumptions", title="Bridge detail", start_worker=False
    )
    before = preferences.read()
    result = tasks.search_projects(projects.list_projects(), "BRI")
    assert {g["project"]["path"] for g in result} == {empty["path"], project["path"]}
    group = next(g for g in result if g["project"]["path"] == project["path"])
    assert len(group["tasks"]) == 1 and group["tasks"][0]["match_id"] == child["id"]
    assert (
        tasks.search_projects(projects.list_projects(), "bridge ass")[0]["tasks"][0]["match_id"]
        == child["id"]
    )
    assert tasks.search_projects(projects.list_projects(), "") == []
    assert tasks.search_projects(projects.list_projects(), "unfindable") == []
    cli = CliRunner().invoke(app, ["task", "search", "bri"])
    assert cli.exit_code == 0, cli.output
    assert json.loads(cli.output) == result
    assert preferences.read() == before
    w.cancel(child["id"])
    tasks.delete(w, parent["id"])
    assert tasks.search_projects(projects.list_projects(), "bridge") == [
        {
            "project": next(p for p in projects.list_projects() if p["path"] == empty["path"]),
            "tasks": [],
        }
    ]
