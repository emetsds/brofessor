"""Measured workflow stages in the existing workspace, shared by both clients."""

import json
import time

from brofessor.contracts.jobs import (
    AUDIO_RENDER_JOB_KINDS,
    CONSOLIDATION_JOB_KINDS,
    DOWNLOAD_JOB_KINDS,
    READING_WORKFLOW_JOB_KINDS,
    RESUMABLE_JOB_STATUSES,
    TERMINAL_JOB_STATUSES,
    TRANSLATION_JOB_KINDS,
    InitialAudioState,
    JobKind,
    JobRecord,
    JobStatus,
    StageId,
    StageState,
    TaskStatus,
)

LABELS = {
    StageId.QUEUED: "Waiting in queue",
    StageId.PREPARING: "Preparing task",
    StageId.READING: "Reading sources",
    StageId.SEARCHING: "Searching original fragments",
    StageId.SOURCE_NAVIGATION: "Finding and reading documents",
    StageId.CONSOLIDATING: "Consolidating reading notes",
    StageId.OUTLINE: "Planning episode",
    StageId.SERIES_PLAN: "Planning series",
    StageId.SCRIPT: "Writing script",
    StageId.WRITING: "Writing result",
    StageId.VALIDATING: "Checking result",
    StageId.SAVING: "Saving result",
    StageId.SPEECH: "Generating speech",
    StageId.AUDIO_PREPARING: "Preparing audio",
    StageId.AUDIO_PACKAGING: "Packaging audio",
    StageId.WAITING_FOR_SPEECH: "Waiting for another local speech job to finish",
    StageId.GLOSSARY: "Collecting book terminology",
    StageId.GLOSSARY_REVIEW: "Checking recurring terminology",
    StageId.TRANSLATION: "Translating book",
    StageId.TERMINOLOGY_UPDATE: "Updating linked passages",
    StageId.CHECKING_SCRIPT: "Checking script against sources",
    StageId.STUDY_REVIEW: "Reviewing answers",
    StageId.DOWNLOADING_MODEL: "Downloading model",
    StageId.RENDERING: "Building file",
}
UNITS = {
    StageId.READING: "fragments",
    StageId.CONSOLIDATING: "groups",
    StageId.SCRIPT: "sections",
    StageId.SPEECH: "turns",
    StageId.TRANSLATION: "passages",
    StageId.CHECKING_SCRIPT: "batches",
    StageId.SOURCE_NAVIGATION: "navigation actions",
    StageId.GLOSSARY: "passages",
    StageId.STUDY_REVIEW: "answers",
}


def stage_label(stage):
    return LABELS.get(stage) or LABELS.get(canonical(stage), "Running")


def canonical(stage):
    return {
        StageId.DRAFT_READY: StageId.SAVING,
        StageId.TRANSLATED_BOOK: StageId.SAVING,
        StageId.CHECKED_SCRIPT: StageId.SAVING,
        StageId.WAITING_FOR_SPEECH: StageId.SPEECH,
    }.get(stage, stage)


def record(db, job_id, *, stage=None, data=None, status=None, now=None, recovered=False):
    now = time.time() if now is None else now
    row = db.execute(
        "SELECT * FROM job_stages WHERE job_id=? ORDER BY id DESC LIMIT 1", (job_id,)
    ).fetchone()
    if row and row["state"] == StageState.RUNNING:
        # Recovery knows only the last heartbeat, never the time of the crash.
        end = row["touched"] if recovered else now
        elapsed = row["elapsed"] + max(0, end - row["touched"])
        finished = status in TERMINAL_JOB_STATUSES or (stage and canonical(stage) != row["stage"])
        db.execute(
            "UPDATE job_stages SET elapsed=?,touched=?,ended=?,state=? WHERE id=?",
            (
                elapsed,
                end,
                end if finished else None,
                status
                if status in RESUMABLE_JOB_STATUSES
                else StageState.COMPLETED
                if finished
                else StageState.RUNNING,
                row["id"],
            ),
        )
        if not finished:
            if data is not None:
                previous = json.loads(row["data"])
                if previous.get("reused_checkpoints"):
                    data = {"reused_checkpoints": previous["reused_checkpoints"], **data}
                db.execute(
                    "UPDATE job_stages SET data=? WHERE id=?",
                    (json.dumps(data, ensure_ascii=False), row["id"]),
                )
            return
    if stage and status not in TERMINAL_JOB_STATUSES:
        db.execute(
            "INSERT INTO job_stages(job_id,stage,state,started,touched,data) VALUES (?,?,?,?,?,?)",
            (
                job_id,
                canonical(stage),
                StageState.RUNNING,
                now,
                now,
                json.dumps(data or {}, ensure_ascii=False),
            ),
        )


def heartbeat(workspace, job_id):
    with workspace.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        job = db.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
        if job and job[0] == JobStatus.RUNNING:
            record(db, job_id)


def workflow(job: JobRecord) -> list[tuple[str, bool]]:
    kind, params = job["kind"], job["params"]
    steps = [(StageId.PREPARING, False)]
    if kind in READING_WORKFLOW_JOB_KINDS:
        steps += [(StageId.SOURCE_NAVIGATION, False)] if params.get("collections") else []
        steps += [(StageId.READING, False)]
        if kind in CONSOLIDATION_JOB_KINDS:
            steps += [(StageId.CONSOLIDATING, True)]
        if kind == JobKind.PODCAST:
            steps += [(StageId.OUTLINE, False)] if params["minutes"] >= 20 else []
            steps += [(StageId.SCRIPT, False)]
        else:
            steps += [
                (StageId.SERIES_PLAN if kind == JobKind.PODCAST_SERIES else StageId.WRITING, False)
            ]
        steps += [(StageId.VALIDATING, False), (StageId.SAVING, False)]
    elif kind in AUDIO_RENDER_JOB_KINDS:
        steps += [(StageId.SPEECH, False), (StageId.AUDIO_PACKAGING, False)]
    elif kind in TRANSLATION_JOB_KINDS:
        steps += [
            (StageId.GLOSSARY, False),
            (StageId.GLOSSARY_REVIEW, True),
            (StageId.TRANSLATION, False),
            (StageId.SAVING, False),
        ]
    elif kind == JobKind.CHECK_PODCAST:
        steps += [(StageId.CHECKING_SCRIPT, False), (StageId.SAVING, False)]
    elif kind == JobKind.REVIEW_STUDY:
        steps += [(StageId.STUDY_REVIEW, False), (StageId.SAVING, False)]
    elif kind in DOWNLOAD_JOB_KINDS:
        steps += [(StageId.DOWNLOADING_MODEL, False)]
    elif kind == JobKind.AUDIOBOOK:
        steps += [(StageId.READING, False), (StageId.SAVING, False)]
    else:
        steps += [(StageId.RENDERING, False)]
    return steps


def snapshot(workspace, job_id, *, now=None, include_audio=True):
    now = time.time() if now is None else now
    job = workspace.job(job_id)
    with workspace.connect() as db:
        rows = [
            dict(r)
            for r in db.execute("SELECT * FROM job_stages WHERE job_id=? ORDER BY id", (job_id,))
        ]
    for row in rows:
        row["data"] = json.loads(row["data"])
    planned = workflow(job)
    # Real branches (e.g. retrieval or an additional terminology pass) become visible.
    for index, row in enumerate(rows):
        if row["stage"] != StageId.QUEUED and row["stage"] not in {s for s, _ in planned}:
            previous = next(
                (
                    r["stage"]
                    for r in reversed(rows[:index])
                    if r["stage"] in {s for s, _ in planned}
                ),
                None,
            )
            position = next(
                (i + 1 for i, (stage, _) in enumerate(planned) if stage == previous), len(planned)
            )
            planned.insert(position, (row["stage"], False))
    observed = {row["stage"] for row in rows}
    last_seen = max((i for i, (stage, _) in enumerate(planned) if stage in observed), default=-1)
    steps = []
    for i, (stage, optional) in enumerate(planned):
        attempts = [row for row in rows if row["stage"] == stage]
        latest = attempts[-1] if attempts else None
        state = (
            latest["state"]
            if latest
            else StageState.SKIPPED
            if i < last_seen or job["status"] == JobStatus.SUCCEEDED
            else StageState.PENDING
        )
        # Old successful jobs have no measured stage history.
        if not rows:
            state = StageState.UNMEASURED
        steps.append(
            {
                "stage": stage,
                "label": stage_label(stage),
                "state": state,
                "optional": optional,
                "seconds": sum(row["elapsed"] for row in attempts) if attempts else None,
                "attempts": len(attempts),
                "progress": latest["data"] if latest else {},
            }
        )
    queue = sum(row["elapsed"] for row in rows if row["stage"] == StageId.QUEUED)
    if rows and rows[-1]["stage"] == StageId.QUEUED and rows[-1]["state"] == StageState.RUNNING:
        queue += max(0, now - rows[-1]["touched"])
    paused = sum(
        max(0, after["started"] - before["ended"])
        for before, after in zip(rows, rows[1:])
        if before["ended"] is not None
        and before["state"] in (StageState.INTERRUPTED, StageState.FAILED, StageState.CANCELLED)
    )
    if (
        rows
        and rows[-1]["state"] in (StageState.INTERRUPTED, StageState.FAILED, StageState.CANCELLED)
        and rows[-1]["ended"] is not None
    ):
        paused += max(0, now - rows[-1]["ended"])
    result = {
        "job_id": job_id,
        "status": job["status"],
        "measured": bool(rows),
        "history_complete": bool(rows) and rows[0]["started"] == job["created"],
        "steps": steps,
        "active_seconds": sum(row["elapsed"] for row in rows if row["stage"] != StageId.QUEUED)
        if rows
        else None,
        "queue_seconds": queue if rows else None,
        "paused_seconds": paused if rows else None,
        "last_confirmed": job["updated"] if rows else None,
        "stopped_stage": rows[-1]["stage"]
        if rows and job["status"] in RESUMABLE_JOB_STATUSES
        else None,
    }
    if include_audio and job["kind"] == JobKind.PODCAST and job["params"].get("auto_audio"):
        from brofessor.application import initial_audio

        audio = initial_audio.state(workspace, job_id)
        result["initial_audio"] = audio
        if audio and audio.get("render"):
            child = snapshot(workspace, audio["render_id"], now=now, include_audio=False)
            result["steps"] += [
                {**s, "stage": StageId.AUDIO_PREPARING, "label": "Preparing audio"}
                if s["stage"] == StageId.PREPARING
                else s
                for s in child["steps"]
            ]
            if result["active_seconds"] is not None and child["active_seconds"] is not None:
                result["active_seconds"] += child["active_seconds"]
                result["queue_seconds"] += child["queue_seconds"]
                result["paused_seconds"] += child["paused_seconds"] + max(
                    0, audio["render"]["created"] - job["updated"]
                )
                result["history_complete"] = (
                    result["history_complete"] and child["history_complete"]
                )
            result["status"] = child["status"]
            result["stopped_stage"] = child["stopped_stage"]
            result["last_confirmed"] = child["last_confirmed"] or result["last_confirmed"]
        else:
            if result["paused_seconds"] is not None and job["status"] == JobStatus.SUCCEEDED:
                result["paused_seconds"] += max(0, now - job["updated"])
            for stage in (StageId.AUDIO_PREPARING, StageId.SPEECH, StageId.AUDIO_PACKAGING):
                result["steps"].append(
                    {
                        "stage": stage,
                        "label": stage_label(stage),
                        "state": StageState.CANCELLED
                        if audio and audio["state"] == InitialAudioState.CANCELLED
                        else StageState.BLOCKED
                        if audio and audio["state"] == InitialAudioState.BLOCKED
                        else StageState.PENDING,
                        "seconds": None,
                        "attempts": 0,
                        "progress": {},
                    }
                )
            if job["status"] == JobStatus.SUCCEEDED:
                result["status"] = audio["state"] if audio else TaskStatus.PENDING
    result["completed"] = sum(s["state"] == StageState.COMPLETED for s in result["steps"])
    result["remaining"] = sum(
        s["state"] in (StageState.PENDING, StageState.BLOCKED) and not s.get("optional")
        for s in result["steps"]
    )
    result["optional_remaining"] = sum(
        s["state"] == StageState.PENDING and s.get("optional", False) for s in result["steps"]
    )
    result["running"] = sum(s["state"] == StageState.RUNNING for s in result["steps"])
    result["current"] = next(
        (s for s in reversed(result["steps"]) if s["state"] == StageState.RUNNING), None
    )
    return result
