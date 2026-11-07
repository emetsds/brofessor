"""Draft reading, editing, recovery, and optional single-turn listening."""

import html
import json
import math

import streamlit as st

from brofessor.application import service
from brofessor.contracts.content import Speaker, UnitStatus
from brofessor.contracts.jobs import (
    ACTIVE_JOB_STATUSES,
    RESUMABLE_JOB_STATUSES,
    TRANSLATION_JOB_KINDS,
    JobKind,
    JobStatus,
    StageId,
)
from brofessor.features.reports import SectionOrigin
from brofessor.features.studies import QuestionKind
from brofessor.infrastructure.formats.contracts import AudioExtension
from brofessor.infrastructure.speech import catalogue as speech_models
from brofessor.infrastructure.speech.contracts import QWEN_ENGINE_PREFIX, SpeechEngine
from brofessor.interfaces.web.components import language as ui_language
from brofessor.interfaces.web.components import layout as ui_layout
from brofessor.interfaces.web.components import recovery as ui_recovery
from brofessor.interfaces.web.components.recovery import RECOVERY_DIRECTORY
from brofessor.interfaces.web.state_keys import EDITOR_PREFIX, EditorSuffix, widget_options


def prose(text):
    """Source/model text stays text: do not load embedded images or execute source HTML."""
    safe = html.escape(str(text)).replace("\n", "<br>")
    st.html(f'<div class="brofessor-prose">{safe}</div>')


def editor_key(workspace, job_id):
    return f"{EDITOR_PREFIX}{workspace.path}:{job_id}"


def restore_editor(key, path):
    copy = ui_recovery.restore(key, path)
    if copy is None:
        return False
    text = copy["content"]
    if "item" in copy:
        st.session_state[key + EditorSuffix.ITEM_SELECTED] = copy["item"]
    st.session_state[key] = copy["revision"]
    st.session_state[key + EditorSuffix.TEXT] = text
    st.session_state[key + EditorSuffix.EDITING] = True
    try:
        json.loads(text)
    except ValueError:
        st.session_state[key + EditorSuffix.JSON] = True
    reset_fields(key)
    return True


def load_editor(workspace, job, draft):
    key = editor_key(workspace, job["id"])
    if key not in st.session_state:
        folder = workspace.path / RECOVERY_DIRECTORY / job["id"]
        st.session_state[key + EditorSuffix.FOLDER] = folder
        copies = ui_recovery.copies(folder)
        if not copies or not restore_editor(key, copies[0]):
            st.session_state[key] = draft["revision"]
            st.session_state[key + EditorSuffix.TEXT] = json.dumps(
                draft["data"], ensure_ascii=False, indent=2
            )
    if saved := st.session_state.pop(key + EditorSuffix.SAVED_DATA, None):
        st.session_state[key] = saved["revision"]
        st.session_state[key + EditorSuffix.TEXT] = json.dumps(
            saved["data"], ensure_ascii=False, indent=2
        )
    original = (
        draft
        if st.session_state[key] == draft["revision"]
        else workspace.draft(job["id"], st.session_state[key])
    )
    st.session_state[key + EditorSuffix.ORIGINAL] = original["data"] if original else None
    return key


def protect_editor(key):
    try:
        if (
            json.loads(st.session_state[key + EditorSuffix.TEXT])
            == st.session_state[key + EditorSuffix.ORIGINAL]
        ):
            ui_recovery.forget(key)
            return
    except ValueError:
        pass  # Incomplete JSON also needs recovery.
    ui_recovery.protect(
        key,
        st.session_state[key + EditorSuffix.FOLDER],
        st.session_state[key],
        st.session_state[key + EditorSuffix.TEXT],
        item=st.session_state.get(key + EditorSuffix.ITEM_SELECTED),
    )


def reset_fields(key):
    st.session_state[key + EditorSuffix.EPOCH] = (
        st.session_state.get(key + EditorSuffix.EPOCH, 0) + 1
    )


def reload_editor(workspace, job_id, key):
    ui_recovery.forget(key)
    current = workspace.draft(job_id)
    st.session_state[key] = current["revision"]
    st.session_state[key + EditorSuffix.TEXT] = json.dumps(
        current["data"], ensure_ascii=False, indent=2
    )
    reset_fields(key)


def _write_field(key, path, widget_key, transform):
    value = json.loads(st.session_state[key + EditorSuffix.TEXT])
    ui_recovery.patch_field(value, path, transform(st.session_state[widget_key]))
    if path[-1] == "headers":
        reset_fields(key)
    st.session_state[key + EditorSuffix.TEXT] = json.dumps(value, ensure_ascii=False, indent=2)
    protect_editor(key)


def _lines(value):
    return [line.strip() for line in value.splitlines() if line.strip()]


def fields(data, kind, key, t, source_names, text_inputs):
    """Callbacks update the canonical buffer before navigation can hide a widget."""
    epoch = st.session_state.get(key + EditorSuffix.EPOCH, 0)

    def field(label, path, *, options=None, lines=False, multiline=False):
        value = data
        for part in path:
            value = (
                value.get(part, [] if part in ("steps", "bullets", "citations") else "")
                if isinstance(value, dict)
                else value[part]
            )
        widget_key = f"{key}:field:{epoch}:" + ":".join(map(str, path))
        if widget_key not in st.session_state:
            st.session_state[widget_key] = "\n".join(value) if lines else value
        kwargs = dict(
            key=widget_key,
            on_change=_write_field,
            args=(
                key,
                path,
                widget_key,
                (lambda v: v.split("\n"))
                if lines and "rows" in path
                else _lines
                if lines
                else lambda v: v,
            ),
        )
        if options is not None:
            return st.selectbox(
                t(label),
                widget_options(options),
                format_func=lambda v: ui_language.LANGUAGE_NAMES.get(
                    v,
                    t(
                        {
                            SectionOrigin.SOURCES: "From sources",
                            SectionOrigin.BROFESSOR: "brofessor adaptation",
                            QuestionKind.APPLICATION: "Scenario question",
                            QuestionKind.EXPLANATION: "Explanation question",
                        }.get(v, v)
                    ),
                ),
                **kwargs,
            )
        text_inputs[widget_key] = dict(path=path, lines=lines, value=st.session_state[widget_key])
        if multiline or lines:
            return st.text_area(t(label), height=130, **kwargs)
        return st.text_input(t(label), **kwargs)

    def references(path):
        value = data
        for part in path:
            value = value[part]
        widget_key = f"{key}:field:{epoch}:" + ":".join(map(str, path))
        if widget_key not in st.session_state:
            st.session_state[widget_key] = value
        st.multiselect(
            t("Source references"),
            list(source_names),
            format_func=lambda v: source_names[v],
            key=widget_key,
            on_change=_write_field,
            args=(key, path, widget_key, lambda v: v),
        )

    def item_actions(collection, index, blank):
        def change(operation):
            value = json.loads(st.session_state[key + EditorSuffix.TEXT])
            items = value[collection]
            if operation == "add":
                items.insert(index + 1, blank)
            elif operation == "remove" and len(items) > 1:
                items.pop(index)
            elif operation == "up" and index:
                items[index - 1], items[index] = items[index], items[index - 1]
            st.session_state[key + EditorSuffix.TEXT] = json.dumps(
                value, ensure_ascii=False, indent=2
            )
            protect_editor(key)
            reset_fields(key)

        cols = st.columns(3)
        for col, op, label in zip(
            cols, ("add", "up", "remove"), ("Add after", "Move up", "Remove")
        ):
            col.button(
                t(label),
                key=f"{key}:{collection}:{op}:{index}",
                on_click=change,
                args=(op,),
                disabled=(op == "up" and index == 0)
                or (
                    op == "remove"
                    and len(data[collection]) <= (2 if kind == JobKind.PODCAST else 1)
                ),
            )

    if (
        "title" in data
        and kind not in TRANSLATION_JOB_KINDS
        and (kind != JobKind.STUDY or st.session_state.get(key + EditorSuffix.EDITING))
    ):
        field("Title", ("title",))
    if kind in TRANSLATION_JOB_KINDS:
        from brofessor.features.books import terminology

        items = data["blocks"]
        index = st.selectbox(
            t("Passage"),
            list(range(len(items))),
            format_func=lambda i: f"{i + 1}. {terminology.MARKER.sub('', items[i]['text'])[:90]}",
            key=key + EditorSuffix.ITEM_SELECTED,
        )
        field("Translated passage", ("blocks", index, "text"), multiline=True)
        st.caption(
            t("Keep inline markers unchanged; formatting and links are preserved by the app.")
        )
        return
    if kind == JobKind.ASK:
        field("Answer", ("answer",), multiline=True)
        # Validated quotes and their citation IDs must change together in JSON.
        if "quotes" not in data:
            references(("citations",))
        return
    if kind == JobKind.STUDY:
        if not data["questions"]:
            st.info(t("Not enough source material for grounded questions."))
            return
        selected = key + EditorSuffix.ITEM_SELECTED
        if st.session_state.get(selected, 0) >= len(data["questions"]):
            st.session_state[selected] = 0
        index = st.selectbox(
            t("Question"),
            range(len(data["questions"])),
            format_func=lambda i: (
                f"{data['questions'][i]['id']}. {data['questions'][i]['prompt'][:70]}"
            ),
            key=selected,
        )
        question = data["questions"][index]
        if st.session_state.get(key + EditorSuffix.EDITING):
            field("Question wording", ("questions", index, "prompt"), multiline=True)
            field("Expected explanation", ("questions", index, "expected_answer"), multiline=True)
            field("Assessment criteria", ("questions", index, "criteria"), lines=True)
            field(
                "Question kind",
                ("questions", index, "kind"),
                options=[QuestionKind.APPLICATION, QuestionKind.EXPLANATION],
            )
        else:
            st.caption(
                t(
                    "Scenario question"
                    if question["kind"] == QuestionKind.APPLICATION
                    else "Explanation question"
                )
            )
            ui_layout.heading(question["prompt"], level=4)
            with st.expander(t("Show explanation and sources")):
                prose(question["expected_answer"])
                for criterion in question["criteria"]:
                    prose("• " + criterion)
                for quote in question["quotes"]:
                    st.caption(source_names[quote["citation"]])
                    st.text(quote["text"])
        field("Your answer", ("answers", question["id"]), multiline=True)
        return
    if kind == JobKind.REPORT:
        if st.session_state.get(key + EditorSuffix.ITEM_SELECTED, 0) >= len(data["sections"]):
            st.session_state[key + EditorSuffix.ITEM_SELECTED] = len(data["sections"]) - 1
        index = st.selectbox(
            t("Section"),
            range(len(data["sections"])),
            format_func=lambda i: f"{i + 1}. {data['sections'][i]['heading']}",
            key=key + EditorSuffix.ITEM_SELECTED,
        )
        field("Heading", ("sections", index, "heading"))
        field("Section text", ("sections", index, "text"), multiline=True)
        field(
            "Basis",
            ("sections", index, "origin"),
            options=[SectionOrigin.SOURCES, SectionOrigin.BROFESSOR],
        )
        with st.expander(t("Arrange sections")):
            item_actions(
                "sections",
                index,
                {
                    "heading": t("New section"),
                    "text": "",
                    "origin": SectionOrigin.BROFESSOR,
                    "citations": [],
                    "quotes": [],
                },
            )
        return
    if kind == JobKind.AUDIOBOOK:
        chapter_key = key + EditorSuffix.ITEM_SELECTED
        if st.session_state.get(chapter_key, 0) >= len(data["chapters"]):
            st.session_state[chapter_key] = 0
        index = st.selectbox(
            t("Chapter"),
            range(len(data["chapters"])),
            format_func=lambda i: data["chapters"][i]["title"],
            key=chapter_key,
        )
        field("Chapter title", ("chapters", index, "title"))
        passage_key = key + ":passage:selected"
        if st.session_state.get(passage_key, 0) >= len(data["chapters"][index]["passages"]):
            st.session_state[passage_key] = 0
        passage = st.selectbox(
            t("Passage"),
            range(len(data["chapters"][index]["passages"])),
            format_func=lambda i: data["chapters"][index]["passages"][i]["text"][:70],
            key=passage_key,
        )
        field("Narration text", ("chapters", index, "passages", passage, "text"), multiline=True)
        return
    if kind in (JobKind.PODCAST, JobKind.SLIDES):
        collection = "turns" if kind == JobKind.PODCAST else JobKind.SLIDES
        items = data[collection]
        select_key = f"{key}:item:selected"
        if st.session_state.get(select_key, 0) >= len(items):
            st.session_state[select_key] = len(items) - 1
        index = st.selectbox(
            t("Turn" if kind == JobKind.PODCAST else "Slide"),
            range(len(items)),
            format_func=lambda i: (
                f"{i + 1}. "
                + (items[i].get("title") or items[i].get("text", "")[:70] or t("New slide"))
            ),
            key=select_key,
        )
        item = items[index]
        if kind == JobKind.PODCAST:
            field("Speaker", (collection, index, "speaker"), options=[Speaker.HOST, Speaker.GUEST])
            field("Spoken text", (collection, index, "text"), multiline=True)
            blank = {"speaker": Speaker.HOST, "text": "", "citations": list(item["citations"])}
        else:
            field("Slide title", (collection, index, "title"))
            field("Bullets, one per line", (collection, index, "bullets"), lines=True)
            with st.expander(t("Speaker notes, tables and steps")):
                field("Speaker notes", (collection, index, "notes"), multiline=True)
                visual_allowed = len(item.get("bullets", [])) <= 2
                if not visual_allowed and not item.get("table") and not item.get("steps"):
                    st.caption(t("Keep at most two bullets to add a table or steps."))
                if not item.get("table") and (visual_allowed or item.get("steps")):
                    field("Steps, one per line", (collection, index, "steps"), lines=True)
                if item.get("table"):
                    field(
                        "Table columns, one per line",
                        (collection, index, "table", "headers"),
                        lines=True,
                    )
                    for row in range(len(item["table"]["rows"])):
                        field(
                            "Table row, one cell per line",
                            (collection, index, "table", "rows", row),
                            lines=True,
                        )

                    def change_row(remove=False):
                        value = json.loads(st.session_state[key + EditorSuffix.TEXT])
                        table = value["slides"][index]["table"]
                        if remove:
                            table["rows"].pop()
                        else:
                            table["rows"].append([""] * len(table["headers"]))
                        st.session_state[key + EditorSuffix.TEXT] = json.dumps(
                            value, ensure_ascii=False, indent=2
                        )
                        protect_editor(key)
                        reset_fields(key)

                    add, remove = st.columns(2)
                    add.button(
                        t("Add row"),
                        key=f"{key}:add-row:{index}",
                        on_click=change_row,
                        disabled=len(item["table"]["rows"]) >= 8,
                    )
                    remove.button(
                        t("Remove last row"),
                        key=f"{key}:remove-row:{index}",
                        on_click=change_row,
                        args=(True,),
                        disabled=len(item["table"]["rows"]) <= 1,
                    )

                def table_toggle():
                    value = json.loads(st.session_state[key + EditorSuffix.TEXT])
                    value["slides"][index]["table"] = (
                        None if item.get("table") else {"headers": ["", ""], "rows": [["", ""]]}
                    )
                    st.session_state[key + EditorSuffix.TEXT] = json.dumps(
                        value, ensure_ascii=False, indent=2
                    )
                    protect_editor(key)
                    reset_fields(key)

                if not item.get("steps") and (visual_allowed or item.get("table")):
                    st.button(
                        t("Remove table" if item.get("table") else "Add table"),
                        key=f"{key}:table:{index}",
                        on_click=table_toggle,
                    )
            blank = {
                "title": "",
                "bullets": [],
                "notes": "",
                "steps": [],
                "table": None,
                "citations": list(item["citations"]),
            }
        references((collection, index, "citations"))
        with st.expander(t("Arrange turns" if kind == JobKind.PODCAST else "Arrange slides")):
            item_actions(collection, index, blank)
        if kind == JobKind.PODCAST:
            return index + 1
    elif kind == JobKind.PODCAST_SERIES:
        index = st.selectbox(
            t("Episode"),
            range(len(data["episodes"])),
            format_func=lambda i: f"{i + 1}. {data['episodes'][i]['title']}",
            key=f"{key}:episode:{epoch}",
        )
        field("Episode title", ("episodes", index, "title"))
        topic_names = {topic["id"]: topic["title"] for topic in data["topics"]}
        path = ("episodes", index, "topic_ids")
        widget_key = f"{key}:field:{epoch}:episode-topics:{index}"
        if widget_key not in st.session_state:
            st.session_state[widget_key] = data["episodes"][index]["topic_ids"]
        st.multiselect(
            t("Topics"),
            list(topic_names),
            format_func=topic_names.__getitem__,
            key=widget_key,
            on_change=_write_field,
            args=(key, path, widget_key, lambda v: v),
        )
        with st.expander(t("Edit topics and terminology")):
            topic = st.selectbox(
                t("Topic"),
                range(len(data["topics"])),
                format_func=lambda i: data["topics"][i]["title"],
                key=f"{key}:topic:{epoch}",
            )
            field("Topic title", ("topics", topic, "title"))
            field("Topic scope", ("topics", topic, "brief"), multiline=True)
            references(("topics", topic, "citations"))
            if data["terms"]:
                term = st.selectbox(
                    t("Term"),
                    range(len(data["terms"])),
                    format_func=lambda i: data["terms"][i]["term"],
                    key=f"{key}:term:{epoch}",
                )
                field("Term", ("terms", term, "term"))
                field("Meaning", ("terms", term, "meaning"), multiline=True)
                references(("terms", term, "citations"))


def turn_page(key, pages, t):
    page_key = key + EditorSuffix.PREVIEW_PAGE
    select_key = page_key + ":select"
    current = max(1, min(st.session_state.get(page_key, 1), pages))
    st.session_state[page_key] = current
    if pages == 1:
        return current
    st.session_state[select_key] = current

    def select(value=None):
        page = st.session_state[select_key] if value is None else value
        st.session_state[page_key] = max(1, min(page, pages))
        st.session_state[select_key] = st.session_state[page_key]

    with st.container(horizontal=True, vertical_alignment="center", key="script-pager-" + key):
        st.button(
            t("Previous page"),
            icon=":material/chevron_left:",
            type="tertiary",
            key=page_key + ":previous",
            on_click=select,
            args=(current - 1,),
            disabled=current == 1,
        )
        st.selectbox(
            t("Page"),
            range(1, pages + 1),
            format_func=lambda value: f"{value} / {pages}",
            key=select_key,
            on_change=select,
            label_visibility="collapsed",
            width=112,
        )
        st.button(
            t("Next page"),
            icon=":material/chevron_right:",
            type="tertiary",
            key=page_key + ":next",
            on_click=select,
            args=(current + 1,),
            disabled=current == pages,
        )
    return current


def preview(data, kind, key, t, workspace, *, job_id, include_terms=True):
    names = {s["id"]: s["name"] for s in workspace.sources()}
    from brofessor.features.sources import navigation as source_navigation

    try:
        names = source_navigation.names(workspace, workspace.job(job_id))
    except ValueError:
        pass
    units = {u["id"]: u for u in workspace.units()}

    def citations(ids):
        if not ids:
            return
        with st.popover(t("Source references")):
            for citation in ids:
                unit = units.get(citation)
                if unit:
                    st.caption(f"{names[unit['source_id']]} · {unit['locator']}")
                    prose(unit["text"])

    if kind in TRANSLATION_JOB_KINDS:
        from brofessor.features.books import terminology
        from brofessor.interfaces.web.components import translation as ui_translation

        items = data["blocks"]
        index = st.selectbox(
            t("Passage"),
            list(range(len(items))),
            format_func=lambda i: f"{i + 1}. {terminology.MARKER.sub('', items[i]['text'])[:90]}",
            key=key + EditorSuffix.ITEM_SELECTED,
        )
        from brofessor.features.books import translation as book_translation

        job = workspace.job(job_id)
        book = book_translation.source_book(workspace, job["params"])
        source = next(b for b in book.blocks if b.id == items[index]["id"])
        prose(source.plain_text(items[index]["text"]))
        ui_translation.original(workspace, workspace.job(job_id), items[index]["id"], t)
    elif kind == JobKind.ASK:
        prose(data["answer"])
    elif kind == JobKind.REPORT:
        for section in data["sections"]:
            ui_layout.heading(section["heading"], level=4)
            ui_layout.origin(
                t(
                    "From sources"
                    if section["origin"] == SectionOrigin.SOURCES
                    else "brofessor adaptation"
                )
            )
            prose(section["text"])
            citations(section["citations"])
    elif kind == JobKind.STUDY:
        for question in data["questions"]:
            ui_layout.heading(question["id"] + ". " + question["prompt"], level=4)
            if answer := data["answers"].get(question["id"]):
                ui_layout.origin(t("Saved learner answer"))
                prose(answer)
            ui_layout.origin(t("Expected explanation"))
            prose(question["expected_answer"])
            for criterion in question["criteria"]:
                prose("• " + criterion)
            citations(question["citations"])
    elif kind == JobKind.AUDIOBOOK:
        index = st.selectbox(
            t("Chapter"),
            range(len(data["chapters"])),
            format_func=lambda i: data["chapters"][i]["title"],
            key=key + EditorSuffix.ITEM_SELECTED,
        )
        if data.get("user_edited"):
            st.caption(t("Narration includes your text edits."))
        for passage in data["chapters"][index]["passages"]:
            prose(passage["text"])
            citations(passage["citations"])
    elif kind == JobKind.PODCAST_SERIES:
        topics = {topic["id"]: topic for topic in data["topics"]}
        for number, episode in enumerate(data["episodes"], 1):
            ui_layout.heading(f"{number}. {episode['title']}", level=4)
            st.caption(" · ".join(topics[topic]["title"] for topic in episode["topic_ids"]))
        if include_terms and data["terms"]:
            ui_layout.heading(t("Shared terminology"), level=4)
            for term in data["terms"]:
                prose(f"{term['term']}: {term['meaning']}")
    elif kind == JobKind.PODCAST:
        turns = data["turns"]
        page = turn_page(key, max(1, math.ceil(len(turns) / 8)), t)
        start = (page - 1) * 8
        st.caption(
            t(
                "Turns {start}–{end} of {total}",
                start=start + 1,
                end=min(start + 8, len(turns)),
                total=len(turns),
            )
        )
        for turn in turns[start : start + 8]:
            st.markdown(f"**{t(turn['speaker'])}**")
            prose(turn["text"])
            citations(turn["citations"])
    elif kind == JobKind.SLIDES:
        for index, slide in enumerate(data["slides"], 1):
            ui_layout.heading(f"{index}. {slide['title']}", level=4)
            for bullet in slide["bullets"]:
                prose("• " + bullet)
            if slide.get("table"):
                table = slide["table"]
                head = "".join(f"<th>{html.escape(v)}</th>" for v in table["headers"])
                rows = "".join(
                    "<tr>" + "".join(f"<td>{html.escape(v)}</td>" for v in row) + "</tr>"
                    for row in table["rows"]
                )
                st.html(
                    f'<div class="brofessor-table"><table><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table></div>'
                )
            if slide.get("steps"):
                prose(" → ".join(slide["steps"]))
            if slide["notes"]:
                with st.expander(t("Speaker notes")):
                    prose(slide["notes"])
            citations(slide["citations"])


def job_error(job, t):
    if job["error"]:
        if (
            job["kind"] in (JobKind.RENDER_PODCAST, JobKind.PREVIEW_TURN)
            and "kIOGPUCommandBufferCallbackErrorOutOfMemory" in job["error"]
        ):
            st.error(
                t(
                    "There was not enough memory for speech. When memory is available, click Resume. Completed turns will be reused."
                )
            )
            with st.expander(t("Technical details")):
                st.text(job["error"])
        else:
            st.error(t("Details: {error}", error=job["error"]))


def turn_preview(workspace, job_id, revision, turn, language, saved, t, model=None):
    if not saved:
        st.caption(t("Save the edits to preview this turn."))
        return
    if model is None:
        from brofessor.application import tasks

        model = tasks.models(workspace, job_id)["data"]["speech_model"]
    existing = next(
        (
            item
            for item in workspace.jobs()
            if item["kind"] == JobKind.PREVIEW_TURN
            and item["params"]["draft_job_id"] == job_id
            and item["params"]["revision"] == revision
            and item["params"]["turn"] == turn
            and service.uses_current_voice(item, language, model)
        ),
        None,
    )
    if existing:
        status = existing["status"]
        if status == JobStatus.SUCCEEDED and (path := service.rendered_file(workspace, existing)):
            st.caption(t("Turn {turn} · Revision {revision}", turn=turn, revision=revision))
            st.audio(
                str(path), format="audio/mpeg" if path.suffix == AudioExtension.MP3 else "audio/wav"
            )
            return
        if status in ACTIVE_JOB_STATUSES:
            label = "Queued" if status == JobStatus.QUEUED else "Generating speech"
            if existing["progress"].get("stage") == StageId.WAITING_FOR_SPEECH:
                label = "Waiting for another local speech job to finish"
            st.caption(t(label))
            return
        job_error(existing, t)
    item = next((m for m in speech_models.list_models() if m["id"] == model), None)
    if item is None:
        from brofessor.application import maintenance

        spec = speech_models.get(model)
        known = next((m for m in maintenance.speech_inventory() if m["id"] == spec["id"]), None)
        if known is None:
            st.caption(t("This saved voice profile is unavailable on this computer."))
            return
        item = {
            **spec,
            "installed": speech_models.installed_path(model) is not None,
            "compatible": known["compatible"],
        }
    if not item["compatible"] or (
        item.get("engine", SpeechEngine.QWEN_CUSTOM).startswith(QWEN_ENGINE_PREFIX)
        and not speech_models.qwen_runtime_available()
    ):
        return
    if not item["installed"]:
        st.caption(t("Download Qwen and its voices to preview this turn."))
        return
    resume = existing and existing["status"] in RESUMABLE_JOB_STATUSES
    if st.button(
        t("Resume") if resume else t("Listen to turn {turn}", turn=turn), key=f"preview-{job_id}"
    ):
        try:
            if existing and existing["status"] in RESUMABLE_JOB_STATUSES:
                from brofessor.application.worker import ensure_worker

                workspace.resume(existing["id"])
                ensure_worker(workspace)
            else:
                service.render(workspace, job_id, revision=revision, turn=turn, model=model)
            st.rerun()
        except (OSError, ValueError) as error:
            st.error(t("Could not prepare the preview: {error}", error=error))


def editor(workspace, job, draft, t, *, voice=None, action=None, advanced_area, has_file=False):
    key = load_editor(workspace, job, draft)
    if st.session_state.get(key + EditorSuffix.RECOVERED):
        st.info(t("Recovered unsaved changes."))
    ui_recovery.other_copies(
        key, st.session_state[key + EditorSuffix.FOLDER], lambda path: restore_editor(key, path), t
    )
    loaded = st.session_state[key]
    turn = None
    text_inputs = {}
    try:
        data = json.loads(st.session_state[key + EditorSuffix.TEXT])
    except ValueError:
        data = None
    if loaded != draft["revision"]:
        st.warning(t("A newer revision is available. Your unsaved edits are still in the editor."))
    saved = data == draft["data"] and loaded == draft["revision"]

    def toggle_edit():
        st.session_state[key + EditorSuffix.EDITING] = not st.session_state.get(
            key + EditorSuffix.EDITING, False
        )
        reset_fields(key)

    with st.container(horizontal=True, vertical_alignment="center"):
        st.button(
            t("Read task" if st.session_state.get(key + EditorSuffix.EDITING) else "Edit task"),
            key=f"edit-{job['id']}",
            on_click=toggle_edit,
        )
        if action:
            action(loaded, saved)
        st.caption(
            t("Saved · Revision {revision}", revision=loaded)
            if saved
            else t("Unsaved changes · Revision {revision}", revision=loaded)
        )
    labels = {
        JobKind.ASK: "Answer",
        JobKind.REPORT: "Written report",
        JobKind.SLIDES: "Slide outline",
        JobKind.PODCAST: "Podcast script",
        JobKind.PODCAST_SERIES: "Series plan",
        JobKind.STUDY: "Questions and answers",
        JobKind.AUDIOBOOK: "Audiobook text",
        JobKind.TRANSLATE_EPUB: "Book translation",
        JobKind.TRANSLATE_PDF: "PDF translation",
    }
    editing = st.session_state.get(key + EditorSuffix.EDITING, False)
    expanded = editing or (
        job["kind"] != JobKind.PODCAST
        and (job["kind"] not in (JobKind.SLIDES, JobKind.AUDIOBOOK) or not has_file)
    )
    label = (
        t("Script · {count} turns", count=len(data.get("turns", [])))
        if job["kind"] == JobKind.PODCAST
        and isinstance(data, dict)
        and isinstance(data.get("turns"), list)
        else t(labels[job["kind"]])
    )
    mode = "editing" if editing else "reading"
    with ui_layout.section(label, key + ":material:" + mode, expanded=expanded):
        if data is not None and not st.session_state.get(key + EditorSuffix.JSON):
            try:
                if editing or job["kind"] == JobKind.STUDY:
                    from brofessor.features.sources import navigation as source_navigation

                    sources = source_navigation.names(workspace, job)
                    names = {
                        unit["id"]: f"{sources[unit['source_id']]} · {unit['locator']}"
                        for unit in source_navigation.units(workspace, job)
                        if unit["status"] == UnitStatus.READY
                    }
                    turn = fields(data, job["kind"], key, t, names, text_inputs)
                else:
                    preview(
                        data, job["kind"], key, t, workspace, job_id=job["id"], include_terms=False
                    )
            except (KeyError, IndexError, TypeError, AttributeError):
                st.info(t("Use the JSON editor to restore the draft structure."))
        elif data is None or st.session_state.get(key + EditorSuffix.JSON):
            st.info(t("Use the advanced editor in Task information and settings."))
    with advanced_area, ui_layout.section(t("Advanced editor"), key + ":advanced"):
        technical = st.toggle(
            t("Edit JSON"), key=key + EditorSuffix.JSON, on_change=reset_fields, args=(key,)
        )
        if technical:
            if "language" in draft["data"]:
                st.caption(
                    t(
                        "The language code describes the existing text. Editing it does not translate the content."
                    )
                )
            st.text_area(
                t("Content (JSON)"),
                height=300,
                key=key + EditorSuffix.TEXT,
                on_change=protect_editor,
                args=(key,),
            )
    if technical:
        text_inputs[key + EditorSuffix.TEXT] = dict(
            path=[], lines=False, value=st.session_state[key + EditorSuffix.TEXT]
        )
    ui_recovery.watch_closing_field(
        key,
        st.session_state[key + EditorSuffix.FOLDER],
        loaded,
        st.session_state[key + EditorSuffix.TEXT],
        text_inputs,
        lambda path: restore_editor(key, path),
    )
    # Re-read: callbacks and the JSON widget share the same canonical buffer.
    try:
        value = json.loads(st.session_state[key + EditorSuffix.TEXT])
        saved = value == draft["data"] and loaded == draft["revision"]
    except ValueError:
        saved = False
    if not saved or st.session_state.get(key + EditorSuffix.EDITING) or technical:
        col1, col2 = st.columns(2)
        col1.button(
            t("Load latest revision"),
            key=f"reload-{job['id']}",
            on_click=reload_editor,
            args=(workspace, job["id"], key),
        )
        if col2.button(
            t("Save edits"),
            key=f"save-{job['id']}",
            disabled=saved,
            type="primary" if not saved else "secondary",
        ):
            try:
                saved_draft = service.edit_draft(
                    workspace,
                    job["id"],
                    json.loads(st.session_state[key + EditorSuffix.TEXT]),
                    loaded,
                )
                ui_recovery.forget(key)
                st.session_state[key + EditorSuffix.SAVED_DATA] = saved_draft
                reset_fields(key)
                st.rerun()
            except (ValueError, TypeError, OSError) as error:
                st.error(t("Could not save edits: {error}", error=error))
    if turn is not None:
        turn_preview(workspace, job["id"], loaded, turn, draft["data"]["language"], saved, t, voice)
    return saved
