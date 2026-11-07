"""Web dialogs: delete."""

import streamlit as st

from brofessor.application import projects, tasks
from brofessor.infrastructure.storage.workspace import Workspace
from brofessor.interfaces.web.components import layout as ui_layout
from brofessor.interfaces.web.state_keys import DELETE_KEY, NAVIGATE_KEY, PROJECT_PATH_KEY


def delete_dialog(context):
    t = context.t
    st.dialog(
        t("Delete project" if st.session_state[DELETE_KEY]["kind"] == "project" else "Delete task"),
        width="small",
        on_dismiss=lambda: st.session_state.pop(DELETE_KEY, None),
    )(_delete_dialog)(context)


def _delete_dialog(context):
    t = context.t
    pending = st.session_state[DELETE_KEY]
    project = pending["kind"] == "project"
    ui_layout.heading(pending["name"])
    st.caption(
        t(
            "The project will disappear from navigation. Its folder and all files stay on disk. Restore it in All projects → Deleted projects."
            if project
            else "The whole task, including related runs, will move to Deleted tasks. Sources, saved versions, files and recovery copies are kept."
        )
    )
    confirm, cancel = st.columns(2)
    if confirm.button(t("Delete"), key="delete:confirm", type="primary", width="stretch"):
        try:
            if project:
                projects.delete(pending["path"])
                if st.session_state.get(PROJECT_PATH_KEY) == pending["path"]:
                    st.session_state[PROJECT_PATH_KEY] = None
                st.session_state[NAVIGATE_KEY] = "projects"
            else:
                tasks.delete(Workspace(pending["path"]), pending["job_id"])
                prefix = f"ui:{pending['path']}:"
                st.session_state[prefix + "selected-job"] = None
                st.session_state[prefix + "catalogue"] = True
                st.session_state[prefix + "creating"] = False
            st.session_state.pop(DELETE_KEY, None)
            st.rerun()
        except (OSError, ValueError) as error:
            st.error(t(str(error)))
    if cancel.button(t("Cancel"), key="delete:cancel", width="stretch"):
        st.session_state.pop(DELETE_KEY, None)
        st.rerun()
