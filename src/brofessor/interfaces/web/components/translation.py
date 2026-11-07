"""Translation controls; domain rules and all model work remain in shared services."""

import streamlit as st

from brofessor.application import service
from brofessor.contracts.content import ArtifactKind
from brofessor.contracts.jobs import JobKind
from brofessor.features.books import translation as book_translation
from brofessor.interfaces.web.components import content as ui_content
from brofessor.interfaces.web.components import layout as ui_layout
from brofessor.interfaces.web.state_keys import UI_PREFIX, EditorSuffix


def glossary_input(key, t):
    with st.expander(t("Optional glossary")):
        st.caption(
            t(
                "Give a term, its meaning in this book and your preferred translation. Other terms are collected automatically."
            )
        )
        widget_key = "book-glossary-grid:" + key
        # The grid's widget state is read-only. Keep a separate, ordinary buffer
        # across navigation, while retaining a fixed grid baseline during edits.
        if widget_key not in st.session_state:
            st.session_state[key + EditorSuffix.BASELINE] = st.session_state.get(
                key + EditorSuffix.ROWS, [{"term": "", "sense": "", "translation": ""}]
            )
        rows = st.data_editor(
            st.session_state[key + EditorSuffix.BASELINE],
            num_rows="dynamic",
            key=widget_key,
            column_order=("term", "sense", "translation"),
            column_config={
                "term": st.column_config.TextColumn(t("Source term"), required=True),
                "sense": st.column_config.TextColumn(t("Meaning / context"), required=True),
                "translation": st.column_config.TextColumn(
                    t("Preferred translation"), required=True
                ),
            },
        )
        st.session_state[key + EditorSuffix.ROWS] = rows
        return [
            {name: row.get(name) or "" for name in ("term", "sense", "translation")}
            for row in rows
            if any(row.values())
        ]


def original(workspace, job, block_id, t):
    with st.expander(t("Original passage")):
        book = book_translation.source_book(workspace, job["params"])
        block = next((block for block in book.blocks if block.id == block_id), None)
        if block:
            st.caption(block.locator)
            ui_content.prose(block.plain_text())


def controls(workspace, job, draft, saved, t, open_result):
    data, revision = draft["data"], draft["revision"]
    prefix = f"book:{workspace.path}:{job['id']}:{revision}"
    pdf = job["kind"] == JobKind.TRANSLATE_PDF
    if saved and st.button(t("Build PDF" if pdf else "Build EPUB"), key=prefix + ":render"):
        try:
            service.render(workspace, job["id"], revision=revision)
            st.rerun()
        except (ValueError, OSError) as error:
            st.error(str(error))
    if data["retained_manual"]:
        st.info(
            t(
                "Manual terminology edits kept: {count}. Review these passages before treating the new term as consistent everywhere.",
                count=len(data["retained_manual"]),
            )
        )
        occurrences = {item["id"]: item for item in data["occurrences"]}
        with st.expander(t("Retained manual passages")):
            for identifier in data["retained_manual"]:
                ui_content.prose(occurrences[identifier]["quote"])
    with ui_layout.section(t("Book terminology"), job["id"] + EditorSuffix.TERMS):
        if not data["terms"]:
            st.caption(t("No glossary terms were identified in this source."))
            return
        terms = {term["id"]: term for term in data["terms"]}
        selected = st.selectbox(
            t("Term meaning"),
            list(terms),
            format_func=lambda key: f"{terms[key]['term']} · {terms[key]['sense']}",
            key=UI_PREFIX + prefix + ":meaning",
        )
        term = terms[selected]
        ui_layout.heading(t("Chosen translation"), level=4)
        ui_content.prose(term["translation"])
        occurrences = [item for item in data["occurrences"] if item["term_id"] == selected]
        st.caption(t("Linked occurrences: {count}", count=len(occurrences)))
        for item in occurrences[:6]:
            ui_content.prose(item["quote"])
        if len(occurrences) > 6:
            st.caption(t("More occurrences are preserved in the saved translation."))
        target_key = UI_PREFIX + prefix + ":target:" + selected
        if target_key not in st.session_state:
            st.session_state[target_key] = term["translation"]
        value = st.text_input(t("Preferred translation"), key=target_key)
        st.caption(
            t(
                "Only this meaning's aligned phrases are updated. Manual terminology edits and other wording are kept."
            )
        )
        if not saved:
            st.caption(t("Save or reload the current revision first."))
        if st.button(
            t("Update linked passages"),
            key=prefix + ":update",
            disabled=not saved or not value.strip() or value.strip() == term["translation"],
        ):
            try:
                result = book_translation.revise_term(
                    workspace, job["id"], selected, value, revision=revision
                )
                open_result(result["id"])
                st.rerun()
            except (ValueError, OSError) as error:
                st.error(str(error))


def file_notes(artifact, t):
    """Keep export qualifications beside the exact file they describe."""
    st.caption(t("File from saved revision {revision}", revision=artifact["metadata"]["revision"]))
    notices = artifact["metadata"].get("preserved_notices", [])
    if notices:
        st.caption(
            t("Copyright/license sections kept in the original: {count}.", count=len(notices))
        )
    if artifact["kind"] == ArtifactKind.PDF:
        st.caption(
            t(
                "Formula, code and numeric objects are kept in the original. Text inside raster images is not translated."
            )
        )
        if artifact["metadata"].get("preserved"):
            with st.expander(t("Preserved PDF objects")):
                for item in artifact["metadata"]["preserved"]:
                    label = {
                        "formula": "Formula",
                        "code": "Code",
                        "numeric/symbol": "Numbers and symbols",
                    }.get(item["reason"], "Original notice or diagram label")
                    st.caption(t("Page {page}", page=item["page"]) + " · " + t(label))
                    ui_content.prose(item["text"])
