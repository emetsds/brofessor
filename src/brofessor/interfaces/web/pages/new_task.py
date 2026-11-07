"""Web pages: new_task."""

import hashlib
import json
import uuid

import streamlit as st

from brofessor.application import service, tasks
from brofessor.contracts.jobs import (
    PODCAST_JOB_KINDS,
    RETRIEVAL_JOB_KINDS,
    TRANSLATION_JOB_KINDS,
    JobKind,
)
from brofessor.contracts.text import TextProvider
from brofessor.features.podcasts.writer import WritingMethod
from brofessor.features.reports import ReportTemplate
from brofessor.infrastructure.formats.contracts import DocumentExtension
from brofessor.interfaces.web.components import content as ui_content
from brofessor.interfaces.web.components import language as ui_language
from brofessor.interfaces.web.components import layout as ui_layout
from brofessor.interfaces.web.dialogs import settings as ui_settings
from brofessor.interfaces.web.state_keys import (
    COMPOSER_MIGRATED_KEY,
    NAVIGATE_KEY,
    ProjectKey,
    project_key,
    widget_options,
    widget_value,
)


def create_result(context):
    workspace = context.workspace
    t = context.t
    ui_layout.heading(t("New task"), level=2)
    prefix = project_key(workspace.path, ProjectKey.NEW, "")
    if not st.session_state.get(COMPOSER_MIGRATED_KEY):
        for name in (
            "focus",
            "kind",
            "source_ids",
            "output_language",
            "minutes",
            "slide_count",
            "series_minutes",
            "episode_count",
            "request_key",
            "request_fingerprint",
        ):
            if name in st.session_state and prefix + name not in st.session_state:
                st.session_state[prefix + name] = st.session_state.pop(name)
        st.session_state[COMPOSER_MIGRATED_KEY] = True
    if st.session_state.pop(prefix + "reset", False):
        st.session_state[prefix + "focus"] = ""
        st.session_state[prefix + "title"] = ""
        st.session_state[prefix + "request_key"] = uuid.uuid4().hex
        st.session_state.pop(prefix + "request_fingerprint", None)
    from brofessor.features.sources.collections import choices

    all_sources = choices(workspace)
    if not all_sources:
        st.info(t("Add a book or document to begin."))
        if st.button(t("Add materials"), key="go_to_sources"):
            st.session_state[NAVIGATE_KEY] = "sources"
            st.rerun()
        return
    names = {s["id"]: s["name"] for s in all_sources}
    if prefix + "source_ids" in st.session_state:
        st.session_state[prefix + "source_ids"] = [
            identifier
            for identifier in st.session_state[prefix + "source_ids"]
            if identifier in names
        ]
    ui_layout.heading(t("Sources"))
    if any(s.get("kind") == "directory" for s in all_sources):
        st.caption(
            t(
                "Documents in connected directories are selected automatically from your task prompt."
            )
        )
        if prefix + "kind" not in st.session_state:
            st.session_state[prefix + "kind"] = widget_value(JobKind.ASK)
    if len(names) == 1:
        selected = list(names)
        ui_content.prose(names[selected[0]])
    else:
        selected = st.multiselect(
            t("Sources"),
            widget_options(list(names)),
            default=None if prefix + "source_ids" in st.session_state else list(names),
            format_func=names.__getitem__,
            key=prefix + "source_ids",
        )
    if prefix + "request_key" not in st.session_state:
        st.session_state[prefix + "request_key"] = uuid.uuid4().hex
    # Ordinary widgets send edits immediately, including before a language switch.
    st.divider()
    with st.container(border=True):
        ui_layout.heading(t("Request"))
        kinds = {
            JobKind.PODCAST: t("Podcast"),
            JobKind.PODCAST_SERIES: t("Podcast series"),
            JobKind.SLIDES: t("Presentation"),
            JobKind.ASK: t("Answer a question"),
            JobKind.REPORT: t("Written report"),
            JobKind.STUDY: t("Practice questions"),
            JobKind.AUDIOBOOK: t("Audiobook"),
            JobKind.TRANSLATE_EPUB: t("Translate book (EPUB 2/3)"),
            JobKind.TRANSLATE_PDF: t("Translate book (text-layer PDF)"),
        }
        kind = st.selectbox(
            t("Output"),
            widget_options(list(kinds)),
            format_func=kinds.__getitem__,
            key=prefix + "kind",
        )
        if kind == JobKind.SLIDES:
            st.caption(
                t(
                    "Ask for comparison tables or a sequence of steps in the focus when they help explain your sources."
                )
            )
        title = st.text_input(
            t("Task name"),
            key=prefix + "title",
            max_chars=160,
            help=t("Leave blank for a short name from your request."),
        )
        focus = (
            ""
            if kind in (JobKind.TRANSLATE_EPUB, JobKind.TRANSLATE_PDF, JobKind.AUDIOBOOK)
            else st.text_area(
                t(
                    "Report goal and context"
                    if kind == JobKind.REPORT
                    else "Learning goal"
                    if kind == JobKind.STUDY
                    else "Question"
                    if kind == JobKind.ASK
                    else "Focus (optional)"
                ),
                key=prefix + "focus",
            )
        )
        if not title.strip():
            st.caption(
                t(
                    "Suggested task name: {name}",
                    name=tasks.initial_title(kind, focus, ""),
                )
            )
        st.divider()
        ui_layout.heading(t("Output settings"))
        language = st.selectbox(
            t("Output language"),
            widget_options(list(ui_language.LANGUAGE_NAMES)),
            format_func=ui_language.LANGUAGE_NAMES.__getitem__,
            key=prefix + "output_language",
        )
        options = {}
        if kind == JobKind.AUDIOBOOK:
            st.caption(t("Narration uses the original text or the selected saved translation."))
            available_translations = {}
            for previous in workspace.jobs():
                if (
                    previous["kind"] in TRANSLATION_JOB_KINDS
                    and previous["params"]["source_ids"] == selected
                ):
                    version = workspace.draft(previous["id"])
                    if version and version["data"]["language"] == language:
                        available_translations[previous["id"]] = version
            translated = st.selectbox(
                t("Saved translation (optional)"),
                widget_options([None, *available_translations]),
                format_func=lambda value: (
                    t("None")
                    if value is None
                    else f"{available_translations[value]['data']['title']} · r{available_translations[value]['revision']}"
                ),
                key=prefix + "translation",
            )
            if translated:
                options["translation"] = {
                    "job_id": translated,
                    "revision": available_translations[translated]["revision"],
                }
        if kind == JobKind.REPORT:
            options["template"] = st.selectbox(
                t("Report template"),
                widget_options(list(ui_language.REPORT_TEMPLATES)),
                format_func=lambda v: t(ui_language.REPORT_TEMPLATES[v]),
                key=prefix + "template",
            )
            if options["template"] == ReportTemplate.REFERENCE:
                accepted = {}
                for previous in workspace.jobs():
                    if previous["kind"] in TRANSLATION_JOB_KINDS:
                        version = workspace.draft(previous["id"])
                        if version and version["data"]["language"] == language:
                            accepted[previous["id"]] = version
                terminology_id = st.selectbox(
                    t("Accepted translation terminology (optional)"),
                    widget_options([None, *accepted]),
                    format_func=lambda value: (
                        t("None")
                        if value is None
                        else f"{accepted[value]['data']['title']} · r{accepted[value]['revision']}"
                    ),
                    key=prefix + "terminology",
                )
                if terminology_id:
                    options["terminology"] = {
                        "job_id": terminology_id,
                        "revision": accepted[terminology_id]["revision"],
                    }
        if kind == JobKind.STUDY:
            options["question_count"] = st.number_input(
                t("Number of questions"), 2, 12, value=6, key=prefix + "question_count"
            )
        if kind in TRANSLATION_JOB_KINDS:
            from brofessor.interfaces.web.components import translation as ui_translation

            st.caption(
                t(
                    "Select one text-layer PDF. Columns and ruled tables are supported when the translation fits. Scans and unsupported layouts are reported explicitly."
                    if kind == JobKind.TRANSLATE_PDF
                    else "Select one reflowable EPUB 2/3. A contextual glossary is built automatically; code, formulas and original illustrations are preserved."
                )
            )
            options["glossary"] = ui_translation.glossary_input(prefix + "glossary", t)
        if kind == JobKind.PODCAST_SERIES:
            options["episode_count"] = st.number_input(
                t("Number of episodes"),
                2,
                12,
                value=3 if prefix + "episode_count" not in st.session_state else None,
                key=prefix + "episode_count",
            )
            options["minutes"] = st.select_slider(
                t("Episode duration, minutes"),
                widget_options([20, 30, 45, 60]),
                value=st.session_state.get(prefix + "series_minutes", 20)
                if prefix + "series_minutes" not in st.session_state
                else None,
                key=prefix + "series_minutes",
            )
            st.caption(t("Review the series plan, then prepare its episodes individually."))
        elif kind == JobKind.PODCAST:
            options["minutes"] = st.select_slider(
                t("Podcast duration, minutes"),
                widget_options([3, 20, 30, 45, 60]),
                value=20 if prefix + "minutes" not in st.session_state else None,
                key=prefix + "minutes",
            )
            st.caption(
                t("3 minutes is a short script and voice preview. Full episodes: 20–60 minutes.")
            )
        elif kind == JobKind.SLIDES:
            options["slide_count"] = st.number_input(
                t("Number of slides"),
                1,
                40,
                value=8 if prefix + "slide_count" not in st.session_state else None,
                key=prefix + "slide_count",
            )
        if kind in PODCAST_JOB_KINDS and options["minutes"] >= 20:
            with st.expander(t("Writing options")):
                if st.toggle(t("Source-backed writing (experimental)"), key=prefix + "originals"):
                    options["writing_method"] = WritingMethod.ORIGINALS
                st.caption(
                    t(
                        "Revisits originals while writing each section. Quality is still being compared; it may require more model context."
                    )
                )
        try:
            connection = ui_settings.new_task_models(
                workspace, kind, t, address_override=context.ollama_address
            )
        except ValueError as error:
            st.error(str(error))
            connection = None
        if connection and connection.get("provider"):
            context.connection_notice(connection["provider"], connection.get("ollama_address"))
        needs_connection = kind != JobKind.AUDIOBOOK and (
            not connection
            or not connection.get("provider")
            or (connection["provider"] == TextProvider.OLLAMA and not connection["model"])
        )
        if needs_connection or (
            kind != JobKind.AUDIOBOOK and st.session_state.get("connection_error")
        ):
            st.warning(t("Complete the text connection in Settings."))
            if st.button(t("Settings"), key="setup_connection"):
                context.show_settings()
                st.rerun()
        st.caption(
            t(
                {
                    JobKind.ASK: "An answer with quotes from the original sources.",
                    JobKind.REPORT: "An editable report with citations and a Markdown file.",
                    JobKind.STUDY: "Practice questions with saved answers and source-based feedback.",
                    JobKind.AUDIOBOOK: "Complete narration text with chapters, ready for local audio generation.",
                    JobKind.PODCAST: "A saved dialogue, then automatic local narration and audio packaging.",
                    JobKind.SLIDES: "An editable slide outline, ready to build PPTX.",
                    JobKind.PODCAST_SERIES: "A series plan; each created episode includes automatic narration.",
                    JobKind.TRANSLATE_EPUB: "A translated EPUB with the book's structure and terminology.",
                    JobKind.TRANSLATE_PDF: "A translated PDF with supported layout and illustrations.",
                }[kind]
            )
        )
        submitted = st.button(
            t("Create task"),
            disabled=not selected
            or (
                kind == JobKind.AUDIOBOOK and (len(selected) != 1 or selected[0].startswith("dir-"))
            )
            or (
                kind == JobKind.TRANSLATE_EPUB
                and (
                    len(selected) != 1
                    or not names[selected[0]].lower().endswith(DocumentExtension.EPUB)
                )
            )
            or (
                kind == JobKind.TRANSLATE_PDF
                and (
                    len(selected) != 1
                    or not names[selected[0]].lower().endswith(DocumentExtension.PDF)
                )
            )
            or (kind in RETRIEVAL_JOB_KINDS and not focus.strip())
            or needs_connection
            or (kind != JobKind.AUDIOBOOK and bool(st.session_state.get("connection_error"))),
            key="prepare",
            type="primary",
        )
    if submitted:
        try:
            fingerprint = hashlib.sha256(
                json.dumps(
                    [
                        str(workspace.path),
                        kind,
                        selected,
                        focus,
                        title,
                        language,
                        connection,
                        options,
                    ],
                    ensure_ascii=False,
                ).encode()
            ).hexdigest()
            if st.session_state.get(prefix + "request_fingerprint") != fingerprint:
                st.session_state[prefix + "request_key"] = uuid.uuid4().hex
                st.session_state[prefix + "request_fingerprint"] = fingerprint
            job = service.submit(
                workspace,
                kind,
                source_ids=selected,
                focus=focus,
                title=title,
                language=language,
                **connection,
                **options,
                request_key=st.session_state[prefix + "request_key"],
            )
            st.session_state[prefix + "reset"] = True
            context.open_result(job["id"])
            st.rerun()
        except Exception as error:
            st.error(t("Could not submit the job: {error}", error=error))
