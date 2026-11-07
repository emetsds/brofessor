"""Local Streamlit client. Durable work never lives in session_state."""

import argparse
from functools import partial
from pathlib import Path

import streamlit as st

from brofessor.application import projects, tasks
from brofessor.contracts.jobs import PRIMARY_JOB_KINDS
from brofessor.infrastructure.storage.workspace import DATABASE_FILENAME, Workspace
from brofessor.interfaces.web.components import language as ui_language
from brofessor.interfaces.web.components import layout as ui_layout
from brofessor.interfaces.web.components import navigation as ui_navigation
from brofessor.interfaces.web.components.jobs import active_work
from brofessor.interfaces.web.context import WebContext
from brofessor.interfaces.web.dialogs import settings as ui_settings
from brofessor.interfaces.web.dialogs.delete import delete_dialog
from brofessor.interfaces.web.dialogs.projects import project_dialog
from brofessor.interfaces.web.dialogs.sources import source_dialog
from brofessor.interfaces.web.pages.notes import notes
from brofessor.interfaces.web.pages.projects import all_projects
from brofessor.interfaces.web.pages.search import search_tasks
from brofessor.interfaces.web.pages.sources import sources
from brofessor.interfaces.web.pages.tasks import results
from brofessor.interfaces.web.state import preserve_buffers
from brofessor.interfaces.web.state_keys import (
    DELETE_KEY,
    NAVIGATION_KEY,
    NOTICE_KEY,
    PROJECT_DIALOG_KEY,
    PROJECT_PATH_KEY,
    RECENT_WARNING_KEY,
    SETTINGS_OPEN_KEY,
    SOURCE_DIALOG_KEY,
    WORKSPACE_ARGUMENT_OPENED_KEY,
    Page,
    ProjectKey,
    project_key,
    widget_value,
)

parser = argparse.ArgumentParser(add_help=False)
parser.add_argument("--workspace", default=None)
parser.add_argument("--ollama-address")
args, _ = parser.parse_known_args()
st.set_page_config(page_title="brofessor", page_icon="🎙", layout="wide")
ui_layout.apply()

if "ui_language" not in st.session_state:
    st.session_state.ui_language = ui_language.load_language(getattr(st.context, "locale", None))


preserve_buffers()

interface_language = st.session_state.ui_language
t = partial(ui_language.text, interface_language)
try:
    catalog = projects.list_projects()
    if (
        args.workspace
        and not st.session_state.get(WORKSPACE_ARGUMENT_OPENED_KEY)
        and str(Path(args.workspace).expanduser().resolve())
        not in {item["path"] for item in catalog}
    ):
        projects.open_project(args.workspace)
        catalog = projects.list_projects()
    st.session_state[WORKSPACE_ARGUMENT_OPENED_KEY] = True
    project_names = {item["path"]: item["name"] for item in catalog}
    if PROJECT_PATH_KEY not in st.session_state:
        current = projects.selected()
        st.session_state[PROJECT_PATH_KEY] = (
            str(Path(args.workspace).expanduser().resolve())
            if args.workspace
            else current["path"]
            if current
            else None
        )
    workspace_path = st.session_state[PROJECT_PATH_KEY]
except (OSError, ValueError) as error:
    st.error(t("Could not open the workspace: {error}", error=error))
    catalog, project_names, workspace_path = [], {}, None


workspace = None
if workspace_path:
    try:
        if not (Path(workspace_path) / DATABASE_FILENAME).is_file():
            raise ValueError("The selected project folder is unavailable")
        workspace = Workspace(workspace_path)
    except (OSError, ValueError) as error:
        st.error(t("Could not open the workspace: {error}", error=error))


context = WebContext(workspace, t, catalog, args.ollama_address)

sidebar_root = None
if workspace:
    known_jobs = {job["id"]: job for job in tasks.visible_jobs(workspace)}
    selection_key = project_key(workspace.path, ProjectKey.SELECTED_JOB)
    if st.session_state.get(selection_key) not in known_jobs:
        st.session_state[selection_key] = next(
            (
                job["id"]
                for job in known_jobs.values()
                if job["kind"] in PRIMARY_JOB_KINDS and tasks.root_job(job, known_jobs) == job["id"]
            ),
            None,
        )
    if st.session_state[selection_key]:
        sidebar_root = tasks.root_job(known_jobs[st.session_state[selection_key]], known_jobs)

ui_navigation.sidebar(
    workspace,
    catalog,
    t,
    selected_root=sidebar_root,
    open_project=context.open_project_folder,
    open_task=context.open_project_task,
    navigate=context.navigate,
    settings=context.show_settings,
)
if st.session_state.get(NAVIGATION_KEY) not in (
    Page.RESULTS,
    Page.SOURCES,
    Page.NOTES,
    Page.PROJECTS,
    Page.SEARCH,
):
    st.session_state[NAVIGATION_KEY] = widget_value(Page.RESULTS if workspace else Page.PROJECTS)
if st.session_state.get(RECENT_WARNING_KEY):
    st.caption(st.session_state.pop(RECENT_WARNING_KEY))
if st.session_state.get("project_error"):
    st.error(st.session_state.project_error)

if st.session_state.get(NOTICE_KEY):
    st.toast(st.session_state.pop(NOTICE_KEY))

if workspace and st.session_state[NAVIGATION_KEY] not in (Page.PROJECTS, Page.SEARCH):
    with st.container(key="project-header"):
        with st.container(horizontal=True, vertical_alignment="center", key="project-heading-row"):
            ui_layout.heading(project_names.get(str(workspace.path), workspace.path.name), level=1)
            st.button(
                t("New task"),
                icon=":material/add:",
                key="create_result",
                on_click=context.new_task,
                type="primary",
                width="content",
            )
            st.button(
                t("Add source"),
                key="header-add-source",
                icon=":material/add_circle_outline:",
                on_click=context.show_source_dialog,
                width="content",
            )
            st.button(
                t("Delete project"),
                key="delete-project",
                icon=":material/delete:",
                on_click=context.request_delete,
                args=(
                    "project",
                    str(workspace.path),
                    project_names.get(str(workspace.path), workspace.path.name),
                ),
            )
        st.caption(str(workspace.path))
        with st.container(horizontal=True, key="project-sections"):
            for section, label in (
                (Page.RESULTS, "Tasks"),
                (Page.SOURCES, "Sources"),
                (Page.NOTES, "Notes"),
            ):
                st.button(
                    t(label), key="nav:" + section, on_click=context.navigate, args=(section,)
                )
if workspace:
    active_work(context)

if (
    st.session_state[NAVIGATION_KEY] == Page.PROJECTS
    or not workspace
    and st.session_state[NAVIGATION_KEY] != Page.SEARCH
):
    all_projects(context)
elif st.session_state[NAVIGATION_KEY] == Page.SEARCH:
    search_tasks(context)
elif st.session_state[NAVIGATION_KEY] == Page.RESULTS:
    results(context)
elif st.session_state[NAVIGATION_KEY] == Page.SOURCES:
    sources(context)
else:
    notes(context)

if st.session_state.get(DELETE_KEY):
    delete_dialog(context)
elif st.session_state.get(SETTINGS_OPEN_KEY):
    ui_settings.dialog(t, language=interface_language, address_override=args.ollama_address)
elif st.session_state.get(PROJECT_DIALOG_KEY):
    project_dialog(context)
elif workspace and st.session_state.get(SOURCE_DIALOG_KEY):
    source_dialog(context)
