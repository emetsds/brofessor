import json
import os
import signal
import subprocess
import sys
import time
from threading import Thread

import pytest

from brofessor import executors, pipeline, service, worker
from brofessor.workspace import Workspace, atomic_json


@pytest.fixture
def workspace(tmp_path):
    return Workspace(tmp_path / "workspace")


def wait_for(predicate, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("Timed out waiting for test process state")


def stop_process(process):
    if process.poll() is None:
        process.kill()
    process.wait(timeout=5)


@pytest.mark.parametrize("outcome", ["succeeded", "failed", "cancelled"])
def test_worker_records_outcome_and_keeps_progress(workspace, monkeypatch, outcome):
    submitted = workspace.submit("fixture", {})

    def execute(store, job, cancelled):
        assert job["status"] == "running"
        assert worker.is_running(store)
        store.update_job(job["id"], progress={"completed": 2})
        if outcome == "cancelled":
            store.cancel(job["id"])
            assert cancelled()
            raise executors.CancelledError("Stopped by user")
        if outcome == "failed":
            raise RuntimeError("Synthetic failure")

    monkeypatch.setattr(pipeline, "execute", execute)
    assert worker.run(workspace, once=True)
    job = workspace.job(submitted["id"])
    assert job["status"] == outcome
    assert job["progress"] == {"completed": 2}
    assert job["error"] is None if outcome == "succeeded" else job["error"]
    assert not worker.is_running(workspace)


def test_sigterm_interrupts_job_and_restores_signal_handlers(workspace, monkeypatch):
    submitted = workspace.submit("fixture", {})
    previous_term = signal.getsignal(signal.SIGTERM)
    previous_int = signal.getsignal(signal.SIGINT)

    def execute(store, job, cancelled):
        store.update_job(job["id"], progress={"completed": 1})
        os.kill(os.getpid(), signal.SIGTERM)
        assert cancelled()
        raise executors.CancelledError("Worker is stopping")

    monkeypatch.setattr(pipeline, "execute", execute)
    worker.run(workspace, once=True)
    assert workspace.job(submitted["id"])["status"] == "interrupted"
    assert workspace.job(submitted["id"])["progress"] == {"completed": 1}
    assert signal.getsignal(signal.SIGTERM) == previous_term
    assert signal.getsignal(signal.SIGINT) == previous_int
    assert not worker.is_running(workspace)


def test_os_lock_blocks_second_process_and_stale_pid_does_not(workspace, monkeypatch):
    submitted = workspace.submit("fixture", {})
    workspace.claim()
    ready = workspace.path / "lock-ready"
    code = """
import sys, time
from pathlib import Path
from brofessor.workspace import Workspace
from brofessor.worker import worker_lock
store = Workspace(sys.argv[1])
with worker_lock(store) as lock:
    assert lock is not None
    Path(sys.argv[2]).write_text('ready')
    time.sleep(60)
"""
    owner = subprocess.Popen([sys.executable, "-c", code, str(workspace.path), str(ready)])
    try:
        wait_for(ready.exists)
        assert worker.is_running(workspace)
        monkeypatch.setattr(pipeline, "execute", lambda *_: pytest.fail("Second worker executed"))
        assert worker.run(workspace, once=True) is False
        # A failed lock acquisition must never recover a live worker's job.
        assert workspace.job(submitted["id"])["status"] == "running"
    finally:
        stop_process(owner)
    (workspace.path / "worker.lock").write_text(str(os.getpid()))
    assert not worker.is_running(workspace)


def test_crash_recovery_requires_explicit_resume_and_preserves_checkpoint(workspace, monkeypatch):
    submitted = workspace.submit("fixture", {})
    checkpoint = workspace.path / "completed-stage.json"
    ready = workspace.path / "worker-ready"
    code = """
import sys, time
from pathlib import Path
from brofessor import pipeline, worker
from brofessor.workspace import Workspace, atomic_json
store = Workspace(sys.argv[1])
def execute(workspace, job, cancelled):
    atomic_json(workspace.path / 'completed-stage.json', {'stage': 1, 'text': 'Completed result'})
    workspace.update_job(job['id'], progress={'completed': 1})
    Path(sys.argv[2]).write_text('ready')
    time.sleep(60)
pipeline.execute = execute
worker.run(store, once=True)
"""
    crashed = subprocess.Popen([sys.executable, "-c", code, str(workspace.path), str(ready)])
    try:
        wait_for(ready.exists)
        assert workspace.job(submitted["id"])["status"] == "running"
        assert worker.is_running(workspace)
    finally:
        stop_process(crashed)
    assert not worker.is_running(workspace)
    monkeypatch.setattr(pipeline, "execute", lambda *_: pytest.fail("Recovery auto-ran a job"))
    worker.run(workspace, once=True)
    interrupted = workspace.job(submitted["id"])
    assert interrupted["status"] == "interrupted"
    assert interrupted["progress"] == {"completed": 1}
    assert json.loads(checkpoint.read_text()) == {"stage": 1, "text": "Completed result"}
    workspace.resume(submitted["id"])

    def resume(store, job, cancelled):
        assert json.loads(checkpoint.read_text())["stage"] == 1
        store.update_job(job["id"], progress={"completed": 2})

    monkeypatch.setattr(pipeline, "execute", resume)
    worker.run(workspace, once=True)
    assert workspace.job(submitted["id"])["status"] == "succeeded"
    assert workspace.job(submitted["id"])["progress"] == {"completed": 2}


def test_job_cancel_stops_owned_process_but_preserves_unrelated_process(workspace, monkeypatch):
    submitted = workspace.submit("fixture", {})
    child_marker = workspace.path / "owned-pid"
    child_code = (
        "import os,sys,time; from pathlib import Path; "
        "Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(60)"
    )
    unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])

    def execute(store, job, cancelled):
        executors._run_process(
            [sys.executable, "-c", child_code, str(child_marker)],
            cwd=workspace.path,
            timeout=10,
            cancelled=cancelled,
        )

    def cancel():
        wait_for(child_marker.exists)
        workspace.cancel(submitted["id"])

    monkeypatch.setattr(pipeline, "execute", execute)
    cancelling = Thread(target=cancel)
    cancelling.start()
    try:
        worker.run(workspace, once=True)
        cancelling.join(timeout=5)
        assert not cancelling.is_alive()
        assert workspace.job(submitted["id"])["status"] == "cancelled"
        assert unrelated.poll() is None
        with pytest.raises(ProcessLookupError):
            os.kill(int(child_marker.read_text()), 0)
    finally:
        stop_process(unrelated)
        cancelling.join(timeout=10)


def test_real_pipeline_reuses_accepted_checkpoints_after_failure(workspace, tmp_path, monkeypatch):
    incoming = tmp_path / "large.txt"
    incoming.write_text("Synthetic lighthouse evidence. " * 1000)
    source = workspace.add_source(incoming)
    units = workspace.units([source["id"]])
    assert len(units) > 2
    submitted = service.submit(
        workspace, "slides", slide_count=1, focus="What is the evidence?", start_worker=False
    )
    calls = []
    fail_once = True

    def generate(prompt, schema, *args, **kwargs):
        nonlocal fail_once
        if schema["title"] == "ReadingBatch":
            batch = json.loads(prompt.split("\n", 1)[1])["fragments"]
            calls.append([unit["id"] for unit in batch])
            if len(calls) == 2 and fail_once:
                fail_once = False
                raise RuntimeError("Temporary failure after the first accepted result")
            return {
                "notes": [
                    {"summary": "Synthetic lighthouse evidence.", "citations": [unit["id"]]}
                    for unit in batch
                ]
            }
        return {
            "title": "Evidence",
            "language": "ru",
            "slides": [
                {
                    "title": "Lighthouse",
                    "bullets": ["A lighthouse"],
                    "notes": "Original evidence.",
                    "citations": [units[0]["id"]],
                }
            ],
        }

    monkeypatch.setattr(executors, "generate", generate)
    worker.run(workspace, once=True)
    assert workspace.job(submitted["id"])["status"] == "failed"
    checkpoints = workspace.path / "jobs" / submitted["id"] / "checkpoints"
    assert len(list(checkpoints.glob("*.json"))) == 1
    workspace.resume(submitted["id"])
    worker.run(workspace, once=True)
    assert workspace.job(submitted["id"])["status"] == "succeeded"
    assert len(calls) == 3
    assert calls[1] == calls[2]
    assert set(calls[0]) | set(calls[2]) == {unit["id"] for unit in units}
    coverage = json.loads((checkpoints.parent / "coverage.json").read_text())
    assert set(coverage["read"]) == {unit["id"] for unit in units}


def test_resume_after_draft_publication_failure_preserves_author_revision(
    workspace, tmp_path, monkeypatch
):
    incoming = tmp_path / "chapter.txt"
    incoming.write_text("A synthetic lighthouse is blue.")
    source = workspace.add_source(incoming)
    unit = workspace.units([source["id"]])[0]
    submitted = service.submit(workspace, "ask", focus="What color?", start_worker=False)
    calls = []

    def generate(*args, **kwargs):
        calls.append(1)
        return {
            "answer": "Blue.",
            "citations": [unit["id"]],
            "quotes": [{"citation": unit["id"], "text": "A synthetic lighthouse is blue."}],
        }

    def fail_publication(path, value):
        if path.name.startswith("draft-r"):
            raise OSError("Synthetic disk error after draft commit")
        atomic_json(path, value)

    monkeypatch.setattr(executors, "generate", generate)
    monkeypatch.setattr(pipeline, "atomic_json", fail_publication)
    worker.run(workspace, once=True)
    assert workspace.job(submitted["id"])["status"] == "failed"
    assert workspace.draft(submitted["id"])["revision"] == 1
    author_data = {
        "answer": "The lighthouse is blue (my edited wording).",
        "citations": [unit["id"]],
    }
    workspace.save_draft(submitted["id"], author_data, 1)
    monkeypatch.setattr(pipeline, "atomic_json", atomic_json)
    workspace.resume(submitted["id"])
    worker.run(workspace, once=True)
    assert workspace.job(submitted["id"])["status"] == "succeeded"
    assert workspace.draft(submitted["id"])["data"] == author_data
    assert workspace.draft(submitted["id"])["revision"] == 2
    assert len(calls) == 1
    artifact = workspace.artifacts(submitted["id"])[0]
    assert json.loads((workspace.path / artifact["path"]).read_text()) == author_data
    assert artifact["metadata"]["revision"] == 2
