"""Stable browser/session keys and the string boundary of Streamlit widgets."""

from enum import StrEnum
from pathlib import Path
from typing import Final

UI_PREFIX: Final = "ui:"
EDITOR_PREFIX: Final = "editor:"
NOTE_PREFIX: Final = "note:"
SETTINGS_PREFIX: Final = "settings:"
SECTION_DEFAULT_PREFIX: Final = "ui:section-default:"
NAVIGATION_KEY: Final = "navigation"

NAVIGATE_KEY: Final = "ui:navigate"
PROJECT_DIALOG_KEY: Final = "ui:project-dialog"
SETTINGS_OPEN_KEY: Final = "ui:settings-open"
DELETE_KEY: Final = "ui:delete"
PROJECT_PATH_KEY: Final = "ui:project-path"
SOURCE_DIALOG_KEY: Final = "ui:source-dialog"
NOTICE_KEY: Final = "ui:notice"
RECENT_WARNING_KEY: Final = "ui:recent-warning"
SETTINGS_SPEECH_KEY: Final = "ui:settings-speech"
PROJECT_INPUT_RESET_KEY: Final = "ui:project-input-reset"
CHOOSE_TASK_PROJECT_KEY: Final = "ui:choose-task-project"
WORKSPACE_ARGUMENT_OPENED_KEY: Final = "ui:workspace-argument-opened"
COMPOSER_MIGRATED_KEY: Final = "ui:composer-migrated"
MAINTENANCE_STATUS_KEY: Final = "ui:maintenance-status"
GLOBAL_TASK_QUERY_KEY: Final = "ui:global-task-query"

SETTINGS_SECTION_KEY: Final = "settings:section"
SETTINGS_PROVIDER_KEY: Final = "settings:provider"
SETTINGS_MODEL_KEY: Final = "settings:model"
SETTINGS_ADDRESS_KEY: Final = "settings:address"
OLLAMA_MODELS_KEY: Final = "settings:ollama-models"
OLLAMA_MODELS_ADDRESS_KEY: Final = "settings:ollama-models-address"


class Page(StrEnum):
    RESULTS = "results"
    SOURCES = "sources"
    NOTES = "notes"
    PROJECTS = "projects"
    SEARCH = "search"
    NEW_PROJECT = "new-project"
    CATALOGUE = "catalogue"


class SettingsSection(StrEnum):
    GENERAL = "general"
    MODELS = "models"
    STORAGE = "storage"


class ProjectKey(StrEnum):
    CREATING = "creating"
    CATALOGUE = "catalogue"
    SELECTED_JOB = "selected-job"
    SELECTED_NOTE = "selected-note"
    RENDER = "render"
    NEXT_RENDER = "next-render"
    ACTIVE_WORK = "active-work"
    STATUS = "status"
    SOURCE_IMPORT = "source-import"
    NEW_MODELS = "new-models"
    RESULT_PAGE = "result-page"
    TASK_CRITERIA = "task-criteria"
    RELATED = "related"
    FIND_RESULT = "find-result"
    FILTER = "filter"
    RENAME = "rename"
    OPERATION = "operation"
    NEW = "new"
    SOURCE_BROWSER = "source-browser"
    SOURCE_FRAGMENT = "source-fragment"
    TASK_MODELS = "task-models"
    REGENERATE = "regenerate"


class EditorSuffix(StrEnum):
    TEXT = ":text"
    JSON = ":json"
    EDITING = ":editing"
    ITEM_SELECTED = ":item:selected"
    REVISION = ":revision"
    COPY = ":copy"
    HISTORY = ":history"
    RECOVERED = ":recovered"
    PROTECTION_ERROR = ":protection-error"
    FOLDER = ":folder"
    ERROR = ":error"
    TITLE = ":title"
    CITATIONS = ":citations"
    FOLLOW_UP = ":follow-up"
    ORIGIN_COPY = ":origin-copy"
    EPOCH = ":epoch"
    TERMS = ":terms"
    SAVED = ":saved"
    PREVIEW_PAGE = ":preview-page"
    RECOVERY_OWNER = ":recovery-owner"
    ORIGINAL = ":original"
    SAVED_DATA = ":saved-data"
    ROWS = ":rows"
    BASELINE = ":baseline"
    SOURCES = ":sources"
    LANGUAGE = ":language"
    SHOWING_HISTORY = ":showing-history"
    FIELD_PREFIX = ":field:"
    EPISODE_PREFIX = ":episode:"
    TOPIC_PREFIX = ":topic:"
    TERM_PREFIX = ":term:"


def project_key(path: str | Path, field: ProjectKey, *parts: object) -> str:
    return UI_PREFIX + ":".join(str(value) for value in (path, field, *parts))


def note_key(path: str | Path, note_id: str) -> str:
    return f"{NOTE_PREFIX}{path}:{note_id}"


def widget_value(value):
    """Keep persisted widget values independent of Python enum classes across reruns."""
    if isinstance(value, StrEnum):
        return str(value)
    return value


def widget_options(values):
    return [widget_value(value) for value in values]
