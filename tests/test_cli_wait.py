"""Deterministic CLI wait lifecycle checks; no model, subprocess, or wall-clock delay."""

import json
from types import SimpleNamespace

import pytest
from click import ClickException
from typer.testing import CliRunner

from brofessor import cli, service, worker
from brofessor.workspace import Workspace


class Clock:
    now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(cli.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(cli.time, "sleep", clock.sleep)
    return clock


def store(tmp_path, status):
    return SimpleNamespace(path=tmp_path, job=lambda job_id: {"id": job_id, "status": status()})


def test_existing_worker_completes_without_extra_start(tmp_path, monkeypatch, clock):
    workspace = store(tmp_path, lambda: "running" if clock.now < 0.3 else "succeeded")
    monkeypatch.setattr(worker, "is_running", lambda workspace: True)
    monkeypatch.setattr(worker, "ensure_worker", lambda workspace: pytest.fail("Unnecessary start"))
    assert cli.wait_for_job(workspace, "job")["status"] == "succeeded"


def test_missing_worker_is_started_once_and_allowed_to_start(tmp_path, monkeypatch, clock):
    workspace = store(tmp_path, lambda: "queued" if clock.now < 0.4 else "succeeded")
    starts = []
    monkeypatch.setattr(worker, "is_running", lambda workspace: clock.now >= 0.2)
    monkeypatch.setattr(worker, "ensure_worker", lambda workspace: starts.append(clock.now))
    assert cli.wait_for_job(workspace, "job")["status"] == "succeeded"
    assert len(starts) == 1


def test_crashed_worker_recovery_returns_interrupted_without_resubmitting(
    tmp_path, monkeypatch, clock
):
    starts = []
    workspace = store(tmp_path, lambda: "interrupted" if starts else "running")
    monkeypatch.setattr(worker, "is_running", lambda workspace: clock.now < 0.2)
    monkeypatch.setattr(worker, "ensure_worker", lambda workspace: starts.append(clock.now))
    assert cli.wait_for_job(workspace, "job")["status"] == "interrupted"
    assert len(starts) == 1


def test_startup_failure_is_bounded_and_names_log(tmp_path, monkeypatch, clock):
    workspace = store(tmp_path, lambda: "queued")
    starts = []
    monkeypatch.setattr(worker, "is_running", lambda workspace: False)
    monkeypatch.setattr(worker, "ensure_worker", lambda workspace: starts.append(clock.now))
    with pytest.raises(ClickException, match="worker.log"):
        cli.wait_for_job(workspace, "job")
    assert len(starts) == 1
    assert 5 <= clock.now < 5.5


def test_recovered_worker_failure_does_not_start_an_infinite_fork_loop(
    tmp_path, monkeypatch, clock
):
    workspace = store(tmp_path, lambda: "running")
    starts = []
    monkeypatch.setattr(worker, "is_running", lambda workspace: 0.2 <= clock.now < 0.4)
    monkeypatch.setattr(worker, "ensure_worker", lambda workspace: starts.append(clock.now))
    with pytest.raises(ClickException, match="stopped again"):
        cli.wait_for_job(workspace, "job")
    assert len(starts) == 1


def test_process_start_error_has_actionable_diagnostic(tmp_path, monkeypatch, clock):
    workspace = store(tmp_path, lambda: "running")
    monkeypatch.setattr(worker, "is_running", lambda workspace: False)

    def fail(workspace):
        raise OSError("synthetic spawn failure")

    monkeypatch.setattr(worker, "ensure_worker", fail)
    with pytest.raises(ClickException, match="worker.log"):
        cli.wait_for_job(workspace, "job")


@pytest.mark.parametrize("command", ["ask", "render"])
def test_cli_wait_reports_persisted_interruption_and_failure_exit(tmp_path, monkeypatch, command):
    workspace = Workspace(tmp_path / "workspace")
    source = tmp_path / "source.txt"
    source.write_text("A synthetic experiment was performed.")
    workspace.add_source(source)
    if command == "ask":
        args = ["ask", "What happened?", "--wait"]
    else:
        original = service.submit(workspace, "slides", start_worker=False)
        citation = workspace.units()[0]["id"]
        workspace.save_draft(
            original["id"],
            {
                "title": "Test",
                "language": "en",
                "slides": [
                    {
                        "title": "An experiment",
                        "bullets": ["It was performed"],
                        "notes": "A synthetic source",
                        "citations": [citation],
                    }
                ],
            },
        )
        workspace.update_job(original["id"], status="succeeded")
        args = ["draft", "render", original["id"], "--wait"]

    def interrupted_worker(store):
        if store.claim() is not None:
            store.recover()

    monkeypatch.setattr(worker, "ensure_worker", interrupted_worker)
    result = CliRunner().invoke(cli.app, ["-w", str(workspace.path), *args])
    assert result.exit_code == 1, result.output
    returned = json.loads(result.output)
    assert returned["status"] == "interrupted"
    assert Workspace(workspace.path).job(returned["id"])["status"] == "interrupted"
