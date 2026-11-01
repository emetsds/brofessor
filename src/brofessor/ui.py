"""Local Streamlit client. Durable work never lives in session_state."""

import argparse
import hashlib
import json
import tempfile
import uuid
from functools import partial
from pathlib import Path

import streamlit as st

from brofessor import service
from brofessor import ui_language
from brofessor.executors import DEFAULT_OLLAMA_PORT
from brofessor.workspace import Workspace

parser = argparse.ArgumentParser(add_help=False)
parser.add_argument("--workspace", default=".brofessor/workspace")
parser.add_argument("--ollama-port", type=int, default=DEFAULT_OLLAMA_PORT)
args, _ = parser.parse_known_args()
st.set_page_config(page_title="brofessor", page_icon="🎙", layout="wide")
st.title("brofessor")

if "ui_language" not in st.session_state:
    st.session_state.ui_language = ui_language.load_language(getattr(st.context, "locale", None))


def remember_language():
    # Keep the selected code when Streamlit replaces translated option labels.
    if "kind" in st.session_state:
        st.session_state.kind = st.session_state.kind
    try:
        ui_language.save_language(st.session_state.ui_language)
        st.session_state.pop("language_save_failed", None)
    except OSError:
        st.session_state.language_save_failed = True


with st.sidebar:
    interface_language = st.selectbox(
        "Язык интерфейса / Interface language",
        list(ui_language.LANGUAGE_NAMES),
        format_func=ui_language.LANGUAGE_NAMES.__getitem__,
        key="ui_language",
        on_change=remember_language,
    )
    t = partial(ui_language.text, interface_language)
    if st.session_state.get("language_save_failed"):
        st.warning(
            t("Could not remember your language choice. It will apply only to this session.")
        )
    workspace_path = st.text_input(t("Workspace"), args.workspace, key="workspace_path")
    provider = st.selectbox(t("Provider"), ["codex", "claude", "ollama"], key="provider")
    model = st.text_input(t("Model (leave empty for the provider default)"), key="model") or None
    ollama_port = st.session_state.get("selected_ollama_port", args.ollama_port)
    if provider == "ollama":
        ollama_port = st.number_input(
            t("Ollama port"),
            min_value=1,
            max_value=65535,
            value=ollama_port,
            step=1,
            key="ollama_port",
            help=t("Port of the running Ollama server on 127.0.0.1."),
        )
        # Hidden widgets lose their state; preserve the port when switching providers.
        st.session_state["selected_ollama_port"] = ollama_port
    st.caption(
        t("Codex and Claude send selected text to their providers. Ollama and speech run locally.")
    )
    if st.button(t("Check connection"), key="check_connection"):
        from brofessor.executors import doctor

        try:
            diagnosis = doctor(provider, model, ollama_port=ollama_port)
            if diagnosis["available"]:
                st.success(t("Connection ready"))
            else:
                st.error(t("Connection unavailable"))
            st.json(diagnosis)
        except Exception as error:
            st.error(t("Could not check the connection: {error}", error=error))

try:
    workspace = Workspace(workspace_path)
except Exception as error:
    st.error(t("Could not open the workspace: {error}", error=error))
    st.stop()

tab_labels = [t("Sources"), t("Create"), t("Jobs and results")]


def remember_tab():
    st.session_state.active_tab_index = tab_labels.index(st.session_state.active_tab)


sources_tab, create_tab, results_tab = st.tabs(
    tab_labels,
    key="active_tab",
    on_change=remember_tab,
    default=tab_labels[st.session_state.get("active_tab_index", 0)],
)

with sources_tab:
    uploaded = st.file_uploader(
        t("Add materials"),
        type=["pdf", "epub", "md", "txt"],
        accept_multiple_files=True,
        max_upload_size=100,
        key="uploaded_sources",
    )
    if st.button(t("Import"), disabled=not uploaded, key="import_sources"):
        for upload in uploaded:
            try:
                with tempfile.TemporaryDirectory() as folder:
                    path = Path(folder) / Path(upload.name).name
                    path.write_bytes(upload.getvalue())
                    workspace.add_source(path)
                st.success(t("Added {name}", name=upload.name))
            except Exception as error:
                st.error(t("Could not import {name}: {error}", name=upload.name, error=error))
    for source in workspace.sources():
        with st.expander(source["name"]):
            units = workspace.units([source["id"]])
            ready = sum(u["status"] == "ready" for u in units)
            st.caption(
                t(
                    "Readable fragments: {ready}/{total} · {id}",
                    ready=ready,
                    total=len(units),
                    id=source["id"],
                )
            )
            for unit in units:
                st.markdown(f"**{unit['locator']}** · `{unit['id']}`")
                st.text(unit["text"] or t("No text extracted"))
    query = st.text_input(t("Search source text"), key="source_query")
    if query:
        from brofessor.sources import search_units

        for unit in search_units(workspace.units(), query):
            st.write(f"{unit['locator']} · {unit['id']}")
            st.text(unit["text"])

with create_tab:
    all_sources = workspace.sources()
    names = {s["id"]: s["name"] for s in all_sources}
    selected = st.multiselect(
        t("Sources"),
        list(names),
        default=list(names),
        format_func=lambda value: names[value],
        key="source_ids",
    )
    if "request_key" not in st.session_state:
        st.session_state.request_key = uuid.uuid4().hex
    # Ordinary widgets send edits immediately, including before a language switch.
    with st.container(border=True):
        kinds = {
            "podcast": t("Podcast"),
            "slides": t("Presentation"),
            "ask": t("Answer a question"),
        }
        kind = st.selectbox(t("Output"), list(kinds), format_func=kinds.__getitem__, key="kind")
        focus = st.text_area(t("Focus / question"), key="focus")
        language = st.selectbox(
            t("Output language"),
            list(ui_language.LANGUAGE_NAMES),
            format_func=ui_language.LANGUAGE_NAMES.__getitem__,
            key="output_language",
        )
        minutes = st.select_slider(
            t("Podcast duration, minutes"), [3, 20, 30, 45, 60], value=20, key="minutes"
        )
        st.caption(
            t("3 minutes is a short script and voice preview. Full episodes: 20–60 minutes.")
        )
        slide_count = st.number_input(t("Number of slides"), 1, 40, 8, key="slide_count")
        submitted = st.button(t("Prepare"), disabled=not selected, key="prepare")
    if submitted:
        try:
            fingerprint = hashlib.sha256(
                json.dumps(
                    [
                        str(workspace.path),
                        kind,
                        selected,
                        focus,
                        language,
                        provider,
                        model,
                        ollama_port if provider == "ollama" else None,
                        minutes,
                        slide_count,
                    ],
                    ensure_ascii=False,
                ).encode()
            ).hexdigest()
            if st.session_state.get("request_fingerprint") != fingerprint:
                st.session_state.request_key = uuid.uuid4().hex
                st.session_state.request_fingerprint = fingerprint
            job = service.submit(
                workspace,
                kind,
                source_ids=selected,
                focus=focus,
                language=language,
                provider=provider,
                model=model,
                ollama_port=ollama_port,
                minutes=minutes,
                slide_count=slide_count,
                request_key=st.session_state.request_key,
            )
            st.success(t("Job {id} submitted. Find the result in Jobs and results.", id=job["id"]))
        except Exception as error:
            st.error(t("Could not submit the job: {error}", error=error))


@st.fragment(run_every=2)
def results():
    from brofessor.worker import is_running

    running = is_running(workspace)
    st.caption(
        t("Background processing is running" if running else "Background processing is stopped")
    )
    jobs = workspace.jobs()
    if not running and any(job["status"] in ("queued", "running") for job in jobs):
        if st.button(t("Restore processing"), key="restore_processing"):
            from brofessor.worker import ensure_worker

            ensure_worker(workspace)
            st.rerun()
    if not jobs:
        st.info(t("Scripts, answers, audio, and presentations will appear here."))
    for job in jobs:
        kind_name = {
            "ask": "Answer",
            "podcast": "Podcast script",
            "slides": "Slide outline",
            "render_podcast": "Audio",
            "render_slides": "Presentation",
        }.get(job["kind"], job["kind"])
        status_name = {
            "queued": "Queued",
            "running": "Running",
            "succeeded": "Ready",
            "failed": "Failed",
            "cancelled": "Cancelled",
            "interrupted": "Interrupted",
        }[job["status"]]
        with st.expander(f"{t(kind_name)} · {t(status_name)} · {job['id']}"):
            progress = job["progress"]
            stage = {
                "reading": "Reading sources",
                "script": "Writing script",
                "speech": "Generating speech",
                "draft_ready": "Draft ready",
            }.get(progress.get("stage"))
            if stage:
                st.caption(t(stage))
            if progress.get("total"):
                completed, total = progress.get("completed", 0), progress["total"]
                st.progress(
                    min(completed / total, 1.0),
                    text=t("Completed {completed} of {total}", completed=completed, total=total),
                )
            if job["error"]:
                st.error(t("Details: {error}", error=job["error"]))
            if job["status"] in ("queued", "running"):
                if st.button(t("Cancel"), key=f"cancel-{job['id']}"):
                    workspace.cancel(job["id"])
                    st.rerun()
            elif job["status"] in ("failed", "interrupted", "cancelled"):
                if st.button(t("Resume"), key=f"resume-{job['id']}"):
                    from brofessor.worker import ensure_worker

                    workspace.resume(job["id"])
                    ensure_worker(workspace)
                    st.rerun()
            draft = workspace.draft(job["id"])
            if draft:
                if job["kind"] == "ask":
                    st.write(draft["data"]["answer"])
                    for citation in draft["data"]["citations"]:
                        unit = next(
                            (
                                u
                                for u in workspace.units(job["params"]["source_ids"])
                                if u["id"] == citation
                            ),
                            None,
                        )
                        if unit:
                            st.caption(f"{citation} · {unit['locator']}")
                            st.text(unit["text"])
                editor_key = f"editor:{workspace.path}:{job['id']}"
                buffer_key = editor_key + ":text"
                if editor_key not in st.session_state:
                    st.session_state[editor_key] = draft["revision"]
                    st.session_state[buffer_key] = json.dumps(
                        draft["data"], ensure_ascii=False, indent=2
                    )
                loaded_revision = st.session_state[editor_key]
                if loaded_revision != draft["revision"]:
                    st.warning(
                        t(
                            "A newer revision is available. Your unsaved edits are still in the editor."
                        )
                    )
                st.caption(
                    t(
                        "Editing revision: {loaded}. Latest: {latest}",
                        loaded=loaded_revision,
                        latest=draft["revision"],
                    )
                )
                text = st.text_area(t("Content (JSON)"), height=260, key=buffer_key)

                def reload_draft(job_id=job["id"], revision_key=editor_key, text_key=buffer_key):
                    current = workspace.draft(job_id)
                    st.session_state[revision_key] = current["revision"]
                    st.session_state[text_key] = json.dumps(
                        current["data"], ensure_ascii=False, indent=2
                    )

                st.button(
                    t("Load latest revision"), key=f"reload-{job['id']}", on_click=reload_draft
                )
                if st.button(t("Save edits"), key=f"save-{job['id']}"):
                    try:
                        saved = service.edit_draft(
                            workspace, job["id"], json.loads(text), loaded_revision
                        )
                        st.session_state[editor_key] = saved["revision"]
                        st.rerun()
                    except (ValueError, TypeError) as error:
                        st.error(t("Could not save edits: {error}", error=error))
                if job["kind"] in ("podcast", "slides"):
                    label = t("Generate audio" if job["kind"] == "podcast" else "Build PPTX")
                    if st.button(label, key=f"render-{job['id']}"):
                        service.render(
                            workspace,
                            job["id"],
                            request_key=f"render:{job['id']}:{draft['revision']}",
                        )
                        st.rerun()
            for artifact in workspace.artifacts(job["id"]):
                path = service.artifact_path(workspace, artifact["path"])
                if not path.exists():
                    st.error(t("File is missing: {name}", name=path.name))
                    continue
                if artifact["kind"] == "audio":
                    st.audio(str(path))
                metadata = artifact["metadata"]
                if metadata.get("duration_matches") is False:
                    actual = round(metadata["duration_seconds"])
                    target = round(metadata["requested_seconds"])
                    st.warning(
                        t(
                            "Actual duration {actual}, target {target}. The difference exceeds 10%. Edit the script before rendering again.",
                            actual=f"{actual // 60}:{actual % 60:02d}",
                            target=f"{target // 60}:{target % 60:02d}",
                        )
                    )
                elif metadata.get("warning"):
                    st.warning(t("Audio warning: {warning}", warning=metadata["warning"]))
                st.download_button(
                    t("Download {name}", name=path.name),
                    path.read_bytes(),
                    file_name=path.name,
                    key=f"download-{job['id']}-{path.name}",
                )


with results_tab:
    results()
