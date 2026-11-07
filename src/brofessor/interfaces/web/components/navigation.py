"""Project folders and task navigation. This module never submits model work."""

import hashlib
from datetime import datetime
from importlib.resources import files
from typing import Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import streamlit as st

from brofessor.application import tasks
from brofessor.contracts.jobs import JobKind, JobStatus, TaskStatus
from brofessor.infrastructure.storage.workspace import Workspace
from brofessor.interfaces.web.components import layout as ui_layout
from brofessor.interfaces.web.state_keys import Page, ProjectKey, project_key

SIDEBAR_SHARE_STORAGE_KEY: Final = "brofessor:sidebar-project-share"

TASK_LABELS = {
    JobKind.ASK: "Answer",
    JobKind.REPORT: "Written report",
    JobKind.STUDY: "Practice questions",
    JobKind.AUDIOBOOK: "Audiobook",
    JobKind.PODCAST: "Podcast",
    JobKind.SLIDES: "Presentation",
    JobKind.PODCAST_SERIES: "Podcast series",
    JobKind.TRANSLATE_EPUB: "Book translation",
    JobKind.TRANSLATE_PDF: "PDF translation",
}
TASK_ICONS = {
    JobKind.ASK: ":material/chat_bubble_outline:",
    JobKind.REPORT: ":material/article:",
    JobKind.STUDY: ":material/quiz:",
    JobKind.AUDIOBOOK: ":material/headphones:",
    JobKind.PODCAST: ":material/mic:",
    JobKind.SLIDES: ":material/co_present:",
    JobKind.PODCAST_SERIES: ":material/queue_music:",
    JobKind.TRANSLATE_EPUB: ":material/translate:",
    JobKind.TRANSLATE_PDF: ":material/translate:",
}

splitter = st.components.v2.component(
    "brofessor_sidebar_splitter",
    html='<div class="brofessor-sidebar-divider" role="separator" tabindex="0" aria-orientation="horizontal"></div>',
    js=files("brofessor.interfaces.web")
    .joinpath("assets", "sidebar_splitter.js")
    .read_text(encoding="utf-8"),
    isolate_styles=False,
)


def sidebar(workspace, catalog, t, *, selected_root, open_project, open_task, navigate, settings):
    with st.sidebar, st.container(key="sidebar-shell"):
        with st.container(key="app-brand"):
            brand, search, preferences = st.columns([4, 0.8, 0.8], vertical_alignment="center")
            brand.markdown("### brofessor")
            search.button(
                t("Search projects and tasks"),
                icon=":material/search:",
                key="find-task",
                help=t("Search projects and tasks"),
                on_click=navigate,
                args=(Page.SEARCH,),
                width="stretch",
                type="tertiary",
            )
            preferences.button(
                t("Settings"),
                icon=":material/settings:",
                key="settings-open",
                help=t("Settings"),
                on_click=settings,
                width="stretch",
                type="tertiary",
            )
        st.button(
            t("All projects"),
            icon=":material/folder_open:",
            key="all-projects",
            on_click=navigate,
            args=(Page.PROJECTS,),
            type="primary",
            width="stretch",
        )
        with st.container(key="sidebar-panels"):
            project_folders(workspace, catalog, t, open_project, open_task, navigate)
            with st.container(key="sidebar-splitter"):
                splitter(
                    data={
                        "label": t("Resize projects and recent tasks"),
                        "storage_key": SIDEBAR_SHARE_STORAGE_KEY,
                    },
                    key="sidebar:splitter",
                )
            recent_tasks(workspace, selected_root, t, open_task)


def project_folders(workspace, catalog, t, open_project, open_task, navigate):
    with st.container(key="sidebar-projects"):
        with st.container(key="sidebar-project-label"):
            label, add = st.columns([5, 1], vertical_alignment="center")
            with label:
                ui_layout.heading(t("Projects"))
            add.button(
                "+",
                key="new-project",
                help=t("Create project"),
                on_click=navigate,
                args=(Page.NEW_PROJECT,),
                width="stretch",
            )
        for project in catalog:
            active = workspace is not None and str(workspace.path) == project["path"]
            slug = hashlib.sha256(project["path"].encode()).hexdigest()[:12]
            with st.container(key=f"sidebar-project-row-{slug}"):
                with st.container(key=f"folder-heading-{'active-' if active else ''}{slug}"):
                    st.button(
                        project["name"],
                        icon=":material/folder:",
                        key=f"project:{project['path']}",
                        width="stretch",
                        on_click=open_project,
                        args=(project["path"],),
                        disabled=not project["available"],
                    )
                with st.expander(
                    t("Tasks in {name}", name=project["name"]),
                    expanded=active,
                    key=f"folder-toggle-{slug}",
                ):
                    if not project["available"]:
                        st.caption(t("Project folder unavailable"))
                    else:
                        try:
                            target = workspace if active else Workspace(project["path"])
                            items = tasks.list_tasks(target)
                        except (OSError, ValueError):
                            st.caption(t("Project folder unavailable"))
                            continue
                        with st.container(key=f"sidebar-project-children-{slug}"):
                            for item in items[:4]:
                                st.button(
                                    item["title"] or t("Task"),
                                    key=f"project-task:{project['path']}:{item['root_id']}",
                                    on_click=open_task,
                                    args=(project["path"], item["child_id"]),
                                    width="stretch",
                                    help=item["title"],
                                )
        if not catalog:
            st.caption(t("No projects yet."))


def recent_tasks(workspace, selected_root, t, open_task):
    with st.container(key="sidebar-recents"):
        with st.container(key="sidebar-recents-heading"):
            st.markdown("**:material/history: " + t("Recent tasks") + "**")
        try:
            recent = tasks.recent_tasks()
        except (OSError, ValueError) as error:
            st.warning(t("Could not read recent tasks: {error}", error=error))
            recent = []
        for item in recent:
            selected = (
                workspace is not None
                and str(workspace.path) == item["workspace_path"]
                and selected_root == item["root_id"]
                and not st.session_state.get(project_key(workspace.path, ProjectKey.CREATING))
                and not st.session_state.get(project_key(workspace.path, ProjectKey.CATALOGUE))
            )
            slug = hashlib.sha256((item["workspace_path"] + item["root_id"]).encode()).hexdigest()[
                :12
            ]
            with st.container(key="active-task" if selected else f"recent-task-{slug}"):
                st.button(
                    item["title"] or t("Task"),
                    key=f"recent:{slug}",
                    width="stretch",
                    on_click=open_task,
                    args=(item["workspace_path"], item["child_id"]),
                    disabled=not item["available"],
                    help=item["title"],
                )
                context = [
                    item["project"],
                    t(TASK_LABELS.get(item["kind"], "Task")),
                ]
                if item["available"] and item["status"] != JobStatus.SUCCEEDED:
                    context.append(
                        t(
                            {
                                JobStatus.SUCCEEDED: "Ready",
                                JobStatus.FAILED: "Failed",
                                JobStatus.QUEUED: "Queued",
                                JobStatus.RUNNING: "Running",
                                JobStatus.CANCELLED: "Cancelled",
                                JobStatus.INTERRUPTED: "Interrupted",
                                TaskStatus.BLOCKED: "Needs attention",
                            }[item["status"]]
                        )
                    )
                st.caption(" · ".join(context))
                if not item["available"]:
                    st.caption(t("Project folder unavailable"))
        if not recent:
            st.caption(t("Opened and newly created tasks will appear here."))


def task_row(item, t, *, key, open_task):
    try:
        zone = ZoneInfo(getattr(st.context, "timezone", None) or "UTC")
    except ZoneInfoNotFoundError:
        zone = ZoneInfo("UTC")
    with st.container(key=f"task-row-{item['root_id']}"):
        title, date = st.columns([5, 1.3], vertical_alignment="center")
        if title.button(
            item["match_title"] or t("Task"),
            key=key,
            icon=TASK_ICONS[item["kind"]],
            type="tertiary",
            width="stretch",
        ):
            open_task(item["match_id"])
            st.rerun(scope="app")
        date.caption(datetime.fromtimestamp(item["created"], zone).strftime("%d.%m.%Y"))
        context = t(TASK_LABELS[item["kind"]])
        if item["status"] != JobStatus.SUCCEEDED:
            context += " · " + t(
                {
                    JobStatus.QUEUED: "Queued",
                    JobStatus.RUNNING: "Running",
                    JobStatus.FAILED: "Failed",
                    JobStatus.CANCELLED: "Cancelled",
                    JobStatus.INTERRUPTED: "Interrupted",
                    TaskStatus.BLOCKED: "Needs attention",
                }[item["status"]]
            )
        if item["match_id"] != item["root_id"]:
            context += " · " + item["title"]
        st.caption(context)
