"""Web pages: projects."""

import streamlit as st

from brofessor.application import projects
from brofessor.interfaces.web.components import layout as ui_layout
from brofessor.interfaces.web.state_keys import CHOOSE_TASK_PROJECT_KEY, PROJECT_DIALOG_KEY, Page


def all_projects(context):
    t = context.t
    catalog = context.catalog
    ui_layout.heading(t("Projects"), level=1)
    if st.session_state.pop(CHOOSE_TASK_PROJECT_KEY, False):
        st.info(t("Choose a project for the new task."))
    for project in catalog:
        label, action = st.columns([4, 1])
        with label:
            ui_layout.heading(project["name"], level=2)
        label.caption(project["path"])
        action.button(
            t("Open project"),
            key=f"all-project:{project['path']}",
            on_click=context.open_project_folder,
            args=(project["path"],),
            disabled=not project["available"],
        )
        if not project["available"]:
            st.caption(t("Project folder unavailable"))
        with label.popover(t("Project actions")):
            st.button(
                t("Delete project"),
                key=f"delete-project:{project['path']}",
                on_click=context.request_delete,
                args=("project", project["path"], project["name"]),
            )
    if not catalog:
        st.info(t("Create a project or open an existing folder to begin."))
    create, existing = st.columns(2)
    create.button(
        t("Create project"),
        key="projects-create",
        on_click=context.navigate,
        args=(Page.NEW_PROJECT,),
    )
    if existing.button(t("Open existing project"), key="projects-open"):
        st.session_state["project_action"] = "open"
        st.session_state[PROJECT_DIALOG_KEY] = True
        st.rerun()
    removed = projects.deleted_projects()
    if removed:
        with st.expander(t("Deleted projects")):
            for project in removed:
                label, action = st.columns([4, 1], vertical_alignment="center")
                label.write(project["name"])
                label.caption(project["path"])
                action.button(
                    t("Restore"),
                    key=f"restore-project:{project['path']}",
                    on_click=context.restore_project,
                    args=(project["path"],),
                )
