"""Web components: jobs."""

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import streamlit as st

from brofessor.contracts.jobs import (
    ACTIVE_JOB_STATUSES,
    RESUMABLE_JOB_STATUSES,
    InitialAudioState,
    JobKind,
    JobStatus,
    StageId,
)
from brofessor.interfaces.web.components import content as ui_content
from brofessor.interfaces.web.components import language as ui_language
from brofessor.interfaces.web.labels import STATUS_LABELS
from brofessor.interfaces.web.state_keys import NAVIGATION_KEY, Page, ProjectKey, project_key


@st.fragment(run_every=2)
def active_work(context):
    workspace = context.workspace
    t = context.t
    jobs = workspace.jobs()
    active = [job for job in jobs if job["status"] in ACTIVE_JOB_STATUSES]
    key = project_key(workspace.path, ProjectKey.ACTIVE_WORK)
    snapshot = [(job["id"], job["status"]) for job in active]
    previous = st.session_state.get(key)
    st.session_state[key] = snapshot
    if previous is not None and previous != snapshot:
        st.rerun()
    for job in sorted(active, key=lambda j: j["status"] != JobStatus.RUNNING)[:3]:
        target = job["params"].get("draft_job_id") or job["id"]
        showing = (
            st.session_state.get(NAVIGATION_KEY) == Page.RESULTS
            and not st.session_state.get(project_key(workspace.path, ProjectKey.CREATING))
            and not st.session_state.get(project_key(workspace.path, ProjectKey.CATALOGUE))
            and st.session_state.get(project_key(workspace.path, ProjectKey.SELECTED_JOB)) == target
        )
        if showing:
            continue
        label, action = st.columns([4, 1])
        label.caption(t("Processing: {title}", title=context.result_title(job)))
        from brofessor.application.progress import stage_label

        label.caption(t(stage_label(job["progress"].get("stage", StageId.QUEUED))))
        if job["kind"] != JobKind.DOWNLOAD_MODEL and action.button(
            t("Open task"), key=f"active-open-{job['id']}"
        ):
            context.open_result(target)
            st.rerun(scope="app")


def output_label(context, job):
    t = context.t
    try:
        zone = ZoneInfo(getattr(st.context, "timezone", None) or "UTC")
    except ZoneInfoNotFoundError:
        zone = ZoneInfo("UTC")
    stamp = datetime.fromtimestamp(job["created"], zone).strftime("%d.%m %H:%M:%S")
    model = (
        job["params"].get("model_spec", {}).get("name")
        or job["params"].get("model")
        or t(
            "PDF"
            if job["kind"] == JobKind.RENDER_PDF
            else "EPUB"
            if job["kind"] == JobKind.RENDER_EPUB
            else "Audio"
            if job["kind"] == JobKind.RENDER_PODCAST
            else "Presentation"
        )
    )
    return (
        t(
            "Revision {revision} · {status}",
            revision=job["params"]["revision"],
            status=t(STATUS_LABELS[job["status"]]),
        )
        + f" · {model} · {stamp}"
    )


@st.fragment(run_every=2)
def job_status(context, job_id, scope=""):
    workspace = context.workspace
    t = context.t
    from brofessor.application import initial_audio, progress
    from brofessor.interfaces.web.components import progress as ui_progress

    job = workspace.job(job_id)
    value = progress.snapshot(workspace, job_id)
    audio = value.get("initial_audio")
    status_key = project_key(workspace.path, ProjectKey.STATUS, job_id)
    snapshot = (job["status"], value["status"], audio.get("render_id") if audio else None)
    previous = st.session_state.get(status_key)
    st.session_state[status_key] = snapshot
    if previous is not None and previous != snapshot:
        st.rerun(scope="app")
    ui_progress.show(value, t, scope=scope)
    target = audio["render"] if audio and audio.get("render") else job
    ui_content.job_error(target, t)
    if audio and audio["state"] == InitialAudioState.BLOCKED:
        st.warning(
            t(audio["error"])
            if audio["error"] in ui_language.RUSSIAN
            else t("Details: {error}", error=audio["error"])
        )
        st.button(
            t("Open model settings"),
            key=f"auto-model-settings:{job_id}",
            on_click=context.show_model_settings,
            args=(job["params"]["auto_audio"]["id"],),
        )
    active = target["status"] in ACTIVE_JOB_STATUSES or (
        audio
        and job["status"] == JobStatus.SUCCEEDED
        and audio["state"] in (InitialAudioState.PENDING, InitialAudioState.BLOCKED)
    )
    if active and st.button(t("Cancel"), key=f"{scope}cancel-{job_id}"):
        if audio and job["status"] == JobStatus.SUCCEEDED:
            initial_audio.cancel(workspace, job_id)
        else:
            workspace.cancel(job_id)
        st.rerun(scope="app")
    elif (
        target["status"] in RESUMABLE_JOB_STATUSES
        or audio
        and audio["state"] in (InitialAudioState.BLOCKED, InitialAudioState.CANCELLED)
    ):
        if st.button(t("Resume"), key=f"{scope}resume-{job_id}"):
            from brofessor.application.worker import ensure_worker

            try:
                if audio and job["status"] == JobStatus.SUCCEEDED:
                    initial_audio.resume(workspace, job_id)
                else:
                    workspace.resume(job_id)
                    ensure_worker(workspace)
                st.rerun(scope="app")
            except (OSError, ValueError) as error:
                st.error(t("Could not submit the job: {error}", error=error))
