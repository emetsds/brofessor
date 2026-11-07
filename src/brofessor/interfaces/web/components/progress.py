"""Present the same measured workflow returned by `task progress`."""

import html
import time

import streamlit as st

from brofessor.application import progress
from brofessor.contracts.jobs import RESUMABLE_JOB_STATUSES, JobStatus, StageId, StageState


def duration(seconds):
    if seconds is None:
        return "—"
    seconds = max(0, round(seconds))
    return (
        f"{seconds // 3600}:{seconds // 60 % 60:02}:{seconds % 60:02}"
        if seconds >= 3600
        else f"{seconds // 60}:{seconds % 60:02}"
    )


def show(value, t, *, scope=""):
    done = value["status"] == JobStatus.SUCCEEDED
    summary = t(
        "Completed stages: {done} · Running: {running} · Remaining: {remaining}",
        done=value["completed"],
        running=value["running"],
        remaining=value["remaining"],
    )
    with st.expander(
        t("Workflow progress") + (" · " + duration(value["active_seconds"]) if done else ""),
        expanded=not done,
        key=f"{scope}workflow:{value['job_id']}:{done}",
    ):
        if not value["measured"]:
            st.caption(t("This older task has no recorded stage times."))
            return
        if not value["history_complete"]:
            st.caption(t("Execution before this task was resumed was not timed."))
        st.caption(
            summary + " · " + t("Execution time: {time}", time=duration(value["active_seconds"]))
        )
        if value["optional_remaining"]:
            st.caption(t("Optional stages: {count}", count=value["optional_remaining"]))
        st.caption(
            t(
                "Time in queue: {queue} · Paused: {paused}",
                queue=duration(value["queue_seconds"]),
                paused=duration(value["paused_seconds"]),
            )
        )
        if value["status"] == JobStatus.QUEUED:
            st.info(t("Waiting in queue"))
        elif value["status"] in RESUMABLE_JOB_STATUSES:
            status = t(
                {
                    JobStatus.CANCELLED: "Cancelled",
                    JobStatus.FAILED: "Failed",
                    JobStatus.INTERRUPTED: "Interrupted",
                }[value["status"]]
            )
            st.warning(
                t(
                    "{status} · Stopped at: {stage}",
                    status=status,
                    stage=t(progress.stage_label(value["stopped_stage"] or StageId.PREPARING)),
                )
            )
        icons = {
            StageState.COMPLETED: "✓",
            StageState.SKIPPED: "↷",
            StageState.RUNNING: "●",
            StageState.PENDING: "○",
            StageState.FAILED: "!",
            StageState.BLOCKED: "!",
            StageState.CANCELLED: "■",
            StageState.INTERRUPTED: "Ⅱ",
            StageState.UNMEASURED: "—",
        }
        labels = {
            StageState.COMPLETED: "Completed",
            StageState.SKIPPED: "Not needed for this run",
            StageState.RUNNING: "Running",
            StageState.PENDING: "Pending",
            StageState.FAILED: "Failed",
            StageState.BLOCKED: "Needs attention",
            StageState.CANCELLED: "Cancelled",
            StageState.INTERRUPTED: "Interrupted",
            StageState.UNMEASURED: "Time unavailable",
        }
        for step in value["steps"]:
            state = step["state"]
            label = t(step["label"])
            status = (
                t("If needed")
                if step.get("optional") and state == StageState.PENDING
                else t(labels[state])
            )
            st.html(
                f'<div class="brofessor-stage {state}"><span>{icons[state]} {html.escape(label)} <small>· {html.escape(status)}</small></span><time>{duration(step["seconds"])}</time></div>'
            )
            data = step["progress"]
            if state == StageState.RUNNING:
                if data.get("waiting_for_model"):
                    st.caption(t("Waiting for the text model's response"))
                if data.get("stage") == StageId.WAITING_FOR_SPEECH:
                    st.caption(t(progress.stage_label(StageId.WAITING_FOR_SPEECH)))
                if data.get("total") and step["stage"] != StageId.SOURCE_NAVIGATION:
                    completed, total = data.get("completed", 0), data["total"]
                    if step["stage"] == StageId.DOWNLOADING_MODEL:
                        text = t(
                            "Downloaded {completed} of {total} MB",
                            completed=round(completed / 1e6),
                            total=round(total / 1e6),
                        )
                    else:
                        text = t(
                            "{stage}: {completed} of {total} {units}",
                            stage=label,
                            completed=completed,
                            total=total,
                            units=t(progress.UNITS.get(step["stage"], "items")),
                        )
                    st.progress(max(0, min(completed / total, 1)), text=text)
                elif step["stage"] == StageId.SOURCE_NAVIGATION:
                    st.caption(
                        t(
                            "Original fragments opened: {fragments} · Documents: {documents}",
                            fragments=data.get("read_fragments", 0),
                            documents=data.get("selected_documents", 0),
                        )
                    )
                    st.caption(
                        t(
                            "Document scope is being determined; navigation limits are not a completion target."
                        )
                    )
            if step["attempts"] > 1:
                st.caption(
                    t(
                        "Attempts: {count}. Previously saved results are reused.",
                        count=step["attempts"],
                    )
                )
            if data.get("reused_checkpoints"):
                st.caption(t("Reused model results: {count}", count=data["reused_checkpoints"]))
        if value["last_confirmed"] and not done:
            st.caption(
                t(
                    "Last confirmed update: {time} ago. Waiting alone does not indicate a stalled job.",
                    time=duration(time.time() - value["last_confirmed"]),
                )
            )
