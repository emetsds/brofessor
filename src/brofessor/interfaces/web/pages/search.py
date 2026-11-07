"""Web pages: search."""

import hashlib

import streamlit as st

from brofessor.application import tasks
from brofessor.interfaces.web.components import layout as ui_layout
from brofessor.interfaces.web.components import navigation as ui_navigation
from brofessor.interfaces.web.state_keys import GLOBAL_TASK_QUERY_KEY


@st.fragment
def search_tasks(context):
    t = context.t
    catalog = context.catalog
    ui_layout.heading(t("Search projects and tasks"), level=1)
    query = st.text_input(
        t("Project or task name"),
        key=GLOBAL_TASK_QUERY_KEY,
        type="search",
        live="0ms",
        placeholder=t("Search by word prefix"),
    )
    if not query.strip():
        st.caption(t("Search project names, task names and original requests."))
        return
    groups = tasks.search_projects(catalog, query)
    with st.container(key="task-catalogue"):
        for group in groups:
            project = group["project"]
            slug = hashlib.sha256(project["path"].encode()).hexdigest()[:12]
            with st.container(key="search-project-heading-" + slug):
                if st.button(
                    project["name"],
                    icon=":material/folder:",
                    key=f"search-project:{project['path']}",
                    type="tertiary",
                    disabled=not project["available"],
                ):
                    context.open_project_folder(project["path"])
                    st.rerun(scope="app")
            for item in group["tasks"]:
                ui_navigation.task_row(
                    item,
                    t,
                    key=f"search-task:{project['path']}:{item['root_id']}",
                    open_task=lambda identifier, path=project["path"]: context.open_project_task(
                        path, identifier
                    ),
                )
    if not groups:
        st.info(t("No matching projects or tasks."))
