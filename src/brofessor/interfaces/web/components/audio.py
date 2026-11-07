"""Web components: audio."""

import streamlit as st

from brofessor.application import service, tasks
from brofessor.contracts.jobs import InitialAudioState, JobKind, JobStatus, StageState
from brofessor.infrastructure.speech import catalogue as speech_models
from brofessor.infrastructure.speech.contracts import SpeechEngine
from brofessor.interfaces.web.state_keys import ProjectKey, project_key


def prepare_voice(context, voice):
    t = context.t
    from brofessor.application import maintenance

    spec = speech_models.get(voice)
    item = next((m for m in speech_models.list_models() if m["id"] == voice), None)
    if item is None:
        item = next((m for m in maintenance.speech_inventory() if m["id"] == spec["id"]), None)
        if item:
            item = {
                **item,
                "installed": speech_models.installed_path(spec) is not None,
                "download_bytes": speech_models.total_bytes(spec),
            }
    if item is None:
        st.error(t("Choose a supported speech model."))
        return False
    if not item["compatible"]:
        st.info(t("Local Qwen speech requires an Apple Silicon Mac."))
        return False
    runtime_ready = True
    if (
        spec.get("engine", SpeechEngine.QWEN_CUSTOM).startswith("qwen3")
        and not speech_models.qwen_runtime_available()
    ):
        st.info(t("Install local speech support in the project environment, then restart the UI."))
        st.code("uv sync --locked --python 3.12 --extra ui --extra speech", language="sh")
        runtime_ready = False
    if not item["installed"]:
        st.info(
            t(
                "This model's files are missing. Download and manage them in Settings → Models or Storage, then generate audio here."
            )
        )
        st.button(
            t("Open model settings"),
            key="voice-settings:" + speech_models.reference(spec),
            on_click=context.show_model_settings,
            args=(voice,),
        )
        return False
    return runtime_ready


def render_controls(
    context, job, draft, revision, saved, renders, displayed_id, voice=None, ready=True
):
    workspace = context.workspace
    t = context.t
    audio = job["kind"] in (JobKind.PODCAST, JobKind.AUDIOBOOK)
    if audio and voice is None:
        voice = tasks.models(workspace, job["id"])["data"]["speech_model"]
    current = next(
        (
            child
            for child in renders
            if child["params"]["revision"] == revision
            and (not audio or service.uses_current_voice(child, draft["data"]["language"], voice))
        ),
        None,
    )
    selected_key = project_key(workspace.path, ProjectKey.NEXT_RENDER, job["id"])
    if job["kind"] == JobKind.PODCAST:
        from brofessor.application.initial_audio import state as initial_state

        initial = initial_state(workspace, job["id"])
        if (
            initial
            and initial["revision"] in (None, revision)
            and initial["state"] in (InitialAudioState.PENDING, InitialAudioState.BLOCKED)
        ):
            st.button(t("Revoice"), key=f"render-{job['id']}", disabled=True)
            return
    if not saved:
        st.info(t("Save or load the displayed revision before rendering."))
    rebuild = (
        current
        and current["status"] == JobStatus.SUCCEEDED
        and not service.rendered_file(workspace, current)
    )
    if current and not rebuild:
        if current["id"] != displayed_id and st.button(
            t("Open output for revision {revision}", revision=revision),
            key=f"current-output-{job['id']}",
        ):
            st.session_state[selected_key] = current["id"]
            st.rerun()
        if current["status"] in (JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.SUCCEEDED):
            st.button(
                t("Revoice" if audio else "Build PPTX"), key=f"render-{job['id']}", disabled=True
            )
            return
        if st.button(
            t("Resume audio" if audio else "Resume"),
            key=f"render-{job['id']}",
            disabled=not saved or not ready,
        ):
            from brofessor.application.worker import ensure_worker

            workspace.resume(current["id"])
            ensure_worker(workspace)
            st.rerun()
        return
    if (
        job["kind"] == JobKind.PODCAST
        and initial
        and initial["state"] == StageState.CANCELLED
        and initial["revision"] in (None, revision)
    ):
        if st.button(t("Revoice"), key=f"render-{job['id']}", disabled=not saved or not ready):
            from brofessor.application.initial_audio import resume

            continuation = resume(workspace, job["id"])
            if continuation.get("render_id"):
                st.session_state[selected_key] = continuation["render_id"]
            st.rerun()
        return
    if rebuild:
        label = t("Rebuild missing file")
    elif renders:
        label = t("Revoice" if audio else "Update PPTX")
    else:
        label = t("Revoice" if audio else "Build PPTX")
    if st.button(label, key=f"render-{job['id']}", disabled=not saved or not ready, type="primary"):
        try:
            child = service.render(
                workspace,
                job["id"],
                revision=revision,
                request_key=f"replace-missing:{current['id']}" if rebuild else None,
                **({"model": voice} if audio else {}),
            )
            st.session_state[selected_key] = child["id"]
            st.rerun()
        except (OSError, ValueError) as error:
            st.error(t("Could not submit the job: {error}", error=error))
