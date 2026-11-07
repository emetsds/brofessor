"""Preserve unsaved widget buffers across page and project navigation."""

import streamlit as st

from brofessor.interfaces.web.state_keys import (
    EDITOR_PREFIX,
    NAVIGATE_KEY,
    NAVIGATION_KEY,
    NOTE_PREFIX,
    PROJECT_INPUT_RESET_KEY,
    UI_PREFIX,
    EditorSuffix,
)


def preserve_buffers():
    # Keep unsaved draft buffers when their project's widgets are temporarily hidden.
    for state_key in list(st.session_state):
        if (
            state_key in ("minutes", "slide_count", "series_minutes", "episode_count")
            or state_key.startswith(UI_PREFIX)
            or (
                state_key.startswith(EDITOR_PREFIX)
                and (
                    state_key.endswith(
                        (
                            EditorSuffix.TEXT,
                            EditorSuffix.JSON,
                            EditorSuffix.PREVIEW_PAGE,
                            EditorSuffix.HISTORY,
                        )
                    )
                    or state_key.endswith((":preview-page:input", ":preview-page:error"))
                    or any(
                        part in state_key
                        for part in (
                            EditorSuffix.FIELD_PREFIX,
                            EditorSuffix.FOLLOW_UP,
                            ":item:",
                            EditorSuffix.EPISODE_PREFIX,
                            EditorSuffix.TOPIC_PREFIX,
                            EditorSuffix.TERM_PREFIX,
                        )
                    )
                )
            )
            or state_key
            in (
                "focus",
                "kind",
                "source_ids",
                "source_query",
                "search_source_ids",
                "provider",
                "model",
                "output_language",
                "ollama_address",
                NAVIGATION_KEY,
            )
            or (
                state_key.startswith(NOTE_PREFIX)
                and state_key.rsplit(":", 1)[-1] in ("title", "text", "citations", "revision")
            )
        ):
            st.session_state[state_key] = st.session_state[state_key]

    if reset_input := st.session_state.pop(PROJECT_INPUT_RESET_KEY, None):
        st.session_state[reset_input] = ""

    if NAVIGATE_KEY in st.session_state:
        st.session_state[NAVIGATION_KEY] = st.session_state.pop(NAVIGATE_KEY)
