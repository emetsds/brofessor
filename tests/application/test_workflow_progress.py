"""Timing follows real stage boundaries and excludes a stopped worker's downtime."""

from brofessor.application import progress, service
from brofessor.contracts.jobs import JobKind, JobStatus
from brofessor.infrastructure.storage.workspace import Workspace


def test_stage_timing_survives_fault_resume_and_dynamic_work_counts(tmp_path, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr("time.time", lambda: clock[0])
    w = Workspace(tmp_path / "workspace")
    source = tmp_path / "source.txt"
    source.write_text("Bridge evidence")
    w.add_source(source)
    job = service.submit(w, JobKind.PODCAST, minutes=20, auto_audio=False, start_worker=False)
    clock[0] = 110
    w.claim()
    clock[0] = 112
    w.update_job(job["id"], progress={"stage": "reading", "completed": 1, "total": 3})
    clock[0] = 120
    progress.heartbeat(w, job["id"])
    clock[0] = 500
    w.recover()
    failed = progress.snapshot(w, job["id"])
    reading = next(s for s in failed["steps"] if s["stage"] == "reading")
    assert reading["seconds"] == 8 and reading["state"] == "interrupted"
    assert failed["paused_seconds"] == 380
    clock[0] = 520
    w.resume(job["id"])
    clock[0] = 530
    w.claim()
    clock[0] = 532
    w.update_job(
        job["id"],
        progress={"stage": "reading", "completed": 3, "total": 3, "reused_checkpoints": 1},
    )
    clock[0] = 535
    w.update_job(job["id"], progress={"stage": "outline"})
    clock[0] = 540
    w.update_job(job["id"], progress={"stage": "script", "completed": 2, "total": 7})
    value = progress.snapshot(Workspace(w.path), job["id"])
    read = next(s for s in value["steps"] if s["stage"] == "reading")
    assert read["seconds"] == 11 and read["attempts"] == 2
    assert read["progress"]["reused_checkpoints"] == 1
    assert value["active_seconds"] == 20
    assert value["queue_seconds"] == 20
    assert value["paused_seconds"] == 400
    assert value["current"]["stage"] == "script"
    import json

    from typer.testing import CliRunner

    from brofessor.interfaces.cli.app import app

    result = CliRunner().invoke(app, ["-w", str(w.path), "task", "progress", job["id"]])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == value
    assert value["current"]["progress"] == {"stage": "script", "completed": 2, "total": 7}
    assert next(s for s in value["steps"] if s["stage"] == "consolidating")["state"] == "skipped"
    done = value["completed"]
    clock[0] = 545
    w.update_job(job["id"], progress={"stage": "script", "completed": 1, "total": 4})
    assert progress.snapshot(w, job["id"])["completed"] == done
    clock[0] = 548
    w.update_job(job["id"], status=JobStatus.FAILED, error="Controlled fault")
    assert (
        next(s for s in progress.snapshot(w, job["id"])["steps"] if s["stage"] == "script")["state"]
        == "failed"
    )


def test_legacy_jobs_do_not_invent_durations_and_cancelled_queue_is_closed(tmp_path):
    w = Workspace(tmp_path / "workspace")
    job = w.submit(JobKind.SLIDES, {})
    w.cancel(job["id"])
    with w.connect() as db:
        assert (
            db.execute("SELECT state FROM job_stages WHERE job_id=?", (job["id"],)).fetchone()[0]
            == "cancelled"
        )
        db.execute("DELETE FROM job_stages WHERE job_id=?", (job["id"],))
    w.update_job(job["id"], status=JobStatus.SUCCEEDED)
    value = progress.snapshot(w, job["id"])
    assert not value["measured"] and value["active_seconds"] is None
    assert all(s["seconds"] is None for s in value["steps"])
