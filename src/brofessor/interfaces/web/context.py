"""Per-rerun UI state and navigation callbacks shared by screens.

Durable data and business rules remain in the application services.
"""

from dataclasses import dataclass
from typing import Callable

import streamlit as st

from brofessor.application import projects, tasks
from brofessor.contracts.text import TextProvider
from brofessor.infrastructure.storage.workspace import Workspace
from brofessor.interfaces.web.labels import JOB_LABELS
from brofessor.interfaces.web.state_keys import (
    CHOOSE_TASK_PROJECT_KEY,
    DELETE_KEY,
    NAVIGATE_KEY,
    NOTICE_KEY,
    PROJECT_DIALOG_KEY,
    PROJECT_INPUT_RESET_KEY,
    PROJECT_PATH_KEY,
    RECENT_WARNING_KEY,
    SETTINGS_OPEN_KEY,
    SETTINGS_SECTION_KEY,
    SETTINGS_SPEECH_KEY,
    SOURCE_DIALOG_KEY,
    Page,
    ProjectKey,
    SettingsSection,
    project_key,
    widget_value,
)


@dataclass
class WebContext:
    workspace: Workspace | None
    t: Callable
    catalog: list[dict]
    ollama_address: str | None = None

    def activate_project(self, project):
        st.session_state[PROJECT_PATH_KEY] = project["path"]
        st.session_state.pop("source_ids", None)
        st.session_state.pop("search_source_ids", None)
        st.session_state.pop("project_error", None)

    def create_project(self):
        t = self.t
        try:
            self.activate_project(
                projects.create(
                    st.session_state.project_name,
                    root=st.session_state.projects_directory.strip() or None,
                )
            )
            st.session_state[PROJECT_INPUT_RESET_KEY] = "project_name"
            st.session_state[PROJECT_DIALOG_KEY] = False
            st.session_state[NAVIGATE_KEY] = widget_value(Page.SOURCES)
            st.session_state[NOTICE_KEY] = t("Project created.")
            return True
        except (OSError, ValueError) as error:
            st.session_state.project_error = str(error)

    def open_project(self):
        try:
            self.activate_project(projects.open_project(st.session_state.existing_project_path))
            st.session_state[PROJECT_INPUT_RESET_KEY] = "existing_project_path"
            st.session_state[PROJECT_DIALOG_KEY] = False
            st.session_state[NAVIGATE_KEY] = widget_value(Page.RESULTS)
            return True
        except (OSError, ValueError) as error:
            st.session_state.project_error = str(error)

    def connection_notice(self, provider, address):
        t = self.t
        destination = {
            TextProvider.CODEX: "OpenAI (Codex)",
            TextProvider.CLAUDE: "Anthropic (Claude)",
            TextProvider.OLLAMA: f"Ollama ({address})",
        }
        st.caption(
            t("Selected source text goes to {destination}.", destination=destination[provider])
        )

    def show_source_dialog(self):
        st.session_state[SOURCE_DIALOG_KEY] = True
        st.session_state[PROJECT_DIALOG_KEY] = False
        st.session_state[SETTINGS_OPEN_KEY] = False

    def result_title(self, job):
        workspace = self.workspace
        t = self.t
        return tasks.title(workspace, job) or t(JOB_LABELS.get(job["kind"], "Task"))

    def open_result(self, job_id):
        workspace = self.workspace
        st.session_state[project_key(workspace.path, ProjectKey.SELECTED_JOB)] = job_id
        st.session_state[project_key(workspace.path, ProjectKey.CREATING)] = False
        st.session_state[project_key(workspace.path, ProjectKey.CATALOGUE)] = False
        st.session_state[NAVIGATE_KEY] = widget_value(Page.RESULTS)
        warning = tasks.record_open(workspace, job_id)
        if warning:
            st.session_state[RECENT_WARNING_KEY] = warning

    def show_settings(self):
        st.session_state[SETTINGS_OPEN_KEY] = True
        st.session_state[PROJECT_DIALOG_KEY] = False

    def show_model_settings(self, voice):
        self.show_settings()
        st.session_state[SETTINGS_SECTION_KEY] = widget_value(SettingsSection.STORAGE)
        st.session_state[SETTINGS_SPEECH_KEY] = voice

    def navigate(self, section):
        workspace = self.workspace
        if section == Page.NEW_PROJECT:
            st.session_state["project_action"] = "create"
            st.session_state[PROJECT_DIALOG_KEY] = True
            st.session_state[SETTINGS_OPEN_KEY] = False
        else:
            st.session_state[NAVIGATE_KEY] = widget_value(
                Page.RESULTS if section == Page.CATALOGUE else section
            )
            if workspace and section in (Page.RESULTS, Page.CATALOGUE):
                st.session_state[project_key(workspace.path, ProjectKey.CATALOGUE)] = True
                st.session_state[project_key(workspace.path, ProjectKey.CREATING)] = False

    def new_task(self):
        workspace = self.workspace
        if workspace:
            st.session_state[project_key(workspace.path, ProjectKey.CREATING)] = True
            st.session_state[project_key(workspace.path, ProjectKey.CATALOGUE)] = False
            st.session_state[NAVIGATE_KEY] = widget_value(Page.RESULTS)
        else:
            st.session_state[NAVIGATE_KEY] = widget_value(Page.PROJECTS)
            st.session_state[CHOOSE_TASK_PROJECT_KEY] = True

    def open_project_folder(self, path):
        try:
            self.activate_project(projects.use(path))
            st.session_state[project_key(path, ProjectKey.CATALOGUE)] = True
            st.session_state[project_key(path, ProjectKey.CREATING)] = False
            st.session_state[NAVIGATE_KEY] = widget_value(Page.RESULTS)
        except (OSError, ValueError) as error:
            st.session_state.project_error = str(error)

    def open_project_task(self, path, job_id):
        try:
            project = projects.open_project(path)
            target = Workspace(project["path"])
            target.job(job_id)
            self.activate_project(project)
            st.session_state[project_key(target.path, ProjectKey.SELECTED_JOB)] = job_id
            st.session_state[project_key(target.path, ProjectKey.CREATING)] = False
            st.session_state[project_key(target.path, ProjectKey.CATALOGUE)] = False
            st.session_state[NAVIGATE_KEY] = widget_value(Page.RESULTS)
            warning = tasks.record_open(target, job_id)
            if warning:
                st.session_state[RECENT_WARNING_KEY] = warning
        except (OSError, ValueError, KeyError) as error:
            st.session_state.project_error = str(error)

    def request_delete(self, kind, path, name, job_id=None):
        st.session_state[DELETE_KEY] = {"kind": kind, "path": path, "name": name, "job_id": job_id}
        st.session_state[SETTINGS_OPEN_KEY] = False
        st.session_state[PROJECT_DIALOG_KEY] = False

    def restore_task(self, job_id):
        workspace = self.workspace
        try:
            tasks.restore(workspace, job_id)
            self.open_project_task(str(workspace.path), job_id)
        except (OSError, ValueError) as error:
            st.session_state.project_error = str(error)

    def restore_project(self, path):
        try:
            self.activate_project(projects.restore(path))
            st.session_state[NAVIGATE_KEY] = widget_value(Page.RESULTS)
        except (OSError, ValueError) as error:
            st.session_state.project_error = str(error)
