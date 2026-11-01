"""Local Streamlit client. Durable work never lives in session_state."""

import argparse
import hashlib
import json
import tempfile
import uuid
from functools import partial
from pathlib import Path

import streamlit as st

from brofessor import projects, service, speech_models
from brofessor import ui_language
from brofessor.executors import DEFAULT_OLLAMA_PORT
from brofessor.workspace import Workspace

parser = argparse.ArgumentParser(add_help=False)
parser.add_argument("--workspace", default=None)
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


def activate_project(project):
    st.session_state.project_selector = project["path"]
    st.session_state.pop("source_ids", None)
    st.session_state.pop("search_source_ids", None)
    st.session_state.pop("project_error", None)


def select_project():
    try:
        activate_project(projects.use(st.session_state.project_selector))
    except (OSError, ValueError) as error:
        st.session_state.project_error = str(error)


def create_project():
    try:
        activate_project(
            projects.create(st.session_state.project_name, root=st.session_state.projects_directory)
        )
        st.session_state.project_name = ""
    except (OSError, ValueError) as error:
        st.session_state.project_error = str(error)


def open_project():
    try:
        activate_project(
            projects.open_project(
                st.session_state.existing_project_path,
                name=st.session_state.project_name.strip() or None,
            )
        )
        st.session_state.project_name = ""
        st.session_state.existing_project_path = ""
    except (OSError, ValueError) as error:
        st.session_state.project_error = str(error)


# Keep unsaved draft buffers when their project's widgets are temporarily hidden.
for state_key in list(st.session_state):
    if state_key.startswith("editor:"):
        st.session_state[state_key] = st.session_state[state_key]


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
    try:
        catalog = projects.list_projects()
        if args.workspace and str(Path(args.workspace).expanduser().resolve()) not in {
            item["path"] for item in catalog
        }:
            projects.open_project(Workspace(args.workspace).path)
            catalog = projects.list_projects()
        project_names = {item["path"]: item["name"] for item in catalog}
        current = projects.selected()
        selected_index = list(project_names).index(current["path"]) if current else None
        workspace_path = st.selectbox(
            t("Project"),
            list(project_names),
            index=selected_index,
            format_func=project_names.__getitem__,
            key="project_selector",
            on_change=select_project,
        )
        with st.expander(t("Create or open a project")):
            st.text_input(t("Project name"), key="project_name")
            st.text_input(t("Projects folder"), str(projects.directory()), key="projects_directory")
            st.button(t("Create project"), key="create_project", on_click=create_project)
            st.text_input(t("Existing project folder"), key="existing_project_path")
            st.button(t("Open project"), key="open_project", on_click=open_project)
        if st.session_state.get("project_error"):
            st.error(
                t("Could not open the workspace: {error}", error=st.session_state.project_error)
            )
    except (OSError, ValueError) as error:
        st.error(t("Could not open the workspace: {error}", error=error))
        st.stop()
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
    if not workspace_path:
        st.info(t("Create a project or open an existing project folder to get started."))
        st.stop()
    if not (Path(workspace_path) / "workspace.sqlite3").is_file():
        raise ValueError("The selected project folder is unavailable")
    workspace = Workspace(workspace_path)
except Exception as error:
    st.error(t("Could not open the workspace: {error}", error=error))
    st.stop()

tab_labels = [t("Sources"), t("Create"), t("Jobs and results")]


def remember_tab():
    st.session_state.active_tab_index = tab_labels.index(st.session_state.active_tab)


def choose_speech_model():
    try:
        speech_models.use(st.session_state.tts_model)
        st.session_state.pop("tts_error", None)
    except (OSError, ValueError) as error:
        st.session_state.tts_error = str(error)


@st.fragment(run_every=2)
def speech_status(choice):
    item = next(item for item in speech_models.list_models() if item["id"] == choice)
    st.caption(
        t(
            "Languages: {languages} · Download: {size} MB",
            languages=", ".join(item["languages"]),
            size=round(item["download_bytes"] / 1e6),
        )
    )
    st.caption(
        t(
            "Requirements: {requirements} · License: {license}",
            requirements=t(item["requirements"]),
            license=item["license"],
        )
    )
    if item.get("notes"):
        st.caption(t(item["notes"]))
    st.caption(t("Installed" if item["installed"] else "Not installed"))
    pending = next(
        (
            job
            for job in workspace.jobs()
            if job["kind"] == "download_model"
            and job["params"]["model"] == choice
            and job["status"] in ("queued", "running")
        ),
        None,
    )
    if pending is not None:
        done = pending["progress"].get("completed", 0)
        st.progress(min(done / item["download_bytes"], 1.0), text=t("Downloading model"))
        st.caption(t("See job {id} in Jobs and results", id=pending["id"]))
    if st.button(
        t("Download model"),
        key="download_tts_model",
        disabled=item["installed"] or pending is not None or not item["compatible"],
    ):
        try:
            service.download_model(workspace, choice)
            st.rerun()
        except (OSError, ValueError) as error:
            st.error(t("Could not submit the job: {error}", error=error))
    if st.session_state.get("tts_error"):
        st.error(t("Details: {error}", error=st.session_state.tts_error))


def speech_controls():
    models = speech_models.list_models()
    choices = {item["id"]: item for item in models}
    with st.expander(t("Speech models")):
        default = speech_models.selected()
        choice = st.selectbox(
            t("Voice model"),
            list(choices),
            index=list(choices).index(default),
            format_func=lambda value: choices[value]["name"],
            key="tts_model",
            on_change=choose_speech_model,
        )
        speech_status(choice)
        if choices[choice].get("requires_reference"):
            from brofessor import speech_references

            st.caption(
                t(
                    "Set one WAV sample and its exact transcript for each speaker. Samples stay on this computer."
                )
            )
            ref_language = st.selectbox(
                t("Voice sample language"),
                choices[choice]["languages"],
                key=f"reference_language:{choice}",
            )
            profiles = speech_references.list_references(ref_language)
            for role in ("host", "guest"):
                with st.expander(t("Voice sample: {role}", role=role)):
                    if role in profiles:
                        st.caption(t("Voice sample saved"))
                    audio = st.file_uploader(
                        t("PCM16 WAV, 2–20 seconds"),
                        type=["wav"],
                        max_upload_size=10,
                        key=f"reference_audio:{ref_language}:{role}",
                    )
                    transcript = st.text_area(
                        t("Exact transcript"),
                        value=profiles.get(role, {}).get("text", ""),
                        key=f"reference_text:{ref_language}:{role}",
                    )
                    if st.button(
                        t("Save voice sample"),
                        key=f"save_reference:{ref_language}:{role}",
                        disabled=(audio is None and role not in profiles) or not transcript.strip(),
                    ):
                        try:
                            speech_references.save(
                                role,
                                ref_language,
                                audio.getvalue()
                                if audio is not None
                                else Path(profiles[role]["path"]).read_bytes(),
                                transcript,
                            )
                            st.rerun()
                        except (OSError, ValueError) as error:
                            st.error(t("Could not save edits: {error}", error=error))


with st.sidebar:
    speech_controls()


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
    search_names = {s["id"]: s["name"] for s in workspace.sources()}
    search_sources = st.multiselect(
        t("Search in sources"),
        list(search_names),
        default=list(search_names),
        format_func=lambda key: search_names[key],
        key="search_source_ids",
    )
    st.caption(
        t(
            "Search matches original words. For a question in another language, use Answer a question."
        )
    )
    if query:
        found = service.search(workspace, query, source_ids=search_sources)
        if not found:
            st.info(t("No matching fragments."))
        for unit in found:
            st.write(f"{unit['source']} · {unit['locator']} · {unit['id']}")
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
            "podcast_series": t("Podcast series"),
            "slides": t("Presentation"),
            "ask": t("Answer a question"),
        }
        kind = st.selectbox(t("Output"), list(kinds), format_func=kinds.__getitem__, key="kind")
        if kind == "slides":
            st.caption(
                t(
                    "Ask for comparison tables or a sequence of steps in the focus when they help explain your sources."
                )
            )
        focus = st.text_area(t("Focus / question"), key="focus")
        language = st.selectbox(
            t("Output language"),
            list(ui_language.LANGUAGE_NAMES),
            format_func=ui_language.LANGUAGE_NAMES.__getitem__,
            key="output_language",
        )
        episode_count = 3
        if kind == "podcast_series":
            episode_count = st.number_input(t("Number of episodes"), 2, 12, 3, key="episode_count")
            minutes = st.select_slider(
                t("Episode duration, minutes"), [20, 30, 45, 60], value=20, key="series_minutes"
            )
            st.caption(t("Review the series plan, then prepare its episodes individually."))
        else:
            minutes = st.select_slider(
                t("Podcast duration, minutes"), [3, 20, 30, 45, 60], value=20, key="minutes"
            )
            st.caption(
                t("3 minutes is a short script and voice preview. Full episodes: 20–60 minutes.")
            )
        slide_count = (
            8
            if kind == "podcast_series"
            else st.number_input(t("Number of slides"), 1, 40, 8, key="slide_count")
        )
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
                        episode_count if kind == "podcast_series" else None,
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
                episode_count=episode_count,
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
            "podcast_series": "Podcast series",
            "slides": "Slide outline",
            "render_podcast": "Audio",
            "render_slides": "Presentation",
            "download_model": "TTS model download",
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
            if job["params"].get("series"):
                reference = job["params"]["series"]
                st.caption(
                    t(
                        "Series {id} · Plan revision {revision} · Episode {number}",
                        id=reference["job_id"],
                        revision=reference["revision"],
                        number=reference["episode"],
                    )
                )
            if job["kind"] == "render_podcast":
                voice_reference = job["params"].get("model") or speech_models.DEFAULT_ID
                try:
                    voice_name = speech_models.get(voice_reference)["name"]
                except ValueError:
                    voice_name = voice_reference
                voice_name = job["params"].get("model_spec", {}).get("name", voice_name)
                st.caption(t("Voice model: {model}", model=voice_name))
                rendered_draft = workspace.draft(
                    job["params"]["draft_job_id"], job["params"]["revision"]
                )
                if rendered_draft:
                    st.caption(
                        t(
                            "Output language: {output_language}",
                            output_language=ui_language.LANGUAGE_NAMES[
                                rendered_draft["data"]["language"]
                            ],
                        )
                    )
            progress = job["progress"]
            stage = {
                "reading": "Reading sources",
                "searching": "Searching original fragments",
                "outline": "Planning episode",
                "series_plan": "Planning series",
                "consolidating": "Consolidating reading notes",
                "script": "Writing script",
                "speech": "Generating speech",
                "draft_ready": "Draft ready",
                "downloading_model": "Downloading model",
            }.get(progress.get("stage"))
            if stage:
                st.caption(t(stage))
            if progress.get("total"):
                completed, total = progress.get("completed", 0), progress["total"]
                st.progress(
                    min(completed / total, 1.0),
                    text=t(
                        "Downloaded {completed} of {total} MB",
                        completed=round(completed / 1e6),
                        total=round(total / 1e6),
                    )
                    if job["kind"] == "download_model"
                    else t("Completed {completed} of {total}", completed=completed, total=total),
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
            coverage = service.coverage(workspace, job["id"])
            if coverage and coverage.get("units"):
                if coverage.get("mode") == "retrieved":
                    st.info(
                        t(
                            "This answer uses search-selected original fragments. Other fragments were not read; missing matches do not prove absence."
                        )
                    )
                if coverage.get("series"):
                    st.caption(t("Reading notes reused from the series plan."))
                st.caption(
                    t(
                        "Read {read} of {total} fragments · Excluded {excluded} · Cited {cited}",
                        read=coverage["count"],
                        total=len(coverage["units"]) - len(coverage["excluded"]),
                        excluded=len(coverage["excluded"]),
                        cited=coverage["cited_count"],
                    )
                )
                with st.expander(t("Reading coverage")):
                    if coverage.get("queries"):
                        st.caption(t("Search queries"))
                        for query_text in coverage["queries"]:
                            st.text(query_text)
                    st.caption(
                        t("Reading coverage does not guarantee that every fact is in the result.")
                    )
                    st.dataframe(
                        [
                            {
                                t("Reading status"): t(
                                    {
                                        "read": "Read",
                                        "pending": "Pending",
                                        "excluded": "Excluded",
                                        "not_selected": "Not selected by search",
                                    }[unit["status"]]
                                ),
                                t("Cited in result"): unit["cited"],
                                t("Source"): unit["source"],
                                t("Fragment"): unit["locator"],
                                "ID": unit["id"],
                                t("Exclusion reason"): t("No text extracted")
                                if unit["reason"] == "empty"
                                else t("Not selected by search")
                                if unit["reason"] == "not_selected_by_search"
                                else unit["reason"],
                            }
                            for unit in coverage["units"]
                        ],
                        hide_index=True,
                    )
            if draft:
                if job["kind"] == "podcast_series":
                    st.write(draft["data"]["title"])
                    st.caption(
                        t(
                            "Episodes: {count} · Target per episode: {minutes} min · Text provider: {provider}",
                            count=len(draft["data"]["episodes"]),
                            minutes=job["params"]["minutes"],
                            provider=job["params"]["provider"],
                        )
                    )
                    topics = {topic["id"]: topic for topic in draft["data"]["topics"]}
                    for number, episode in enumerate(draft["data"]["episodes"], 1):
                        st.write(f"{number}. {episode['title']}")
                        st.caption(" · ".join(topics[key]["title"] for key in episode["topic_ids"]))
                    if draft["data"]["terms"]:
                        with st.expander(t("Shared terminology")):
                            for term in draft["data"]["terms"]:
                                st.write(f"{term['term']}: {term['meaning']}")
                if job["kind"] == "ask":
                    st.caption(t("Question"))
                    st.write(job["params"]["focus"])
                    st.write(draft["data"]["answer"])
                    evidence_status = draft["data"].get("evidence_status", "supported")
                    if evidence_status == "conflicting_evidence":
                        st.warning(
                            t("Sources contain conflicting evidence. Review both positions below.")
                        )
                    elif evidence_status == "insufficient_evidence":
                        st.info(t("The available evidence is insufficient to establish an answer."))
                    if "quotes" not in draft["data"]:
                        st.caption(
                            t(
                                "This older answer has source references but no verified exact quotes."
                            )
                        )
                    for item in service.answer_evidence(workspace, job["id"], draft["revision"]):
                        st.caption(f"{item['source']} · {item['locator']} · {item['citation']}")
                        for quote in item["quotes"]:
                            st.text(quote)
                        with st.expander(t("Original fragment")):
                            st.text(item["text"])
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
                if job["kind"] == "podcast_series":
                    number = st.selectbox(
                        t("Episode"),
                        range(1, len(draft["data"]["episodes"]) + 1),
                        format_func=lambda n: f"{n}. {draft['data']['episodes'][n - 1]['title']}",
                        key=f"series-episode-{job['id']}",
                    )
                    try:
                        saved_plan = (
                            json.loads(text) == draft["data"]
                            and loaded_revision == draft["revision"]
                        )
                    except ValueError:
                        saved_plan = False
                    if not saved_plan:
                        st.caption(t("Save or load the latest plan before preparing an episode."))
                    if st.button(
                        t("Prepare episode"),
                        key=f"prepare-episode-{job['id']}",
                        disabled=not saved_plan or job["status"] != "succeeded",
                    ):
                        try:
                            service.series_episode(
                                workspace, job["id"], number, revision=draft["revision"]
                            )
                            st.rerun()
                        except (OSError, ValueError) as error:
                            st.error(t("Could not submit the job: {error}", error=error))
                if job["kind"] in ("podcast", "slides"):
                    label = t("Generate audio" if job["kind"] == "podcast" else "Build PPTX")
                    voice_model = st.session_state.get("tts_model", speech_models.selected())
                    missing_voice = (
                        job["kind"] == "podcast"
                        and speech_models.installed_path(voice_model) is None
                    )
                    unsupported_language = (
                        job["kind"] == "podcast"
                        and draft["data"]["language"]
                        not in speech_models.get(voice_model)["languages"]
                    )
                    if unsupported_language:
                        st.caption(
                            t("The selected voice model does not support this draft's language.")
                        )
                    if missing_voice:
                        st.caption(t("Download the selected voice model before generating audio."))
                    if st.button(
                        label,
                        key=f"render-{job['id']}",
                        disabled=missing_voice or unsupported_language,
                    ):
                        try:
                            service.render(
                                workspace,
                                job["id"],
                                model=voice_model if job["kind"] == "podcast" else None,
                                request_key=service.render_request_key(
                                    workspace, job["id"], voice_model
                                )
                                if job["kind"] == "podcast"
                                else f"render:{job['id']}:{draft['revision']}",
                            )
                            st.rerun()
                        except (OSError, ValueError) as error:
                            st.error(t("Could not submit the job: {error}", error=error))
            for artifact in workspace.artifacts(job["id"]):
                path = service.artifact_path(workspace, artifact["path"])
                if not path.exists():
                    st.error(t("File is missing: {name}", name=path.name))
                    continue
                if artifact["kind"] == "audio":
                    st.audio(str(path))
                metadata = artifact["metadata"]
                if "requested_seconds" in metadata:
                    actual = round(metadata["duration_seconds"])
                    target = round(metadata["requested_seconds"])
                    st.caption(
                        t(
                            "Audio duration {actual} · Target {target}",
                            actual=f"{actual // 60}:{actual % 60:02d}",
                            target=f"{target // 60}:{target % 60:02d}",
                        )
                    )
                if metadata.get("duration_matches") is False:
                    actual = round(metadata["duration_seconds"])
                    target = round(metadata["requested_seconds"])
                    st.warning(
                        t(
                            "Actual duration {actual}, target {target}. Edit the script to match the target within 10% and keep full episodes between 20 and 60 minutes.",
                            actual=f"{actual // 60}:{actual % 60:02d}",
                            target=f"{target // 60}:{target % 60:02d}",
                        )
                    )
                    if "suggested_word_count" in metadata:
                        st.caption(
                            t(
                                "Script: {words} words. At the measured pace, about {suggested} words would match the target. This is an editing estimate.",
                                words=metadata["script_words"],
                                suggested=metadata["suggested_word_count"],
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
