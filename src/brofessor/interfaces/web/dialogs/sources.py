"""Web dialogs: sources."""

import hashlib
import tempfile
from importlib.resources import files
from pathlib import Path

import streamlit as st

from brofessor.interfaces.web.state_keys import (
    NAVIGATE_KEY,
    Page,
    NOTICE_KEY,
    SOURCE_DIALOG_KEY,
    ProjectKey,
    project_key,
)

upload_labels = st.components.v2.component(
    "brofessor_upload_labels",
    html="",
    js=files("brofessor.interfaces.web")
    .joinpath("assets", "upload_labels.js")
    .read_text(encoding="utf-8"),
    isolate_styles=False,
)


def _source_dialog(context):
    workspace = context.workspace
    t = context.t
    from brofessor.features.sources import collections

    prefix = project_key(workspace.path, ProjectKey.SOURCE_IMPORT, "")
    mode = st.radio(
        t("Source type"),
        ["files", "folder"],
        horizontal=True,
        format_func=lambda v: t("Files" if v == "files" else "Folder"),
        key=prefix + "mode",
    )
    if mode == "folder":
        st.caption(
            t(
                "Documents stay in their folder and are read when a task runs. An Obsidian vault is also a folder."
            )
        )
        directory = st.text_input(t("Folder path"), key=f"directory:{workspace.path}")
        if st.button(t("Connect folder"), disabled=not directory.strip(), key="connect_directory"):
            try:
                collections.connect(workspace, directory)
                st.session_state[SOURCE_DIALOG_KEY] = False
                st.session_state[NAVIGATE_KEY] = str(Page.SOURCES)
                st.session_state[NOTICE_KEY] = t("Folder connected.")
                st.rerun(scope="app")
            except (ValueError, OSError) as error:
                st.error(str(error))
        return
    st.caption(t("PDF, EPUB, MD, TXT · up to 100 MB per file. PDFs need selectable text."))
    uploaded = st.file_uploader(
        t("Choose files or drag them here"),
        type=["pdf", "epub", "md", "txt"],
        accept_multiple_files=True,
        max_upload_size=100,
        key=f"uploaded_sources:{workspace.path}",
    )
    upload_labels(
        data={"choose": t("Choose files"), "limit": t("100 MB per file · PDF, EPUB, MD, TXT")},
        key="source-upload-labels",
    )
    outcomes = st.session_state.setdefault(prefix + "outcomes", {})
    incoming = []
    for index, upload in enumerate(uploaded):
        digest = hashlib.sha256(upload.getvalue()).hexdigest()
        incoming.append((upload, digest, f"{index}:{upload.name}:{digest}"))
    add = st.button(
        t("Add selected files"), disabled=not incoming, key="import_sources", type="primary"
    )
    existing = {source["hash"] for source in workspace.sources() if not source.get("hidden")}
    for upload, digest, entry in incoming:
        with st.container(border=True):
            st.write(upload.name)
            if add and outcomes.get(entry, {}).get("status") != "added":
                try:
                    with st.spinner(t("Adding {name}…", name=upload.name)):
                        with tempfile.TemporaryDirectory() as folder:
                            path = Path(folder) / Path(upload.name).name
                            path.write_bytes(upload.getvalue())
                            workspace.add_source(path)
                    outcomes[entry] = {"status": "added", "duplicate": digest in existing}
                except (ValueError, OSError) as error:
                    outcomes[entry] = {"status": "error", "error": str(error)}
            if outcomes.get(entry, {}).get("status") == "added":
                existing.add(digest)
            result = outcomes.get(entry)
            if result and result["status"] == "error":
                st.error(
                    t("Could not import {name}: {error}", name=upload.name, error=result["error"])
                )
            elif result:
                st.success(t("Already in this project" if result["duplicate"] else "Source added."))
    if add and all(outcomes.get(entry, {}).get("status") == "added" for _, _, entry in incoming):
        duplicates = sum(outcomes[entry]["duplicate"] for _, _, entry in incoming)
        outcomes.clear()
        st.session_state[SOURCE_DIALOG_KEY] = False
        st.session_state[NAVIGATE_KEY] = str(Page.SOURCES)
        st.session_state[NOTICE_KEY] = t(
            "Files added: {count} · Already present: {duplicates}",
            count=len(incoming) - duplicates,
            duplicates=duplicates,
        )
        st.rerun(scope="app")


def source_dialog(context):
    t = context.t
    st.dialog(
        t("Add source"),
        width="medium",
        on_dismiss=lambda: st.session_state.update({SOURCE_DIALOG_KEY: False}),
    )(_source_dialog)(context)
