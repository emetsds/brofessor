"""Web dialogs: projects."""

import streamlit as st

from brofessor.application import projects
from brofessor.interfaces.web.state_keys import PROJECT_DIALOG_KEY, widget_options


def project_actions(context):
    t = context.t
    action = st.radio(
        t("Project"),
        widget_options(["create", "open"]),
        horizontal=True,
        key="project_action",
        format_func=lambda v: t("Create project" if v == "create" else "Open project"),
        label_visibility="collapsed",
        on_change=lambda: st.session_state.pop("project_error", None),
    )
    if action == "create":
        name = st.text_input(t("Project name"), key="project_name")
        st.text_input(t("Projects folder"), str(projects.directory()), key="projects_directory")
        if st.button(t("Create project"), key="create_project", disabled=not name.strip()):
            if context.create_project():
                st.rerun(scope="app")
    else:
        path = st.text_input(t("Existing project folder"), key="existing_project_path")
        if st.button(t("Open project"), key="open_project", disabled=not path.strip()):
            if context.open_project():
                st.rerun(scope="app")
    if st.session_state.get("project_error"):
        st.error(st.session_state.project_error)


def _project_dialog(context):
    project_actions(context)


def project_dialog(context):
    t = context.t
    st.dialog(
        t("Create or open a project"),
        width="medium",
        on_dismiss=lambda: st.session_state.update({PROJECT_DIALOG_KEY: False}),
    )(_project_dialog)(context)
