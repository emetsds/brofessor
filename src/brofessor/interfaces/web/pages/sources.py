"""Web pages: sources."""

from pathlib import Path

import streamlit as st

from brofessor.application import service
from brofessor.contracts.content import UnitStatus
from brofessor.interfaces.web.components import content as ui_content
from brofessor.interfaces.web.components import layout as ui_layout
from brofessor.interfaces.web.state_keys import ProjectKey, project_key, widget_options


def sources(context):
    workspace = context.workspace
    t = context.t
    ui_layout.heading(t("Sources"), level=2)
    st.button(t("Add source"), key="sources-add-source", on_click=context.show_source_dialog)
    from brofessor.features.sources import collections

    directories = collections.registered(workspace)
    if directories:
        st.divider()
        ui_layout.heading(t("Connected folders"))
    for root in directories:
        with st.expander(Path(root["root"]).name + "/"):
            st.code(root["root"], language=None)
            st.caption(
                t(
                    "Write what you need in the task prompt. The directory is read without changing its files."
                )
            )
            if st.button(t("Disconnect directory"), key="disconnect:" + root["id"]):
                collections.disconnect(workspace, root["id"])
                st.rerun()
    sources = [s for s in workspace.sources() if not s.get("hidden")]
    if sources:
        st.divider()
        ui_layout.heading(t("Source search"))
    query = st.text_input(t("Search source text"), key="source_query") if sources else ""
    if query.strip():
        names = {source["id"]: source["name"] for source in sources}
        scope = (
            st.multiselect(
                t("Search in sources"),
                widget_options(list(names)),
                default=None if "search_source_ids" in st.session_state else list(names),
                format_func=names.__getitem__,
                key="search_source_ids",
            )
            if len(names) > 1
            else list(names)
        )
        st.caption(
            t(
                "Search matches original words. For a question in another language, use Answer a question."
            )
        )
        found = service.search(workspace, query, source_ids=scope)
        if not found:
            st.info(t("No matching fragments." if scope else "Select sources to search."))
        for unit in found:
            st.write(f"{unit['source']} · {unit['locator']} · {unit['id']}")
            st.text(unit["text"])

    if sources:
        st.divider()
        ui_layout.heading(t("Source content"))
        source_map = {source["id"]: source for source in sources}
        selected_source = st.selectbox(
            t("Source"),
            widget_options(list(source_map)),
            format_func=lambda value: source_map[value]["name"],
            key=project_key(workspace.path, ProjectKey.SOURCE_BROWSER),
        )
        source = source_map[selected_source]
        units = workspace.units([selected_source])
        with st.expander(source["name"], expanded=True):
            st.caption(
                t(
                    "Readable fragments: {ready}/{total} · {id}",
                    ready=sum(u["status"] == UnitStatus.READY for u in units),
                    total=len(units),
                    id=source["id"],
                )
            )
            unit_map = {unit["id"]: unit for unit in units}
            if unit_map:
                selected_unit = st.selectbox(
                    t("Fragment"),
                    widget_options(list(unit_map)),
                    format_func=lambda value: unit_map[value]["locator"],
                    key=project_key(workspace.path, ProjectKey.SOURCE_FRAGMENT, selected_source),
                )
                ui_content.prose(unit_map[selected_unit]["text"] or t("No text extracted"))
    elif not collections.registered(workspace):
        st.info(t("Add a book or document to begin."))
