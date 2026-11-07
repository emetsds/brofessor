"""Web pages: notes."""

import streamlit as st

from brofessor.application import service
from brofessor.contracts.content import UnitStatus
from brofessor.interfaces.web.components import content as ui_content
from brofessor.interfaces.web.components import layout as ui_layout
from brofessor.interfaces.web.components.recovery import RECOVERY_DIRECTORY
from brofessor.interfaces.web.state_keys import (
    EditorSuffix,
    ProjectKey,
    note_key,
    project_key,
    widget_options,
)


def notes(context):
    workspace = context.workspace
    t = context.t
    from brofessor.interfaces.web.components import recovery as ui_recovery

    ui_layout.heading(t("Notes"), level=2)
    st.caption(
        t("Notes are your editable commentary. They are not automatically used as source evidence.")
    )
    note_names = {
        u["id"]: f"{s['name']} · {u['locator']}"
        for s in workspace.sources()
        for u in workspace.units([s["id"]])
        if u["status"] == UnitStatus.READY
    }
    new_key = note_key(workspace.path, "new")

    def create_note(prefix=new_key):
        try:
            note = service.save_note(
                workspace,
                {
                    "title": st.session_state.get(prefix + EditorSuffix.TITLE, ""),
                    "text": st.session_state.get(prefix + EditorSuffix.TEXT, ""),
                    "citations": st.session_state.get(prefix + EditorSuffix.CITATIONS, []),
                },
            )
            ui_recovery.forget(prefix)
            st.session_state[prefix + EditorSuffix.SAVED] = note["id"]
            st.session_state[prefix + EditorSuffix.TITLE] = ""
            st.session_state[prefix + EditorSuffix.TEXT] = ""
            st.session_state[prefix + EditorSuffix.CITATIONS] = []
            st.session_state.pop(prefix + EditorSuffix.ERROR, None)
        except (OSError, ValueError) as error:
            st.session_state[prefix + EditorSuffix.ERROR] = str(error)

    new_folder = workspace.path / RECOVERY_DIRECTORY / "note-new"
    with ui_layout.section(
        t("Create note"), new_key, expanded=bool(ui_recovery.copies(new_folder))
    ):
        changed = ui_recovery.note_buffer(
            workspace, new_key, "new", {"title": "", "text": "", "citations": []}, 0, t
        )
        st.text_input(t("Note title"), key=new_key + EditorSuffix.TITLE, on_change=changed)
        st.text_area(t("Note text"), key=new_key + EditorSuffix.TEXT, on_change=changed)
        st.multiselect(
            t("Source references"),
            widget_options(list(note_names)),
            format_func=note_names.__getitem__,
            key=new_key + EditorSuffix.CITATIONS,
            on_change=changed,
        )
        st.button(t("Create note"), key=new_key + ":create", on_click=create_note)
        if st.session_state.get(new_key + EditorSuffix.ERROR):
            st.error(
                t(
                    "Could not save note: {error}",
                    error=st.session_state[new_key + EditorSuffix.ERROR],
                )
            )
        if st.session_state.get(new_key + EditorSuffix.SAVED):
            st.success(t("Note saved: {id}.", id=st.session_state[new_key + EditorSuffix.SAVED]))
    all_notes = workspace.notes()
    selected_note = None
    if all_notes:
        st.divider()
        selected_note = st.selectbox(
            t("Notes"),
            widget_options([note["id"] for note in all_notes]),
            format_func=lambda value: next(
                note["data"]["title"] for note in all_notes if note["id"] == value
            ),
            key=project_key(workspace.path, ProjectKey.SELECTED_NOTE),
        )
    else:
        st.info(t("No notes yet. Save an answer or create a note."))
    for note in [note for note in all_notes if note["id"] == selected_note]:
        with st.container():
            ui_layout.heading(note["data"]["title"])
            prefix = note_key(workspace.path, note["id"])

            def reload_note(note_id=note["id"], key=prefix):
                ui_recovery.forget(key)
                current = workspace.note(note_id)
                st.session_state[key + EditorSuffix.REVISION] = current["revision"]
                for field in ("title", "text", "citations"):
                    st.session_state[key + ":" + field] = current["data"][field]

            changed = ui_recovery.note_buffer(
                workspace, prefix, note["id"], note["data"], note["revision"], t
            )
            loaded = st.session_state[prefix + EditorSuffix.REVISION]
            st.caption(
                t(
                    "Editing revision: {loaded}. Latest: {latest}",
                    loaded=loaded,
                    latest=note["revision"],
                )
            )
            st.caption(f"ID: {note['id']}")
            if loaded != note["revision"]:
                st.warning(
                    t("A newer revision is available. Your unsaved edits are still in the editor.")
                )
            if st.button(
                t(
                    "Read task"
                    if st.session_state.get(prefix + EditorSuffix.EDITING)
                    else "Edit note"
                ),
                key=prefix + ":edit",
            ):
                st.session_state[prefix + EditorSuffix.EDITING] = not st.session_state.get(
                    prefix + EditorSuffix.EDITING, False
                )
                st.rerun()
            note_mode = (
                "editing" if st.session_state.get(prefix + EditorSuffix.EDITING) else "reading"
            )
            with ui_layout.section(t("Note text"), prefix + ":body:" + note_mode, expanded=True):
                if not st.session_state.get(prefix + EditorSuffix.EDITING):
                    ui_content.prose(st.session_state[prefix + EditorSuffix.TEXT])
                else:
                    title = st.text_input(
                        t("Note title"), key=prefix + EditorSuffix.TITLE, on_change=changed
                    )
                    body = st.text_area(
                        t("Note text"),
                        height=220,
                        key=prefix + EditorSuffix.TEXT,
                        on_change=changed,
                    )
                    citations = st.multiselect(
                        t("Source references"),
                        widget_options(list(note_names)),
                        format_func=note_names.__getitem__,
                        key=prefix + EditorSuffix.CITATIONS,
                        on_change=changed,
                    )
            if st.session_state.get(prefix + EditorSuffix.EDITING):
                st.button(t("Load latest revision"), key=prefix + ":reload", on_click=reload_note)
                if st.button(t("Save note"), key=prefix + ":save"):
                    try:
                        saved = service.save_note(
                            workspace,
                            {"title": title, "text": body, "citations": citations},
                            note_id=note["id"],
                            expected_revision=loaded,
                        )
                        ui_recovery.forget(prefix)
                        st.session_state[prefix + EditorSuffix.REVISION] = saved["revision"]
                        st.rerun()
                    except (OSError, ValueError) as error:
                        st.error(t("Could not save note: {error}", error=error))
            with ui_layout.section(t("Revision history"), prefix + EditorSuffix.HISTORY):
                number = st.selectbox(
                    t("Saved revision"),
                    widget_options(range(1, note["revision"] + 1)),
                    index=note["revision"] - 1,
                    key=prefix + EditorSuffix.HISTORY,
                )
                previous = workspace.note(note["id"], number)
                st.text(previous["data"]["title"])
                st.text(previous["data"]["text"])
            evidence = service.note_evidence(workspace, note["id"])
            if evidence:
                with ui_layout.section(t("Source references"), prefix + EditorSuffix.SOURCES):
                    for item in evidence:
                        with st.expander(
                            f"{item['source']} · {item['locator']} · {item['citation']}"
                        ):
                            st.text(item["text"])
            if note["origin"]:
                origin = note["origin"]
                with st.expander(
                    t(
                        "Saved answer: {id} · revision {revision}",
                        id=origin["job_id"],
                        revision=origin["revision"],
                    )
                ):
                    parent = workspace.job(origin["job_id"])
                    st.text(parent["params"]["focus"])
                    st.text(workspace.draft(origin["job_id"], origin["revision"])["data"]["answer"])
                    for item in service.answer_evidence(
                        workspace, origin["job_id"], origin["revision"]
                    ):
                        st.caption(f"{item['source']} · {item['locator']}")
                        for quote in item["quotes"]:
                            st.text(quote)
