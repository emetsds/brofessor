"""Durable first narration of a newly created podcast, independent of its clients."""

from typing import cast

from brofessor.application import service
from brofessor.contracts.jobs import (
    ACTIVE_JOB_STATUSES,
    RESUMABLE_JOB_STATUSES,
    InitialAudioRecord,
    InitialAudioState,
    JobKind,
    JobStatus,
)
from brofessor.infrastructure.speech import catalogue as speech_models
from brofessor.infrastructure.storage.workspace import Workspace


def state(workspace: Workspace, job_id: str) -> InitialAudioRecord | None:
    with workspace.connect() as db:
        row = db.execute("SELECT * FROM initial_audio WHERE job_id=?", (job_id,)).fetchone()
    if row is None:
        return None
    result = cast(InitialAudioRecord, dict(row))
    if result["render_id"]:
        result["render"] = workspace.job(result["render_id"])
    elif result["revision"]:
        # Resolve the small crash window without mutating state or starting work.
        child = existing_render(workspace, job_id, result)
        if child:
            result["render_id"], result["render"] = child["id"], child
    return result


def pin(workspace, job_id):
    # The first saved script remains the input even if it is edited before recovery.
    with workspace.connect() as db:
        db.execute(
            "UPDATE initial_audio SET revision=(SELECT MIN(revision) FROM drafts WHERE job_id=?) WHERE job_id=? AND revision IS NULL",
            (job_id, job_id),
        )


def unavailable(spec):
    if speech_models.installed_path(spec) is None:
        return "Speech model files are missing. Open Settings → Models."
    if spec.get("engine", "").startswith("qwen3") and not speech_models.qwen_runtime_available():
        return "Install local speech support in the project environment, then restart the UI."
    return None


def existing_render(workspace, job_id, pending):
    if not pending or not pending["revision"]:
        return None
    job = workspace.job(job_id)
    return next(
        (
            child
            for child in workspace.jobs()
            if child["kind"] == JobKind.RENDER_PODCAST
            and child["params"].get("draft_job_id") == job_id
            and child["params"].get("revision") == pending["revision"]
            and service.uses_current_voice(
                child, job["params"]["language"], job["params"]["auto_audio"]
            )
        ),
        None,
    )


def continue_audio(workspace, job_id, *, start_worker=True):
    pending = state(workspace, job_id)
    if pending is None:
        raise ValueError("This task has no automatic narration policy")
    job = workspace.job(job_id)
    if job["status"] != JobStatus.SUCCEEDED:
        return pending
    pin(workspace, job_id)
    pending = state(workspace, job_id)
    # An enqueue may have committed just before the worker died or cancellation.
    previous = existing_render(workspace, job_id, pending)
    if previous:
        if (
            pending["state"] == InitialAudioState.CANCELLED
            and previous["status"] in ACTIVE_JOB_STATUSES
        ):
            workspace.cancel(previous["id"])
        with workspace.connect() as db:
            db.execute(
                "UPDATE initial_audio SET render_id=?,state=CASE WHEN state=? THEN state ELSE ? END,error=NULL WHERE job_id=?",
                (previous["id"], InitialAudioState.CANCELLED, InitialAudioState.QUEUED, job_id),
            )
        return state(workspace, job_id)
    if (
        pending["state"] not in (InitialAudioState.PENDING, InitialAudioState.BLOCKED)
        or not pending["revision"]
    ):
        return pending
    try:
        spec = job["params"]["auto_audio"]
        reason = unavailable(spec)
        if reason:
            raise ValueError(reason)
        child = service.render(
            workspace,
            job_id,
            model=spec,
            revision=pending["revision"],
            start_worker=False,
        )
        with workspace.connect() as db:
            db.execute(
                "UPDATE initial_audio SET render_id=?,state=CASE WHEN state=? THEN state ELSE ? END,error=NULL WHERE job_id=?",
                (child["id"], InitialAudioState.CANCELLED, InitialAudioState.QUEUED, job_id),
            )
        if state(workspace, job_id)["state"] == InitialAudioState.CANCELLED:
            workspace.cancel(child["id"])
        elif start_worker:
            from brofessor.application.worker import ensure_worker

            ensure_worker(workspace)
    except (ValueError, OSError, RuntimeError) as error:
        with workspace.connect() as db:
            db.execute(
                "UPDATE initial_audio SET state=?,error=? WHERE job_id=? AND state IN (?,?)",
                (
                    InitialAudioState.BLOCKED,
                    str(error)[:1500],
                    job_id,
                    InitialAudioState.PENDING,
                    InitialAudioState.BLOCKED,
                ),
            )
    return state(workspace, job_id)


def reconcile(workspace):
    with workspace.connect() as db:
        pending = [
            r[0]
            for r in db.execute(
                "SELECT a.job_id FROM initial_audio a JOIN jobs j ON a.job_id=j.id WHERE j.status=? AND a.render_id IS NULL",
                (JobStatus.SUCCEEDED,),
            )
        ]
    for job_id in pending:
        continue_audio(workspace, job_id, start_worker=False)


def cancel(workspace, job_id):
    pin(workspace, job_id)
    with workspace.connect() as db:
        db.execute(
            "UPDATE initial_audio SET state=? WHERE job_id=? OR render_id=?",
            (InitialAudioState.CANCELLED, job_id, job_id),
        )
        row = db.execute("SELECT render_id FROM initial_audio WHERE job_id=?", (job_id,)).fetchone()
    child = existing_render(workspace, job_id, state(workspace, job_id))
    child_id = (row[0] if row else None) or (child["id"] if child else None)
    if child_id and workspace.job(child_id)["status"] in ACTIVE_JOB_STATUSES:
        workspace.cancel(child_id)
    return state(workspace, job_id)


def resume(workspace, job_id, *, start_worker=True):
    if state(workspace, job_id) is None:
        raise ValueError("This task has no automatic narration policy")
    with workspace.connect() as db:
        db.execute(
            "UPDATE initial_audio SET state=CASE WHEN render_id IS NULL THEN ? ELSE ? END,error=NULL WHERE job_id=?",
            (InitialAudioState.PENDING, InitialAudioState.QUEUED, job_id),
        )
    pending = continue_audio(workspace, job_id, start_worker=False)
    if pending.get("render") and pending["render"]["status"] in RESUMABLE_JOB_STATUSES:
        workspace.resume(pending["render_id"])
    if start_worker:
        from brofessor.application.worker import ensure_worker

        ensure_worker(workspace)
    return state(workspace, job_id)
