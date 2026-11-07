"""Web pages: tasks."""

import hashlib
import json
from functools import partial

import streamlit as st

from brofessor.application import service, tasks
from brofessor.contracts.content import ArtifactKind, EvidenceStatus
from brofessor.contracts.jobs import (
    ACTIVE_JOB_STATUSES,
    ALL_TASK_KINDS_FILTER,
    PRIMARY_JOB_KINDS,
    TRANSLATION_JOB_KINDS,
    InitialAudioState,
    JobKind,
    JobStatus,
)
from brofessor.features.podcasts.writer import WritingMethod
from brofessor.features.sources.reading import ReadingStatus
from brofessor.infrastructure.speech import catalogue as speech_models
from brofessor.interfaces.web.components import content as ui_content
from brofessor.interfaces.web.components import language as ui_language
from brofessor.interfaces.web.components import layout as ui_layout
from brofessor.interfaces.web.components import navigation as ui_navigation
from brofessor.interfaces.web.components import script_checks as ui_script_checks
from brofessor.interfaces.web.components.audio import prepare_voice, render_controls
from brofessor.interfaces.web.components.jobs import job_status, output_label
from brofessor.interfaces.web.components.series import series_actions
from brofessor.interfaces.web.dialogs import settings as ui_settings
from brofessor.interfaces.web.labels import JOB_LABELS, STATUS_LABELS
from brofessor.interfaces.web.pages.new_task import create_result
from brofessor.interfaces.web.state_keys import (
    NAVIGATE_KEY,
    NAVIGATION_KEY,
    EditorSuffix,
    ProjectKey,
    project_key,
    widget_options,
)


@st.fragment
def task_catalogue(context, has_tasks):
    workspace = context.workspace
    t = context.t
    with st.container(key="task-catalogue"):
        ui_layout.heading(t("Tasks"), level=2)
        query, kind_filter = "", ALL_TASK_KINDS_FILTER
        if has_tasks:
            search, kinds = st.columns([4, 2])
            query = search.text_input(
                t("Find task"),
                key=project_key(workspace.path, ProjectKey.FIND_RESULT),
                placeholder=t("Search by word prefix"),
                icon=":material/search:",
                type="search",
                live="0ms",
                label_visibility="collapsed",
            )
            kind_filter = kinds.selectbox(
                t("Task type"),
                widget_options([ALL_TASK_KINDS_FILTER, *ui_navigation.TASK_LABELS]),
                format_func=lambda value: t(
                    "All tasks"
                    if value == ALL_TASK_KINDS_FILTER
                    else ui_navigation.TASK_LABELS[value]
                ),
                key=project_key(workspace.path, ProjectKey.FILTER),
                label_visibility="collapsed",
            )
        matches = tasks.list_tasks(workspace, query=query, kind=kind_filter)
        page_key = project_key(workspace.path, ProjectKey.RESULT_PAGE)
        criteria_key = project_key(workspace.path, ProjectKey.TASK_CRITERIA)
        criteria = (query, kind_filter)
        if st.session_state.get(criteria_key) != criteria:
            st.session_state[page_key] = 1
            st.session_state[criteria_key] = criteria
        pages = max(1, (len(matches) + 5) // 6)
        if st.session_state.get(page_key, 1) > pages:
            st.session_state[page_key] = pages
        page = st.number_input(t("Page"), 1, pages, key=page_key) if pages > 1 else 1
        for item in matches[(page - 1) * 6 : page * 6]:
            ui_navigation.task_row(
                item, t, key=f"open-{item['root_id']}", open_task=context.open_result
            )
        if not matches:
            st.info(t("No tasks yet." if not has_tasks else "No matching tasks."))
        removed = tasks.list_tasks(workspace, deleted=True)
        if removed:
            with st.expander(t("Deleted tasks")):
                for item in removed:
                    label, action = st.columns([4, 1], vertical_alignment="center")
                    label.write(item["title"] or t("Task"))
                    if action.button(
                        t("Restore"),
                        key=f"restore-task:{item['root_id']}",
                        on_click=context.restore_task,
                        args=(item["root_id"],),
                    ):
                        st.rerun()


def results(context):
    workspace = context.workspace
    t = context.t
    from brofessor.application.worker import is_running

    all_jobs = tasks.visible_jobs(workspace)
    by_id = {job["id"]: job for job in all_jobs}
    active = [job for job in all_jobs if job["status"] in ACTIVE_JOB_STATUSES]
    with workspace.connect() as db:
        pending_audio = db.execute(
            "SELECT 1 FROM initial_audio a JOIN jobs j ON a.job_id=j.id WHERE a.state=? AND a.render_id IS NULL AND j.status=? LIMIT 1",
            (InitialAudioState.PENDING, JobStatus.SUCCEEDED),
        ).fetchone()
    if (active or pending_audio) and not is_running(workspace):
        st.warning(t("Background processing is stopped"))
        if st.button(t("Restore processing"), key="restore_processing"):
            from brofessor.application.worker import ensure_worker

            ensure_worker(workspace)
            st.rerun()
    primary = [job for job in all_jobs if job["kind"] in PRIMARY_JOB_KINDS]
    roots = [job for job in primary if tasks.root_job(job, by_id) == job["id"]]
    selected_key = project_key(workspace.path, ProjectKey.SELECTED_JOB)
    selected = st.session_state.get(selected_key)
    if selected not in by_id:
        selected = roots[0]["id"] if roots else None
        st.session_state[selected_key] = selected
    selected_root = tasks.root_job(by_id[selected], by_id) if selected else None
    creating = st.session_state.get(project_key(workspace.path, ProjectKey.CREATING), False)
    catalogue = st.session_state.get(project_key(workspace.path, ProjectKey.CATALOGUE), False)
    if (catalogue or not selected) and not creating:
        task_catalogue(context, bool(roots))
        return
    with st.container(key="result-detail"):
        if st.session_state.get(project_key(workspace.path, ProjectKey.CREATING)) or not selected:
            create_result(context)
            return
        active_render = next(
            (
                j
                for j in all_jobs
                if j["params"].get("draft_job_id") == selected
                and j["kind"]
                in (
                    JobKind.RENDER_PODCAST,
                    JobKind.RENDER_AUDIOBOOK,
                    JobKind.RENDER_SLIDES,
                    JobKind.RENDER_EPUB,
                    JobKind.RENDER_PDF,
                )
                and j["status"] in ACTIVE_JOB_STATUSES
            ),
            None,
        )
        initial = by_id[selected]["params"].get("auto_audio")
        from brofessor.application.initial_audio import state as audio_state

        initial_state = audio_state(workspace, selected) if initial else None
        selected_render_id = st.session_state.get(
            project_key(workspace.path, ProjectKey.NEXT_RENDER, selected)
        ) or st.session_state.get(project_key(workspace.path, ProjectKey.RENDER, selected))
        chosen_render = (
            by_id.get(selected_render_id)
            if selected_render_id
            else next(
                (
                    j
                    for j in all_jobs
                    if j["params"].get("draft_job_id") == selected
                    and j["kind"]
                    in (
                        JobKind.RENDER_PODCAST,
                        JobKind.RENDER_AUDIOBOOK,
                        JobKind.RENDER_SLIDES,
                        JobKind.RENDER_EPUB,
                        JobKind.RENDER_PDF,
                    )
                ),
                None,
            )
        )
        candidate = active_render or chosen_render
        progress_target = (
            candidate["id"]
            if candidate and (not initial_state or initial_state["render_id"] != candidate["id"])
            else selected
        )
        progress_first = by_id[progress_target]["status"] != JobStatus.SUCCEEDED or (
            initial_state
            and initial_state["state"]
            in (InitialAudioState.PENDING, InitialAudioState.BLOCKED, InitialAudioState.CANCELLED)
        )
        model_choices = tasks.models(workspace, selected)["data"]
        with st.container(horizontal=True, vertical_alignment="center", key="task-heading"):
            ui_layout.heading(context.result_title(by_id[selected]), level=2)
            with st.popover("", icon=":material/more_horiz:", help=t("Task actions")):
                name = st.text_input(
                    t("Task name"),
                    value=context.result_title(by_id[selected]),
                    key=project_key(workspace.path, ProjectKey.RENAME, selected),
                    max_chars=160,
                )
                if st.button(t("Rename"), key="rename-task", disabled=not name.strip()):
                    try:
                        tasks.rename(workspace, selected, name)
                        st.rerun()
                    except (OSError, ValueError) as error:
                        st.error(t(str(error)))
                st.button(
                    t("Delete task"),
                    icon=":material/delete:",
                    key="delete-task",
                    on_click=context.request_delete,
                    args=(
                        "task",
                        str(workspace.path),
                        context.result_title(by_id[selected]),
                        selected,
                    ),
                )
        if progress_first:
            job_status(context, progress_target)
        check_status_area = st.container()
        group = [job for job in primary if tasks.root_job(job, by_id) == selected_root]
        if len(group) > 1:
            options = [job["id"] for job in reversed(group)]
            related_key = project_key(workspace.path, ProjectKey.RELATED, selected_root)
            st.session_state[related_key] = selected

            def related_label(identifier):
                if by_id[identifier]["kind"] in TRANSLATION_JOB_KINDS:
                    # A pending translation gains a title on completion. Keep the
                    # selector's labels stable so that this does not change selection.
                    return t("Translation run {number}", number=options.index(identifier) + 1)
                return context.result_title(by_id[identifier])

            st.selectbox(
                t("Related tasks"),
                widget_options(options),
                index=None,
                format_func=related_label,
                key=related_key,
                on_change=lambda: context.open_result(st.session_state[related_key]),
            )
        jobs = [by_id[selected]]
        renders = [
            job
            for job in all_jobs
            if job["kind"]
            in (
                JobKind.RENDER_PODCAST,
                JobKind.RENDER_SLIDES,
                JobKind.RENDER_EPUB,
                JobKind.RENDER_PDF,
                JobKind.RENDER_AUDIOBOOK,
            )
            and job["params"].get("draft_job_id") == selected
        ]
        rendered = None
        output_area = None
        own_files = [a for a in workspace.artifacts(selected) if a["kind"] != "json"]
        if renders or own_files:
            output_kind = (
                JOB_LABELS[renders[0]["kind"]]
                if renders
                else {JobKind.TRANSLATE_EPUB: "EPUB", JobKind.TRANSLATE_PDF: "PDF"}.get(
                    by_id[selected]["kind"], "Ready file"
                )
            )
            with ui_layout.section(t(output_kind), selected + ":output", expanded=True) as area:
                output_area = area
        if renders:
            choices = [job["id"] for job in renders]
            if own_files:
                choices.append(selected)
            next_render = st.session_state.pop(
                project_key(workspace.path, ProjectKey.NEXT_RENDER, selected), None
            )
            if next_render in choices:
                st.session_state[project_key(workspace.path, ProjectKey.RENDER, selected)] = (
                    next_render
                )
            elif (
                project_key(workspace.path, ProjectKey.RENDER, selected) not in st.session_state
                and own_files
            ):
                st.session_state[project_key(workspace.path, ProjectKey.RENDER, selected)] = (
                    selected
                )
            with output_area:
                rendered = st.selectbox(
                    t("Output version"),
                    widget_options(choices),
                    format_func=lambda value: (
                        t(
                            "Original export · Revision {revision}",
                            revision=own_files[0]["metadata"]["revision"],
                        )
                        if value == selected
                        else output_label(context, by_id[value])
                    ),
                    key=project_key(workspace.path, ProjectKey.RENDER, selected),
                )
            if rendered != selected:
                jobs.insert(0, by_id[rendered])
        draft_area = st.container(key="result-draft")
        utilities_area = st.container(key="task-utilities")
        with utilities_area:
            ui_layout.heading(t("Task information and settings"))
            advanced_area = st.container()
            details_area = st.container()
            history_area = st.container()
        saved_draft = True
        for job in jobs:
            kind_name = JOB_LABELS[job["kind"]]
            status_name = STATUS_LABELS[job["status"]]
            draft = workspace.draft(job["id"])
            with output_area if job["id"] == rendered and rendered != selected else draft_area:
                if job["id"] != rendered and not draft:
                    ui_layout.heading(t(kind_name))
                metadata = [t(status_name)]
                if job["kind"] in (
                    JobKind.RENDER_PODCAST,
                    JobKind.RENDER_SLIDES,
                    JobKind.RENDER_EPUB,
                    JobKind.RENDER_PDF,
                    JobKind.RENDER_AUDIOBOOK,
                ):
                    current = workspace.draft(job["params"]["draft_job_id"])
                    metadata.append(
                        t(
                            "File from revision {rendered} · Current draft: {current}",
                            rendered=job["params"]["revision"],
                            current=current["revision"],
                        )
                    )
                elif draft:
                    metadata.append(
                        t("Local speech narration")
                        if job["kind"] == JobKind.AUDIOBOOK
                        else t(
                            "This version was created with {provider} · {model}",
                            provider=job["params"]["provider"],
                            model=job["params"].get("model") or t("Provider default"),
                        )
                    )
                if job["params"].get("series"):
                    reference = job["params"]["series"]
                    metadata.append(
                        t(
                            "Series {id} · Plan revision {revision} · Episode {number}",
                            id=reference["job_id"],
                            revision=reference["revision"],
                            number=reference["episode"],
                        )
                    )
                if job["kind"] == JobKind.RENDER_PODCAST:
                    voice_reference = job["params"].get("model") or speech_models.DEFAULT_ID
                    try:
                        voice_name = speech_models.get(voice_reference)["name"]
                    except ValueError:
                        voice_name = voice_reference
                    voice_name = job["params"].get("model_spec", {}).get("name", voice_name)
                    metadata.append(t("Voice model: {model}", model=voice_name))
                    rendered_draft = workspace.draft(
                        job["params"]["draft_job_id"], job["params"]["revision"]
                    )
                    if rendered_draft:
                        metadata.append(
                            t(
                                "Output language: {output_language}",
                                output_language=ui_language.LANGUAGE_NAMES[
                                    rendered_draft["data"]["language"]
                                ],
                            )
                        )
                st.caption(" · ".join(metadata))
                if draft:
                    if job["kind"] == JobKind.PODCAST_SERIES:
                        st.caption(
                            t(
                                "Episodes: {count} · Target per episode: {minutes} min · Text provider: {provider}",
                                count=len(draft["data"]["episodes"]),
                                minutes=job["params"]["minutes"],
                                provider=job["params"]["provider"],
                            )
                        )
                    if job["kind"] == JobKind.ASK:
                        if job["params"].get("conversation"):
                            conversation = service.question_context(workspace, job["id"])
                            parent = job["params"]["conversation"][-1]
                            st.caption(
                                t(
                                    "Follow-up to {id} · Answer revision {revision}",
                                    id=parent["job_id"],
                                    revision=parent["revision"],
                                )
                            )
                            with st.expander(t("Conversation context")):
                                for turn in conversation["turns"]:
                                    st.caption(f"{turn['job_id']} · r{turn['revision']}")
                                    st.text(turn["question"])
                                    st.text(turn["answer"])
                            if conversation["omitted"]:
                                st.info(
                                    t(
                                        "Earlier turns omitted from model context: {count}. They remain in job history.",
                                        count=conversation["omitted"],
                                    )
                                )
                        if context.result_title(job) != job["params"]["focus"]:
                            ui_layout.heading(t("Question"), level=4)
                            ui_content.prose(job["params"]["focus"])
                    if job["params"].get("writing_method") == WritingMethod.ORIGINALS:
                        st.caption(t("Source-backed writing (experimental)"))
                    audio_ready = True
                    if job["kind"] in (JobKind.PODCAST, JobKind.AUDIOBOOK):
                        from brofessor.application.initial_audio import state as initial_state

                        policy = (
                            initial_state(workspace, job["id"])
                            if job["kind"] == JobKind.PODCAST
                            else None
                        )
                        if (
                            policy
                            and policy["state"] == InitialAudioState.BLOCKED
                            and policy["revision"] == draft["revision"]
                        ):
                            audio_ready = False
                        else:
                            audio_ready = prepare_voice(context, model_choices.get("speech_model"))

                    def render_action(revision, saved):
                        render_controls(
                            context,
                            job,
                            draft,
                            revision,
                            saved,
                            renders,
                            rendered,
                            voice=model_choices.get("speech_model"),
                            ready=audio_ready,
                        )
                        if job["kind"] in (JobKind.PODCAST, JobKind.AUDIOBOOK):
                            completed = next(
                                (
                                    child
                                    for child in renders
                                    if child["status"] == JobStatus.SUCCEEDED
                                    and service.rendered_file(workspace, child)
                                ),
                                None,
                            )
                            if completed:
                                st.caption(
                                    t("Audio matches saved revision {revision}", revision=revision)
                                    if completed["params"]["revision"] == revision
                                    else t(
                                        "Audio: revision {audio} · Script has changed",
                                        audio=completed["params"]["revision"],
                                    )
                                )

                    saved_draft = ui_content.editor(
                        workspace,
                        job,
                        draft,
                        t,
                        voice=model_choices.get("speech_model"),
                        action=render_action
                        if job["kind"] in (JobKind.PODCAST, JobKind.SLIDES, JobKind.AUDIOBOOK)
                        else None,
                        advanced_area=advanced_area,
                        has_file=any(
                            child["status"] == JobStatus.SUCCEEDED
                            and service.rendered_file(workspace, child)
                            for child in renders
                        ),
                    )
                    if job["kind"] == JobKind.STUDY:
                        from brofessor.interfaces.web.components import studies as ui_studies

                        ui_studies.show(
                            workspace,
                            job,
                            draft,
                            saved_draft,
                            t,
                            partial(job_status, context),
                            status_area=check_status_area,
                        )
                    if job["kind"] == JobKind.REPORT and job["params"].get("terminology"):
                        from brofessor.features.reports import accepted_terminology

                        with ui_layout.section(
                            t("Accepted terminology"), job["id"] + EditorSuffix.TERMS
                        ):
                            for term in accepted_terminology(
                                workspace, job["params"]["terminology"], job["params"]["language"]
                            ):
                                st.text(f"{term['term']} ({term['sense']}): {term['translation']}")
                    if job["kind"] in TRANSLATION_JOB_KINDS:
                        from brofessor.interfaces.web.components import (
                            translation as ui_translation,
                        )

                        ui_translation.controls(
                            workspace, job, draft, saved_draft, t, context.open_result
                        )
                    if job["kind"] in (JobKind.ASK, JobKind.REPORT):
                        if not saved_draft:
                            st.caption(
                                t(
                                    "Evidence below belongs to saved revision {revision}.",
                                    revision=draft["revision"],
                                )
                            )
                        evidence_status = draft["data"].get(
                            "evidence_status", EvidenceStatus.SUPPORTED
                        )
                        if evidence_status == EvidenceStatus.CONFLICTING_EVIDENCE:
                            st.warning(
                                t(
                                    "Sources contain conflicting evidence. Review both positions below."
                                )
                            )
                        elif evidence_status == EvidenceStatus.INSUFFICIENT_EVIDENCE:
                            st.info(
                                t("The available evidence is insufficient to establish an answer.")
                            )
                        if job["kind"] == JobKind.ASK and "quotes" not in draft["data"]:
                            st.caption(
                                t(
                                    "This older answer has source references but no verified exact quotes."
                                )
                            )
                        evidence = service.answer_evidence(workspace, job["id"], draft["revision"])
                        if evidence:
                            with ui_layout.section(
                                t(
                                    "Answer sources"
                                    if job["kind"] == JobKind.ASK
                                    else "Report sources"
                                ),
                                job["id"] + EditorSuffix.SOURCES,
                            ):
                                for item in evidence:
                                    ui_layout.heading(item["source"], level=4)
                                    st.caption(item["locator"])
                                    for quote in item["quotes"]:
                                        st.text(quote)
                                    with st.expander(t("Original fragment")):
                                        st.text(item["text"])
                    if job["kind"] == JobKind.ASK:
                        if not saved_draft:
                            st.caption(
                                t(
                                    "Save or load the latest answer before saving a note or asking a follow-up."
                                )
                            )
                        ready_answer = saved_draft and job["status"] == JobStatus.SUCCEEDED
                        note = workspace.note(service.answer_note_id(job["id"], draft["revision"]))
                        if note:
                            if st.button(
                                t(
                                    "Open saved note · revision {revision}",
                                    revision=draft["revision"],
                                ),
                                key=f"open-answer-note-{job['id']}",
                            ):
                                st.session_state[
                                    project_key(workspace.path, ProjectKey.SELECTED_NOTE)
                                ] = note["id"]
                                st.session_state[NAVIGATE_KEY] = "notes"
                                st.rerun()
                        elif st.button(
                            t("Save answer as note"),
                            key=f"answer-note-{job['id']}",
                            disabled=not ready_answer,
                        ):
                            try:
                                service.note_from_answer(
                                    workspace, job["id"], revision=draft["revision"]
                                )
                                st.rerun()
                            except ValueError as error:
                                st.error(t("Could not save note: {error}", error=error))
                        with ui_layout.section(
                            t("Ask a follow-up"), job["id"] + EditorSuffix.FOLLOW_UP
                        ):
                            st.caption(
                                t(
                                    "Uses this answer's sources and the task's text provider: {provider}.",
                                    provider=model_choices["provider"],
                                )
                            )
                            context.connection_notice(
                                model_choices["provider"], model_choices.get("ollama_address")
                            )
                            follow_key = f"editor:{workspace.path}:{job['id']}:follow-up"
                            follow_text = st.text_area(t("Follow-up question"), key=follow_key)
                            follow_language = st.selectbox(
                                t("Follow-up language"),
                                widget_options(list(ui_language.LANGUAGE_NAMES)),
                                index=list(ui_language.LANGUAGE_NAMES).index(
                                    job["params"]["language"]
                                )
                                if follow_key + EditorSuffix.LANGUAGE not in st.session_state
                                else None,
                                format_func=ui_language.LANGUAGE_NAMES.__getitem__,
                                key=follow_key + EditorSuffix.LANGUAGE,
                            )
                            if st.button(
                                t("Submit follow-up"),
                                key=f"follow-submit-{job['id']}",
                                disabled=not ready_answer or not follow_text.strip(),
                            ):
                                try:
                                    fingerprint = hashlib.sha256(
                                        json.dumps(
                                            [
                                                job["id"],
                                                draft["revision"],
                                                follow_text,
                                                follow_language,
                                            ]
                                        ).encode()
                                    ).hexdigest()
                                    child = service.follow_up(
                                        workspace,
                                        job["id"],
                                        follow_text,
                                        title="",
                                        revision=draft["revision"],
                                        language=follow_language,
                                        request_key=f"follow-up:{fingerprint}",
                                    )
                                    context.open_result(child["id"])
                                    st.rerun()
                                except (OSError, ValueError) as error:
                                    st.error(t("Could not submit the job: {error}", error=error))
                    if job["kind"] == JobKind.PODCAST_SERIES:
                        if draft["data"]["terms"]:
                            with ui_layout.section(
                                t("Shared terminology"), job["id"] + EditorSuffix.TERMS
                            ):
                                for term in draft["data"]["terms"]:
                                    ui_content.prose(f"{term['term']}: {term['meaning']}")
                        with ui_layout.section(
                            t("Prepare episode"), job["id"] + ":episode", expanded=True
                        ):
                            revision = st.session_state[ui_content.editor_key(workspace, job["id"])]
                            plan = (
                                draft
                                if revision == draft["revision"]
                                else workspace.draft(job["id"], revision)
                            )
                            series_actions(context, job, plan, saved_draft, group)
                    if job["kind"] == JobKind.PODCAST:
                        ui_script_checks.show(
                            workspace,
                            job,
                            st.session_state[ui_content.editor_key(workspace, job["id"])],
                            saved_draft,
                            t,
                            partial(job_status, context),
                            status_area=check_status_area,
                        )
                published = workspace.artifacts(job["id"])
                with output_area or st.container():
                    if (
                        job["kind"] == JobKind.RENDER_AUDIOBOOK
                        and job["status"] == JobStatus.SUCCEEDED
                    ):
                        book_audio = next((a for a in published if a["kind"] == "audio"), None)
                        if book_audio:
                            chapters = book_audio["metadata"]["chapters"]
                            index = st.selectbox(
                                t("Play chapter"),
                                widget_options(range(len(chapters))),
                                format_func=lambda i: chapters[i]["title"],
                                key="audiobook-chapter:" + job["id"],
                            )
                            st.audio(
                                str(service.artifact_path(workspace, book_audio["path"])),
                                format="audio/mpeg",
                                start_time=int(chapters[index]["start_seconds"]),
                            )
                    for artifact in [
                        a
                        for a in published
                        if a["kind"] != "json" and (job["id"] == rendered or not renders)
                    ]:
                        path = service.artifact_path(workspace, artifact["path"])
                        if not path.exists():
                            st.error(t("File is missing: {name}", name=path.name))
                            continue
                        if artifact["kind"] == "audio" and job["kind"] != JobKind.RENDER_AUDIOBOOK:
                            st.audio(str(path))
                        metadata = artifact["metadata"]
                        if artifact["kind"] in (ArtifactKind.EPUB, ArtifactKind.PDF):
                            from brofessor.interfaces.web.components import (
                                translation as ui_translation,
                            )

                            ui_translation.file_notes(artifact, t)
                        if "requested_seconds" in metadata:
                            actual = round(metadata["duration_seconds"])
                            target = round(metadata["requested_seconds"])
                            st.caption(
                                t(
                                    "Audio duration {actual} · Target {target}",
                                    actual=f"{actual // 60}:{actual % 60:02d}",
                                    target=f"{target // 60}:{target % 60:02d}",
                                )
                            )
                        if metadata.get("duration_matches") is False:
                            actual = round(metadata["duration_seconds"])
                            target = round(metadata["requested_seconds"])
                            st.warning(
                                t(
                                    "Actual duration {actual}, target {target}. Edit the script to match the target within 10% and keep full episodes between 20 and 60 minutes.",
                                    actual=f"{actual // 60}:{actual % 60:02d}",
                                    target=f"{target // 60}:{target % 60:02d}",
                                )
                            )
                            if "suggested_word_count" in metadata:
                                st.caption(
                                    t(
                                        "Script: {words} words. At the measured pace, about {suggested} words would match the target. This is an editing estimate.",
                                        words=metadata["script_words"],
                                        suggested=metadata["suggested_word_count"],
                                    )
                                )
                        elif metadata.get("warning"):
                            st.warning(t("Audio warning: {warning}", warning=metadata["warning"]))
                        st.download_button(
                            t("Download {name}", name=path.name),
                            path.read_bytes(),
                            file_name=path.name,
                            key=f"download-{job['id']}-{path.name}",
                            on_click="ignore",
                        )

                with details_area:
                    if job["id"] == selected:
                        detail_job = (
                            workspace.job(job["params"]["draft_job_id"])
                            if job["params"].get("draft_job_id")
                            else job
                        )
                        details = service.task_details(workspace, detail_job["id"])
                        with (
                            ui_layout.section(
                                t("Task details and reading coverage"), job["id"] + ":details"
                            )
                            if details
                            else st.container()
                        ):
                            if details.get("request"):
                                ui_layout.heading(t("Original request"), level=4)
                                ui_content.prose(details["request"])
                            if details.get("selected_sources"):
                                ui_layout.heading(t("Selected sources"), level=4)
                                for source in details["selected_sources"]:
                                    st.text(source["name"])
                                st.caption(
                                    t("Selection does not mean the sources have already been read.")
                                )
                            navigation = details.get(NAVIGATION_KEY)
                            if navigation:
                                ui_layout.heading(t("Documents selected during this task"), level=4)
                                st.dataframe(
                                    list(navigation["documents"].values()), hide_index=True
                                )
                                if navigation.get("verification", {}).get("exhaustive"):
                                    st.caption(
                                        t(
                                            "All extractable text in the requested scope was read: {count} documents.",
                                            count=navigation["verification"]["documents"],
                                        )
                                    )
                                else:
                                    st.caption(
                                        t(
                                            "Other documents in the directory may not have been read."
                                        )
                                    )
                                if navigation.get("issues"):
                                    st.dataframe(navigation["issues"], hide_index=True)
                                with st.expander(t("Source navigation history")):
                                    st.json(navigation["steps"])
                            coverage = details.get("coverage")
                            if coverage and coverage.get("units"):
                                if coverage.get("mode") == "retrieved":
                                    st.info(
                                        t(
                                            "This answer uses search-selected original fragments. Other fragments were not read; missing matches do not prove absence."
                                        )
                                    )
                                if coverage.get("series"):
                                    st.caption(t("Reading notes reused from the series plan."))
                                st.caption(
                                    t(
                                        "Read {read} of {total} fragments · Excluded {excluded} · Cited {cited}",
                                        read=coverage["count"],
                                        total=len(coverage["units"]) - len(coverage["excluded"]),
                                        excluded=len(coverage["excluded"]),
                                        cited=coverage["cited_count"],
                                    )
                                )
                                with st.expander(t("Reading coverage")):
                                    if coverage.get("queries"):
                                        ui_layout.heading(t("Search queries"), level=4)
                                        for query_text in coverage["queries"]:
                                            st.text(query_text)
                                    st.caption(
                                        t(
                                            "Reading coverage does not guarantee that every fact is in the task."
                                        )
                                    )
                                    st.dataframe(
                                        [
                                            {
                                                t("Reading status"): t(
                                                    {
                                                        ReadingStatus.READ: "Read",
                                                        ReadingStatus.PENDING: "Pending",
                                                        ReadingStatus.EXCLUDED: "Excluded",
                                                        ReadingStatus.NOT_SELECTED: "Not selected by search",
                                                    }[unit["status"]]
                                                ),
                                                t("Cited in task"): unit["cited"],
                                                t("Source"): unit["source"],
                                                t("Fragment"): unit["locator"],
                                                "ID": unit["id"],
                                                t("Exclusion reason"): t("No text extracted")
                                                if unit["reason"] == "empty"
                                                else t("Not selected by search")
                                                if unit["reason"] == "not_selected_by_search"
                                                else unit["reason"],
                                            }
                                            for unit in coverage["units"]
                                        ],
                                        hide_index=True,
                                    )
                with history_area:
                    with (
                        ui_layout.section(
                            t("Saved versions" if draft else "Output details"),
                            job["id"] + EditorSuffix.HISTORY,
                        )
                        if draft or any(a["kind"] == "json" for a in published)
                        else st.container()
                    ):
                        for artifact in [a for a in published if a["kind"] == "json"]:
                            path = service.artifact_path(workspace, artifact["path"])
                            if path.is_file():
                                st.download_button(
                                    t("Download {name}", name=path.name),
                                    path.read_bytes(),
                                    file_name=path.name,
                                    key=f"download-{job['id']}-{path.name}",
                                    on_click="ignore",
                                )
                        if draft:
                            history_key = ui_content.editor_key(workspace, job["id"])
                            revision = st.selectbox(
                                t("Saved revision"),
                                widget_options(range(1, draft["revision"] + 1)),
                                index=draft["revision"] - 1
                                if history_key + EditorSuffix.HISTORY not in st.session_state
                                else None,
                                key=history_key + EditorSuffix.HISTORY,
                            )
                            if st.button(
                                t("Read saved revision"), key=history_key + ":show-history"
                            ):
                                st.session_state[history_key + EditorSuffix.SHOWING_HISTORY] = (
                                    revision
                                )
                            if (
                                st.session_state.get(history_key + EditorSuffix.SHOWING_HISTORY)
                                == revision
                            ):
                                previous = workspace.draft(job["id"], revision)
                                if job["kind"] == JobKind.ASK:
                                    ui_content.prose(previous["data"]["answer"])
                                else:
                                    ui_content.preview(
                                        previous["data"],
                                        job["kind"],
                                        history_key + f":history:{revision}",
                                        t,
                                        workspace,
                                        job_id=job["id"],
                                    )
        with utilities_area:
            if not progress_first:
                job_status(context, progress_target)
            ui_settings.task_models(workspace, by_id[selected], t)
            with ui_layout.section(t("Task operations"), selected + ":operations"):
                if draft and job["kind"] != JobKind.AUDIOBOOK:
                    ui_settings.regenerate_controls(
                        workspace, job, draft, saved_draft, t, context.open_result
                    )
                operations = [
                    job for job in all_jobs if tasks.root_job(job, by_id) == selected_root
                ]
                operation_id = st.selectbox(
                    t("Operation"),
                    widget_options([job["id"] for job in operations]),
                    key=project_key(workspace.path, ProjectKey.OPERATION, selected_root),
                    format_func=lambda value: (
                        t(JOB_LABELS[by_id[value]["kind"]])
                        + " · "
                        + t(STATUS_LABELS[by_id[value]["status"]])
                        + " · "
                        + value
                    ),
                )
                if operation_id != progress_target:
                    job_status(context, operation_id, scope="operation:")
                st.json(by_id[operation_id]["params"])
