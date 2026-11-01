"""Deterministic CLI wait lifecycle checks; no model, subprocess, or wall-clock delay."""

from types import SimpleNamespace

import pytest
from click import ClickException
from typer.testing import CliRunner

from brofessor import cli, worker


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


@pytest.mark.parametrize(
    "command", [["ask", "Question?", "--wait"], ["draft", "render", "draft-id", "--wait"]]
)
def test_both_cli_wait_paths_use_recovery_helper(tmp_path, monkeypatch, command):
    calls = []
    job = {"id": "fixture", "status": "queued"}
    monkeypatch.setattr(cli.service, "submit", lambda *a, **k: job)
    monkeypatch.setattr(cli.service, "render", lambda *a, **k: job)

    def wait(workspace, job_id):
        calls.append(job_id)
        return {"id": job_id, "status": "interrupted"}

    monkeypatch.setattr(cli, "wait_for_job", wait)
    result = CliRunner().invoke(cli.app, ["-w", str(tmp_path), *command])
    assert result.exit_code == 1
    assert '"status": "interrupted"' in result.output
    assert calls == ["fixture"]
