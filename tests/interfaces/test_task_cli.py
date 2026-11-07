"""CLI uses the same task snapshots and maintenance workspace as the UI."""

import json

from typer.testing import CliRunner

from brofessor.application import maintenance, projects, service, tasks
from brofessor.contracts.jobs import JobKind, JobStatus
from brofessor.infrastructure.storage import preferences
from brofessor.infrastructure.storage.workspace import Workspace
from brofessor.interfaces.cli.app import app


def invoke(*args):
    result = CliRunner().invoke(app, list(args))
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def test_cli_settings_before_project_and_task_overrides_preserve_old_runs(tmp_path, monkeypatch):
    monkeypatch.setattr("brofessor.application.worker.ensure_worker", lambda *_: None)
    preferences.update(text_provider=None)
    saved = invoke("config", "--language", "en")
    assert saved["provider"] is None and saved["language"] == "en"
    assert projects.list_projects() == []
    invoke("config", "--provider", "codex", "--model", "initial")
    w = Workspace(tmp_path / "workspace")
    source = tmp_path / "source.txt"
    source.write_text("One bridge carries eighty kilograms.")
    w.add_source(source)
    job = service.submit(w, JobKind.ASK, focus="Capacity?", model="initial", start_worker=False)
    w.save_draft(job["id"], {"answer": "Eighty.", "citations": [w.units()[0]["id"]]})
    w.update_job(job["id"], status=JobStatus.SUCCEEDED)
    prefix = ("-w", str(w.path), "task")
    shown = invoke(*prefix, "show", job["id"])
    version = shown["models"]["revision"]
    changed = invoke(
        *prefix,
        "models",
        job["id"],
        "--provider",
        "claude",
        "--model",
        "other",
        "--expected-revision",
        str(version),
    )
    assert changed["data"]["model"] == "other"
    fresh = invoke(*prefix, "regenerate", job["id"], "--request-key", "again")
    assert fresh["params"]["provider"] == "claude" and fresh["params"]["model"] == "other"
    invoke(*prefix, "models", job["id"], "--use-defaults")
    assert invoke(*prefix, "regenerate", job["id"], "--request-key", "again")["id"] == fresh["id"]
    assert w.job(job["id"])["params"]["model"] == "initial"
    assert len(invoke(*prefix, "list")) == 1
    assert invoke("task", "recent")[0]["root_id"] == job["id"]
    stale = CliRunner().invoke(
        app, [*prefix, "models", job["id"], "--model", "stale", "--expected-revision", str(version)]
    )
    assert stale.exit_code == 1 and "changed" in stale.output


def test_cli_downloads_without_project_use_hidden_durable_queue(tmp_path, monkeypatch):
    started = []
    monkeypatch.setattr(
        "brofessor.application.worker.ensure_worker", lambda w: started.append(w.path)
    )
    folder = preferences.data_directory() / "maintenance"
    assert not folder.exists()
    assert invoke("models", "jobs") == []
    assert not folder.exists()
    job = invoke("models", "download", "qwen3-base")
    target = maintenance.workspace()
    assert target.path in started and target.job(job["id"])["status"] == "queued"
    assert projects.list_projects() == [] and tasks.recent_tasks() == []
    assert invoke("models", "jobs")[0]["workspace_path"] == str(target.path)
    assert invoke("models", "cancel", job["id"])["status"] == "cancelled"
    assert invoke("models", "resume", job["id"])["status"] == "queued"
    assert preferences.read().get("recent_tasks", []) == []


def test_cli_missing_task_workspace_is_not_created(tmp_path):
    absent = tmp_path / "missing"
    result = CliRunner().invoke(app, ["-w", str(absent), "task", "list"])
    assert result.exit_code == 1 and "unavailable" in result.output
    assert not absent.exists()


def test_cli_task_list_uses_the_same_word_prefixes_and_kind_filter(tmp_path):
    w = Workspace(tmp_path / "project")
    target = w.submit(JobKind.PODCAST, {"focus": "Примеры голосов"})
    w.submit(JobKind.ASK, {"focus": "Сравнение голосов"})
    rows = invoke("-w", str(w.path), "task", "list", "--query", "ГОЛ", "--kind", "podcast")
    assert [row["root_id"] for row in rows] == [target["id"]]
    assert invoke("-w", str(w.path), "task", "list", "--query", "олос") == []


def test_cli_deletion_requires_confirmation_and_supports_project_and_task_restore(tmp_path):
    project = projects.create("Book")
    w = Workspace(project["path"])
    job = w.submit(JobKind.ASK, {"focus": "Saved question"})
    w.save_draft(job["id"], {"answer": "Kept answer"})
    w.update_job(job["id"], status=JobStatus.SUCCEEDED)
    declined = CliRunner().invoke(app, ["task", "delete", job["id"]], input="n\n")
    assert declined.exit_code != 0 and tasks.list_tasks(w)
    invoke("task", "delete", job["id"], "--yes")
    assert invoke("task", "list") == []
    assert invoke("task", "list", "--deleted")[0]["root_id"] == job["id"]
    invoke("task", "restore", job["id"])
    assert invoke("task", "list")[0]["root_id"] == job["id"]
    declined = CliRunner().invoke(app, ["project", "delete", "Book"], input="n\n")
    assert declined.exit_code != 0 and projects.list_projects()
    invoke("project", "delete", "Book", "--yes")
    assert invoke("project", "list") == []
    assert invoke("project", "deleted")[0]["path"] == str(w.path)
    invoke("project", "restore", "Book")
    assert w.draft(job["id"])["data"]["answer"] == "Kept answer"
