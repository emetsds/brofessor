"""Fixed, inspectable workflows with a checkpoint per accepted model result."""

import hashlib
import json
import math
from pathlib import Path
from typing import Final

from brofessor import prompts
from brofessor.contracts.content import ArtifactKind, ContentLanguage, Speaker, UnitStatus
from brofessor.contracts.jobs import (
    RETRIEVAL_JOB_KINDS,
    SUPPORTED_JOB_KINDS,
    TEXT_JOB_KINDS,
    TRANSLATION_JOB_KINDS,
    JobKind,
    JobRecord,
    StageId,
)
from brofessor.contracts.text import DEFAULT_OLLAMA_ADDRESS, DEFAULT_OLLAMA_PORT, TextProvider
from brofessor.features.podcasts.series import EVIDENCE_FILENAME
from brofessor.features.sources import reading
from brofessor.features.sources.reading import ReadingStatus
from brofessor.infrastructure.formats.audio import AUDIO_METADATA_SUFFIX
from brofessor.infrastructure.storage.workspace import (
    AUDIO_SEGMENTS_DIRECTORY,
    JOBS_DIRECTORY,
    Workspace,
    atomic_json,
)
from brofessor.models import Podcast, Slides, validate_citations
from brofessor.prompts import ids as prompt_ids

MODEL_RESULT_FILENAME: Final = "model.json"


def execute(workspace: Workspace, job: JobRecord, cancelled=lambda: False):
    if job["kind"] in TEXT_JOB_KINDS:
        with prompts.use_snapshot(job["params"].get(prompts.SNAPSHOT_KEY)):
            return _execute(workspace, job, cancelled)
    return _execute(workspace, job, cancelled)


def _execute(workspace: Workspace, job: JobRecord, cancelled):
    from brofessor.features.podcasts import series
    from brofessor.infrastructure.text import runners as executors

    if job["kind"] not in SUPPORTED_JOB_KINDS:
        raise ValueError(f"Unsupported job kind: {job['kind']}")
    params = job["params"]
    folder = workspace.path / JOBS_DIRECTORY / job["id"]
    folder.mkdir(parents=True, exist_ok=True)

    def check():
        if cancelled():
            raise executors.CancelledError("Cancelled")

    def progress(value):
        from brofessor.application.progress import canonical

        previous = workspace.job(job["id"])["progress"]
        if canonical(value.get("stage")) == canonical(previous.get("stage")) and previous.get(
            "reused_checkpoints"
        ):
            value = {"reused_checkpoints": previous["reused_checkpoints"], **value}
        workspace.update_job(job["id"], progress=value)

    if job["kind"] == JobKind.AUDIOBOOK:
        from brofessor.features.books.audiobooks import prepare

        prepare(workspace, job, check, progress)
        return
    if job["kind"] == JobKind.RENDER_AUDIOBOOK:
        from brofessor.features.books.audiobooks import render

        render(workspace, job, cancelled, progress, check)
        return

    if job["kind"] == JobKind.DOWNLOAD_OLLAMA_MODEL:
        from brofessor.application.maintenance import pull_ollama

        result = pull_ollama(params, cancelled=cancelled, progress=progress)
        check()
        output = folder / MODEL_RESULT_FILENAME
        atomic_json(output, result)
        workspace.add_artifact(job["id"], output, ArtifactKind.JSON, result)
        return

    if job["kind"] == JobKind.DOWNLOAD_MODEL:
        from brofessor.infrastructure.speech.catalogue import download

        result = download(
            params.get("model_spec", params["model"]), cancelled=cancelled, progress=progress
        )
        output = folder / MODEL_RESULT_FILENAME
        atomic_json(output, result)
        workspace.add_artifact(job["id"], output, ArtifactKind.JSON, result)
        return

    def generate(prompt, schema, citation_scope=None, validate=None, *, timeout=600):
        check()
        ollama_address = (
            executors.ollama_address_for_job(params)
            if params["provider"] == TextProvider.OLLAMA
            else DEFAULT_OLLAMA_ADDRESS
        )
        identity = {
            "prompt": prompt,
            "schema": schema.model_json_schema(),
            "provider": params["provider"],
            "model": params["model"],
        }
        if prompts.SNAPSHOT_KEY in params:
            # Historical runs keep their original checkpoint keys. New runs identify
            # every instruction actually sent, including the runner's message framing.
            identity["messages"] = prompts.messages(identity.pop("prompt"), params["provider"])
        if params["provider"] == TextProvider.OLLAMA:
            if "ollama_address" in params:
                identity["ollama_address"] = ollama_address
            elif params.get("ollama_port", DEFAULT_OLLAMA_PORT) != DEFAULT_OLLAMA_PORT:
                identity["ollama_port"] = params["ollama_port"]
        fingerprint = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        checkpoint = folder / "checkpoints" / f"{fingerprint}.json"
        if checkpoint.exists():
            result = json.loads(checkpoint.read_text())
            current = workspace.job(job["id"])["progress"]
            progress({**current, "reused_checkpoints": current.get("reused_checkpoints", 0) + 1})
        else:
            current = workspace.job(job["id"])["progress"]
            progress({"stage": StageId.PREPARING, **current, "waiting_for_model": True})
            result = executors.generate(
                prompt,
                schema.model_json_schema(),
                params["provider"],
                params["model"],
                ollama_address=ollama_address,
                workdir=folder,
                cancelled=cancelled,
                timeout=timeout,
            )
        value = schema.model_validate(result).model_dump()
        validate_citations(value, allowed if citation_scope is None else citation_scope)
        from brofessor.features.reports import Report
        from brofessor.features.studies import FeedbackBatch, StudySet

        if (
            issubclass(schema, Podcast)
            or schema in (Slides, series.Series, Report, StudySet, FeedbackBatch)
        ) and value["language"] != params["language"]:
            raise ValueError("Generated language does not match the request")
        if schema is Slides and len(value["slides"]) != params["slide_count"]:
            raise ValueError("Generated slide count does not match the request")
        if validate:
            validate(value)
        check()
        atomic_json(checkpoint, value)
        current = workspace.job(job["id"])["progress"]
        progress({**current, "waiting_for_model": False})
        return value

    if job["kind"] in (
        JobKind.TRANSLATE_EPUB,
        JobKind.RENDER_EPUB,
        JobKind.TRANSLATE_PDF,
        JobKind.RENDER_PDF,
    ):
        from brofessor.features.books import translation as book_translation

        allowed = set()
        if job["kind"] in TRANSLATION_JOB_KINDS:
            book_translation.run(workspace, job, generate, progress, check)
        else:
            progress({"stage": StageId.RENDERING})
            saved = workspace.draft(params["draft_job_id"], params["revision"])
            if saved is None:
                raise ValueError("Choose a saved translation revision")
            book_translation.export(
                workspace, job, book_translation.source_book(workspace, params, check), saved, check
            )
        return

    if job["kind"] == JobKind.REVIEW_STUDY:
        from brofessor.features import studies
        from brofessor.features.sources import navigation as source_navigation

        allowed = {
            u["id"]
            for u in source_navigation.units(workspace, job)
            if u["status"] == UnitStatus.READY
        }
        studies.review(workspace, job, generate, progress, check)
        return

    if job["kind"] == JobKind.CHECK_PODCAST:
        from brofessor.features.podcasts import checks as script_checks
        from brofessor.features.sources import navigation as source_navigation

        allowed = {
            u["id"]
            for u in source_navigation.units(workspace, job)
            if u["status"] == UnitStatus.READY
        }
        script_checks.run(workspace, job, generate, progress, check)
        return

    if job["kind"] in (JobKind.RENDER_SLIDES, JobKind.RENDER_PODCAST, JobKind.PREVIEW_TURN):
        from brofessor.infrastructure.formats.audio import render_audio, render_slides

        draft = workspace.draft(params["draft_job_id"], params["revision"])
        if draft is None:
            raise ValueError("The requested draft revision no longer exists")
        check()
        if job["kind"] == JobKind.RENDER_SLIDES:
            progress({"stage": StageId.RENDERING})
            from brofessor.features.sources import navigation as source_navigation

            source_job = workspace.job(params["draft_job_id"])
            names = source_navigation.names(workspace, source_job)
            labels = {
                unit["id"]: f"{names[unit['source_id']]} · {unit['locator']}"
                for unit in source_navigation.units(workspace, source_job)
            }
            output = render_slides(
                draft["data"], folder / "presentation.pptx", source_labels=labels
            )
            check()
            workspace.add_artifact(
                job["id"], Path(output), ArtifactKind.PPTX, {"revision": draft["revision"]}
            )
        else:
            segments = workspace.path / AUDIO_SEGMENTS_DIRECTORY
            model_options = {}
            if "model_spec" in params:
                from brofessor.infrastructure.speech.catalogue import get
                from brofessor.infrastructure.speech.references import resolve

                spec = get(params["model_spec"])
                if spec.get("references"):
                    spec["references"] = resolve(workspace.path, spec["references"])
                model_options["model_spec"] = spec
            plan = draft["data"]
            preview = job["kind"] == JobKind.PREVIEW_TURN
            if preview:
                plan = {**plan, "turns": [plan["turns"][params["turn"] - 1]]}
            output = folder / ("turn.mp3" if preview else "podcast.mp3")
            result = render_audio(
                plan,
                output,
                segment_dir=segments,
                model=params["model"],
                **model_options,
                cancelled=cancelled,
                progress=progress,
            )
            check()
            if preview:
                result.update(turn=params["turn"], revision=draft["revision"])
            else:
                from brofessor.features.podcasts.writer import duration_feedback

                result.update(
                    duration_feedback(draft["data"], params["minutes"], result["duration_seconds"])
                )
                if not result["duration_matches"]:
                    result["warning"] = (
                        "Duration is outside the target tolerance (10%) or the 20–60 minute episode "
                        "range. Edit the script and render again."
                    )
            atomic_json(output.with_suffix(AUDIO_METADATA_SUFFIX), result)
            workspace.add_artifact(job["id"], Path(result["path"]), ArtifactKind.AUDIO, result)
        return

    from brofessor.features.sources import navigation as source_navigation

    allowed = set()
    if params.get("collections") and not params.get("source_snapshot_job"):
        navigation_conversation = None
        if params.get("conversation"):
            from brofessor.features import questions

            navigation_conversation = questions.history(
                workspace,
                params["conversation"],
                params["source_ids"],
                collections=params["collections"],
            )
        source_navigation.prepare(
            workspace, job, generate, check, progress, conversation=navigation_conversation
        )
    original_units = source_navigation.units(workspace, job)
    units = [u for u in original_units if u["status"] == UnitStatus.READY]
    names = source_navigation.names(workspace, job)
    allowed = {u["id"] for u in units}
    if not units and job["kind"] not in RETRIEVAL_JOB_KINDS:
        raise ValueError("Sources contain no readable text")
    progress({"stage": StageId.READING})
    series_context = None
    conversation = None
    if "series" in params:
        reference = params["series"]
        parent = workspace.draft(reference["job_id"], reference["revision"])
        if parent is None:
            raise ValueError("The requested series plan revision does not exist")
        plan = series.Series.model_validate(parent["data"]).model_dump()
        validate_citations(plan, allowed)
        if plan["language"] != params["language"]:
            raise ValueError("Series language does not match the episode")
        series_context = series.episode_context(plan, reference["episode"])
        evidence, coverage = series.reading_notes(workspace, reference, folder, allowed)
    elif job["kind"] in RETRIEVAL_JOB_KINDS:
        from brofessor.features import questions

        if params.get("conversation"):
            conversation = questions.history(
                workspace,
                params["conversation"],
                params["source_ids"],
                collections=params.get("collections", []),
            )
        evidence, coverage = questions.prepare(
            [{**u, "source": names[u["source_id"]]} for u in original_units],
            params["focus"],
            generate,
            check,
            progress,
            folder,
            conversation=conversation,
            required_ids=set(source_navigation.report(workspace, job)["units"])
            if params.get("collections")
            else None,
        )
    else:
        evidence, coverage = reading.prepare(
            original_units,
            params["focus"],
            generate,
            check,
            progress,
            folder,
            version=params.get("reading_version", 1),
            names=names,
        )
    if params.get("dialogue_version", 1) >= 4:
        evidence = reading.with_metadata(evidence, original_units, names)
    allowed = {
        citation for item in evidence for citation in item.get("citations", [item.get("id")])
    }
    encoded = json.dumps(evidence, ensure_ascii=False)
    language_name = {ContentLanguage.RU: "Russian", ContentLanguage.EN: "English"}[
        params["language"]
    ]
    instructions = prompts.render(
        prompt_ids.COMMON_MATERIALS,
        language=params["language"],
        language_name=language_name,
        focus=params["focus"],
    )
    navigation = source_navigation.report(workspace, job)
    if navigation and navigation.get("verification"):
        instructions += prompts.render(
            prompt_ids.COMMON_COVERAGE,
            verification=json.dumps(navigation["verification"], ensure_ascii=False),
        )
    base = prompts.render(prompt_ids.COMMON_EVIDENCE, instructions=instructions, evidence=encoded)
    editorial_context = ""
    if job["kind"] == JobKind.PODCAST and params.get("dialogue_version", 1) >= 2:
        editorial_context += prompts.render(prompt_ids.PODCASTS_VOICES)
    if series_context:
        editorial_context += prompts.render(
            prompt_ids.PODCASTS_SERIES_CONTEXT,
            series=json.dumps(series_context, ensure_ascii=False),
        )
    base += editorial_context
    if conversation:
        base += prompts.render(
            prompt_ids.QUESTIONS_CONVERSATION,
            conversation=json.dumps(conversation, ensure_ascii=False),
        )
    if job["kind"] in (JobKind.ASK, JobKind.REPORT, JobKind.STUDY, JobKind.SLIDES):
        progress({"stage": StageId.WRITING})
    if job["kind"] == JobKind.ASK:
        from brofessor.features import questions

        value = questions.write(
            base, evidence, generate, [u for u in units if u["id"] in allowed], params["language"]
        )
    elif job["kind"] == JobKind.STUDY:
        from brofessor.features import studies

        value = studies.write(
            base,
            evidence,
            generate,
            [u for u in units if u["id"] in allowed],
            params["language"],
            params["question_count"],
        )
    elif job["kind"] == JobKind.REPORT:
        from brofessor.features import reports

        if params.get("terminology"):
            terms = reports.accepted_terminology(
                workspace, params["terminology"], params["language"]
            )
            glossary = reading.encoded(terms)
            from brofessor.features.books.terminology import PROMPT_BUDGET

            if len(glossary) > PROMPT_BUDGET:
                raise ValueError("Accepted terminology exceeds the report context budget")
            base += prompts.render(prompt_ids.REPORTS_TERMINOLOGY, glossary=glossary)
        scope = [
            {
                "source": names[source_id],
                "selected_fragments": sum(
                    u["source_id"] == source_id and u["id"] in allowed for u in units
                ),
                "readable_fragments": sum(u["source_id"] == source_id for u in units)
                if source_id in params["source_ids"]
                else None,
            }
            for source_id in dict.fromkeys(u["source_id"] for u in original_units)
        ]
        value = reports.write(
            prompts.render(prompt_ids.REPORTS_SCOPE, base=base, scope=reading.encoded(scope)),
            evidence,
            generate,
            [u for u in units if u["id"] in allowed],
            params["language"],
            params["template"],
        )
    elif job["kind"] == JobKind.SLIDES:
        value = generate(
            prompts.render(prompt_ids.SLIDES_CREATE, base=base, slide_count=params["slide_count"]),
            Slides,
        )
    elif job["kind"] == JobKind.PODCAST_SERIES:
        value = series.write(base, params["episode_count"], params["minutes"], generate, progress)
        atomic_json(folder / EVIDENCE_FILENAME, evidence)
    elif job["kind"] == JobKind.PODCAST:
        if params["minutes"] >= 20:
            from brofessor.features.podcasts import writer as podcasts

            def save_outline(outline):
                output = folder / "outline.json"
                atomic_json(output, outline)
                workspace.add_artifact(
                    job["id"], output, ArtifactKind.JSON, {"role": "episode_outline"}
                )

            def save_section(index, report):
                atomic_json(folder / f"writer-section-{index}.json", report)

            writer_options = {}
            if params.get("dialogue_version", 1) >= 4:
                writer_options = {
                    "writer_context": {
                        "instructions": instructions + editorial_context,
                        "evidence": evidence,
                        "units": original_units,
                        "names": names,
                    },
                    "save_section": save_section,
                }

            value = podcasts.write(
                base,
                params["minutes"],
                params["language"],
                generate,
                progress,
                save_outline,
                target_words=params.get("target_words"),
                dialogue_version=params.get("dialogue_version", 1),
                **writer_options,
            )
        else:
            value = short_podcast(base, params, generate, progress)
    progress({"stage": StageId.VALIDATING})
    if job["kind"] == JobKind.PODCAST:
        value = Podcast.model_validate(value).model_dump()
    check()
    if coverage["mode"] in (
        reading.ReadingMode.DIRECT,
        reading.ReadingMode.RETRIEVED,
        reading.ReadingMode.NAVIGATED,
    ):
        for unit in coverage["units"]:
            if unit["status"] == ReadingStatus.PENDING:
                unit["status"] = ReadingStatus.READ
        reading.save_coverage(folder, coverage)
    progress({"stage": StageId.SAVING})
    existing = workspace.draft(job["id"])
    if existing is None:
        workspace.save_draft(job["id"], value)
    if job["kind"] == JobKind.PODCAST and params.get("auto_audio"):
        from brofessor.application.initial_audio import pin

        pin(workspace, job["id"])
    # Resume must not replace a manually edited draft.
    final_draft = workspace.draft(job["id"])
    draft_path = folder / f"draft-r{final_draft['revision']}.json"
    atomic_json(draft_path, final_draft["data"])
    workspace.add_artifact(
        job["id"], draft_path, ArtifactKind.JSON, {"revision": final_draft["revision"]}
    )
    if job["kind"] == JobKind.REPORT:
        from brofessor.features.reports import publish

        check()
        publish(workspace, job, final_draft)
    progress({"stage": StageId.DRAFT_READY, "read_units": coverage["count"]})


def short_podcast(base, params, generate, progress):
    """Keep the existing preview prompts and checkpoints for jobs below 20 minutes."""
    parts = max(1, math.ceil(params["minutes"] / 5))
    turns = []
    title = ""
    for index in range(parts):
        progress({"stage": StageId.SCRIPT, "completed": index, "total": parts})
        # Initial estimate calibrated with the pinned local preset voices.
        # Measured audio duration remains authoritative; this is not a guarantee.
        words_per_minute = 85 if params["language"] == ContentLanguage.RU else 125
        target_words = round(params["minutes"] * words_per_minute / parts)
        previous = " ".join(turn["text"] for turn in turns[-4:])
        value = generate(
            prompts.render(
                "podcasts/short",
                base=base,
                part_number=index + 1,
                parts=parts,
                target_words=target_words,
                last_part=parts,
                previous=previous,
            ),
            Podcast,
        )
        title = title or value["title"]
        turns.extend(value["turns"])
    value = {"title": title, "language": params["language"], "turns": turns}
    if {t["speaker"] for t in turns} != {Speaker.HOST, Speaker.GUEST}:
        raise ValueError("The podcast must contain both host and guest")
    return value
