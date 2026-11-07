"""User operations shared by the CLI and Streamlit. No frontend imports."""

import hashlib
import json
from pathlib import Path
from typing import cast

from brofessor import prompts
from brofessor.contracts.content import ArtifactKind, ContentLanguage, UnitStatus
from brofessor.contracts.jobs import (
    AUDIO_RENDER_JOB_KINDS,
    PODCAST_JOB_KINDS,
    RETRIEVAL_JOB_KINDS,
    TRANSLATION_JOB_KINDS,
    DraftRecord,
    JobKind,
    JobRecord,
    JobStatus,
)
from brofessor.contracts.text import DEFAULT_OLLAMA_ADDRESS, TEXT_PROVIDERS, TextProvider
from brofessor.features.podcasts.writer import WritingMethod
from brofessor.features.reports import ReportTemplate
from brofessor.features.sources.reading import COVERAGE_FILENAME, ReadingStatus
from brofessor.infrastructure.storage.workspace import JOBS_DIRECTORY, Workspace, atomic_json
from brofessor.infrastructure.text.runners import normalize_ollama_address, validate_ollama_model
from brofessor.models import Answer, Output, Podcast, Slides, validate_citations

_RESULT_OPTIONS: dict[str, dict[str, str | int]] = {
    JobKind.ASK: {},
    JobKind.REPORT: {"template": ReportTemplate.COMPARISON},
    JobKind.STUDY: {"question_count": 6},
    JobKind.PODCAST: {"minutes": 20},
    JobKind.SLIDES: {"slide_count": 8},
    JobKind.PODCAST_SERIES: {"episode_count": 3, "minutes": 20},
    JobKind.TRANSLATE_EPUB: {},
    JobKind.TRANSLATE_PDF: {},
}


def _draft_params(kind, params):
    # Compare requested inputs independently of the writer's frozen settings.
    # Older jobs also stored durations and slide counts for unrelated operations.
    return {
        key: value
        for key, value in params.items()
        if key not in ("target_words", "dialogue_version", "reading_version", prompts.SNAPSHOT_KEY)
        and (key not in ("minutes", "slide_count", "episode_count") or key in _RESULT_OPTIONS[kind])
    }


def _remember_task(workspace: Workspace, job: JobRecord) -> JobRecord:
    from brofessor.application.tasks import record_open

    warning = record_open(workspace, job["id"])
    if warning:
        job = {**job, "notice": warning}
    return job


def _with_models(params, choices):
    from brofessor.infrastructure.text.runners import ollama_address_for_job

    same = params.get("provider") == choices["provider"] and params.get("model") == choices["model"]
    if same and choices["provider"] == TextProvider.OLLAMA:
        same = ollama_address_for_job(params) == choices["ollama_address"]
    if same:
        return params.copy()
    result = {
        k: v
        for k, v in params.items()
        if k not in ("provider", "model", "ollama_address", "ollama_port")
    }
    result.update(provider=choices["provider"], model=choices["model"])
    if (
        choices["provider"] == TextProvider.OLLAMA
        and choices["ollama_address"] != DEFAULT_OLLAMA_ADDRESS
    ):
        result["ollama_address"] = choices["ollama_address"]
    return result


def _text_params(kind, params):
    """A new text run uses today's templates; resume keeps its stored inputs."""
    requested = {key: value for key, value in params.items() if key != prompts.SNAPSHOT_KEY}
    return {**requested, prompts.SNAPSHOT_KEY: prompts.snapshot(kind, requested)}


def _submit_text(workspace, kind, params, request_key=None, **options):
    previous = workspace.job_by_request_key(request_key) if request_key else None
    if previous:

        def plain(value):
            return {key: item for key, item in value.items() if key != prompts.SNAPSHOT_KEY}

        if previous["kind"] != kind or plain(previous["params"]) != plain(params):
            raise ValueError("Request key already belongs to a different operation")
        return workspace.submit(kind, previous["params"], request_key, **options)
    frozen = params if prompts.SNAPSHOT_KEY in params else _text_params(kind, params)
    return workspace.submit(kind, frozen, request_key, **options)


def _submit_draft(workspace, kind, params, request_key, *, model_choices=None):
    from brofessor.application import tasks

    model_choices = (
        tasks.validate_models(kind, model_choices)
        if model_choices
        else tasks.initial_models(kind, params)
    )
    requested = _draft_params(kind, params)
    params = requested.copy()
    originals = (
        kind in PODCAST_JOB_KINDS and params.get("writing_method") == WritingMethod.ORIGINALS
    )
    if kind not in (
        JobKind.ASK,
        JobKind.REPORT,
        JobKind.STUDY,
        JobKind.TRANSLATE_EPUB,
        JobKind.TRANSLATE_PDF,
    ):
        params["reading_version"] = 3 if originals else 2
    if kind == JobKind.PODCAST:
        params["dialogue_version"] = 4 if originals else 3
    if kind == JobKind.PODCAST and params["minutes"] >= 20:
        # Qwen Base with the bundled ExNihilus voices. Frozen at submission so a
        # later calibration cannot change the prompts of a queued or resumed job.
        minutes = params["minutes"]
        lower = max(20, minutes * 0.9)
        upper = min(60, minutes * 1.1)
        # Aim inside the accepted interval at the 20/60-minute boundaries.
        params["target_words"] = round(
            (lower + upper)
            / 2
            * {ContentLanguage.RU: 115, ContentLanguage.EN: 150}[params["language"]]
        )
    try:
        result = _submit_text(
            workspace,
            kind,
            params,
            request_key,
            task_models=model_choices if not params.get("regeneration") else None,
        )
    except ValueError:
        previous = workspace.job_by_request_key(request_key)
        if (
            previous
            and previous["kind"] == kind
            and _draft_params(kind, previous["params"]) == requested
        ):
            result = previous
        else:
            raise
    return _remember_task(workspace, result)


def submit(
    workspace: Workspace,
    kind: str,
    *,
    source_ids=None,
    focus="",
    language=ContentLanguage.RU,
    provider=TextProvider.CODEX,
    model=None,
    ollama_address=None,
    minutes=None,
    slide_count=None,
    episode_count=None,
    speech_model=None,
    writing_method=None,
    glossary=None,
    template=None,
    terminology=None,
    question_count=None,
    translation=None,
    title=None,
    auto_audio=True,
    request_key=None,
    start_worker=True,
) -> JobRecord:
    if type(auto_audio) is not bool:
        raise ValueError("Automatic narration must be true or false")
    if kind == JobKind.AUDIOBOOK:
        from brofessor.features.books.audiobooks import submit as submit_audiobook

        if source_ids is None or len(source_ids) != 1:
            raise ValueError("Choose one imported source for an audiobook")
        if (
            focus
            or any(
                value is not None
                for value in (
                    minutes,
                    slide_count,
                    episode_count,
                    writing_method,
                    glossary,
                    template,
                    terminology,
                    question_count,
                    model,
                    ollama_address,
                )
            )
            or provider != TextProvider.CODEX
        ):
            raise ValueError(
                "An audiobook takes a source, text language, optional saved translation and speech model"
            )
        return submit_audiobook(
            workspace,
            source_ids[0],
            language=language,
            speech_model=speech_model,
            translation=translation,
            title=title,
            request_key=request_key,
            start_worker=start_worker,
        )
    if translation is not None:
        raise ValueError("A saved translation input applies only to an audiobook")
    if kind in TRANSLATION_JOB_KINDS:
        from brofessor.features.books import translation as book_translation

        if focus or any(
            value is not None
            for value in (
                minutes,
                slide_count,
                episode_count,
                speech_model,
                writing_method,
                template,
                terminology,
                question_count,
            )
        ):
            raise ValueError(
                "Book translation takes a source, target language and optional glossary"
            )
        return book_translation.submit(
            workspace,
            kind=kind,
            source_ids=source_ids,
            language=language,
            provider=provider,
            model=model,
            ollama_address=ollama_address,
            glossary=glossary,
            title=title,
            request_key=request_key,
            start_worker=start_worker,
        )
    if glossary is not None:
        raise ValueError("A glossary applies only to book translation")
    if terminology is not None and (kind != JobKind.REPORT or template != ReportTemplate.REFERENCE):
        raise ValueError("Accepted terminology applies only to a topic reference")
    if kind not in _RESULT_OPTIONS:
        raise ValueError("Choose ask, report, podcast, slides or podcast_series")
    if provider not in TEXT_PROVIDERS:
        raise ValueError("Choose codex, claude or ollama")
    if provider == TextProvider.OLLAMA:
        ollama_address = normalize_ollama_address(
            DEFAULT_OLLAMA_ADDRESS if ollama_address is None else ollama_address
        )
        try:
            validate_ollama_model(model)
        except RuntimeError as error:
            raise ValueError(str(error)) from error
    elif ollama_address is not None:
        raise ValueError("Only Ollama uses a server address")
    if language not in (ContentLanguage.RU, ContentLanguage.EN):
        raise ValueError("Choose ru or en")
    options = _RESULT_OPTIONS[kind].copy()
    for key, value in (
        ("minutes", minutes),
        ("slide_count", slide_count),
        ("episode_count", episode_count),
        ("template", template),
        ("question_count", question_count),
    ):
        if value is not None:
            if key not in options:
                raise ValueError(f"{key} does not apply to {kind}")
            options[key] = value
    if kind == JobKind.REPORT:
        from brofessor.features.reports import TEMPLATES

        if options["template"] not in TEMPLATES:
            raise ValueError(
                "Choose comparison, guide, reference or arguments as the report template"
            )
    if kind == JobKind.STUDY and (
        type(options["question_count"]) is not int or not 2 <= options["question_count"] <= 12
    ):
        raise ValueError("Choose 2–12 practice questions")
    if "minutes" in options and (
        type(options["minutes"]) is not int or not 1 <= options["minutes"] <= 60
    ):
        raise ValueError("Podcast duration must be 1–60 whole minutes (under 20 is preview)")
    if kind == JobKind.SLIDES and (
        type(options["slide_count"]) is not int or not 1 <= options["slide_count"] <= 40
    ):
        raise ValueError("Slide count must be a whole number from 1 to 40")
    if kind == JobKind.PODCAST_SERIES and (
        type(options["episode_count"]) is not int
        or not 2 <= options["episode_count"] <= 12
        or cast(int, options["minutes"]) < 20
    ):
        raise ValueError("Series need 2–12 episodes, each 20–60 minutes")
    if writing_method not in (None, WritingMethod.CLASSIC, WritingMethod.ORIGINALS):
        raise ValueError("Choose classic or originals as the writing method")
    if writing_method is not None and (
        kind not in PODCAST_JOB_KINDS or cast(int, options["minutes"]) < 20
    ):
        raise ValueError("A writing method applies only to podcasts of at least twenty minutes")
    from brofessor.features.sources import collections

    available = collections.choices(workspace)
    ids = source_ids if source_ids is not None else [s["id"] for s in available]
    known = {s["id"] for s in available}
    if not ids or not set(ids) <= known:
        raise ValueError("Select existing sources before starting a job")
    if kind in RETRIEVAL_JOB_KINDS and not focus.strip():
        raise ValueError("A question or report goal is required")
    params = {
        "source_ids": [
            identifier
            for identifier in ids
            if not identifier.startswith(collections.COLLECTION_ID_PREFIX)
        ],
        "focus": focus,
        "language": language,
        "provider": provider,
        "model": model,
        **options,
    }
    if terminology is not None:
        from brofessor.features.reports import accepted_terminology

        accepted_terminology(workspace, terminology, language)
        params["terminology"] = terminology
    roots = [r for r in collections.registered(workspace) if r["id"] in ids]
    if roots:
        params["collections"] = roots
    if writing_method == WritingMethod.ORIGINALS:
        params["writing_method"] = writing_method
    # Omit the default to preserve pre-address loopback request identities.
    if provider == TextProvider.OLLAMA and ollama_address != DEFAULT_OLLAMA_ADDRESS:
        params["ollama_address"] = ollama_address
    if speech_model is not None and kind not in PODCAST_JOB_KINDS:
        raise ValueError("A speech model applies only to a podcast or series")
    from brofessor.application.tasks import initial_models

    choices = initial_models(kind, params, speech_model=speech_model)
    from brofessor.application import tasks

    if title is not None:
        params["task_title"] = tasks.initial_title(kind, focus, title)
    if kind in PODCAST_JOB_KINDS:
        from brofessor.infrastructure.speech.catalogue import get

        previous = workspace.job_by_request_key(request_key) if request_key else None
        # Repeating a pre-policy request must not add work to that historical task.
        if previous is None or "auto_audio" in previous["params"]:
            params["auto_audio"] = get(choices["speech_model"]) if auto_audio else False
    result = _submit_draft(workspace, kind, params, request_key, model_choices=choices)
    if start_worker:
        from brofessor.application.worker import ensure_worker

        ensure_worker(workspace)
    return result


def edit_draft(
    workspace: Workspace, job_id: str, data: dict, expected_revision: int
) -> DraftRecord:
    from brofessor.features.books.audiobooks import Audiobook
    from brofessor.features.podcasts.series import Series
    from brofessor.features.reports import Report
    from brofessor.features.studies import StudySet

    job = workspace.job(job_id)
    if job["kind"] in TRANSLATION_JOB_KINDS:
        from brofessor.features.books import translation as book_translation

        return book_translation.edit(workspace, job_id, data, expected_revision)
    schemas: dict[str, type[Output]] = {
        JobKind.ASK: Answer,
        JobKind.REPORT: Report,
        JobKind.STUDY: StudySet,
        JobKind.AUDIOBOOK: Audiobook,
        JobKind.PODCAST: Podcast,
        JobKind.SLIDES: Slides,
        JobKind.PODCAST_SERIES: Series,
    }
    schema = schemas.get(job["kind"])
    if schema is None:
        raise ValueError("This job has no editable draft")
    value = schema.model_validate(data).model_dump()
    from brofessor.features.sources import navigation as source_navigation

    allowed = {u["id"] for u in source_navigation.units(workspace, job)}
    validate_citations(value, allowed)
    if job["kind"] == JobKind.ASK:
        from brofessor.features.questions import validate_answer

        previous = workspace.draft(job_id)
        require_quotes = "quotes" in data or (previous is not None and "quotes" in previous["data"])
        validate_answer(
            value, source_navigation.units(workspace, job), require_quotes=require_quotes
        )
        if not require_quotes and "quotes" not in data:
            value.pop("quotes")  # Preserve legacy answers without claiming quote verification.
    elif job["kind"] == JobKind.REPORT:
        from brofessor.features.reports import accepted_terminology, validate

        validate(value, source_navigation.units(workspace, job))
        if job["params"].get("terminology"):
            accepted_terminology(workspace, job["params"]["terminology"], value["language"])
    elif job["kind"] == JobKind.STUDY:
        from brofessor.features.studies import validate_set

        validate_set(value, source_navigation.units(workspace, job))
    elif job["kind"] == JobKind.AUDIOBOOK:
        first = workspace.draft(job_id, 1)
        assert first is not None  # The editable audiobook already has its initial revision.
        value["user_edited"] = value["chapters"] != first["data"]["chapters"]
    saved = workspace.save_draft(job_id, value, expected_revision)
    output = workspace.path / JOBS_DIRECTORY / job_id / f"draft-r{saved['revision']}.json"
    atomic_json(output, saved["data"])
    workspace.add_artifact(job_id, output, ArtifactKind.JSON, {"revision": saved["revision"]})
    if job["kind"] == JobKind.REPORT:
        from brofessor.features.reports import publish

        publish(workspace, job, saved)
    return saved


def check_script(workspace, job_id, *, revision=None, request_key=None, start_worker=True):
    """Review a saved revision independently of rendering; never replace its text."""
    from brofessor.application.tasks import models

    original = workspace.job(job_id)
    if original["kind"] != JobKind.PODCAST:
        raise ValueError("Choose a podcast script")
    draft = workspace.draft(job_id, revision)
    if draft is None:
        raise ValueError("Choose a saved script revision")
    value = Podcast.model_validate(draft["data"])
    previous = workspace.job_by_request_key(request_key) if request_key else None
    if previous:
        if (
            previous["kind"] != JobKind.CHECK_PODCAST
            or previous["params"]["draft_job_id"] != job_id
            or previous["params"]["revision"] != draft["revision"]
        ):
            raise ValueError("Request key already belongs to a different operation")
        result = previous
    else:
        choices = models(workspace, job_id)["data"]
        params = _with_models(
            {"provider": original["params"]["provider"], "model": original["params"].get("model")},
            choices,
        )
        params.update(
            draft_job_id=job_id,
            revision=draft["revision"],
            source_ids=original["params"]["source_ids"],
            source_snapshot_job=original["id"],
            language=value.language,
            check_version=1,
        )
        params = _text_params(JobKind.CHECK_PODCAST, params)
        key = (
            request_key
            or "script-check:"
            + hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()
        )
        result = _submit_text(workspace, JobKind.CHECK_PODCAST, params, key)
    if start_worker:
        from brofessor.application.worker import ensure_worker

        ensure_worker(workspace)
    return result


def follow_up(
    workspace,
    job_id,
    question,
    *,
    title=None,
    revision=None,
    language=None,
    request_key=None,
    start_worker=True,
):
    from brofessor.features import questions

    if not question.strip():
        raise ValueError("A question is required")
    parent, draft = questions.saved_answer(workspace, job_id, revision)
    params = {
        key: value
        for key, value in parent["params"].items()
        if key not in ("conversation", "conversation_omitted")
    }
    params["focus"] = question
    if "task_title" in params or title is not None:
        from brofessor.application.tasks import initial_title

        params["task_title"] = initial_title(JobKind.ASK, question, title or "")
    params["language"] = language if language is not None else params["language"]
    if params["language"] not in (ContentLanguage.RU, ContentLanguage.EN):
        raise ValueError("Choose ru or en")
    references = [
        *parent["params"].get("conversation", []),
        {"job_id": job_id, "revision": draft["revision"]},
    ]
    omitted = parent["params"].get("conversation_omitted", 0)
    while True:
        try:
            questions.history(
                workspace,
                references,
                params["source_ids"],
                collections=params.get("collections", []),
            )
            break
        except questions.HistoryLimit:
            if len(references) == 1:
                raise
            references.pop(0)
            omitted += 1
    params["conversation"] = references
    if omitted:
        params["conversation_omitted"] = omitted
    from brofessor.application.tasks import ModelOrigin, models

    choices = {**models(workspace, job_id)["data"], "origin": ModelOrigin.PARENT}
    # A retry keeps the first model snapshot even after the task's preferences change.
    previous = workspace.job_by_request_key(request_key) if request_key else None
    ignore = {"provider", "model", "ollama_address", "ollama_port"}
    if (
        previous
        and previous["kind"] == JobKind.ASK
        and {
            k: v
            for k, v in _draft_params(JobKind.ASK, previous["params"]).items()
            if k not in ignore
        }
        == {k: v for k, v in _draft_params(JobKind.ASK, params).items() if k not in ignore}
    ):
        result = _remember_task(workspace, previous)
    else:
        result = _submit_draft(
            workspace,
            JobKind.ASK,
            _with_models(params, choices),
            request_key,
            model_choices=choices,
        )
    if start_worker:
        from brofessor.application.worker import ensure_worker

        ensure_worker(workspace)
    return result


def save_note(workspace, data, *, note_id=None, expected_revision=0):
    from brofessor.models import Note

    value = Note.model_validate(data).model_dump()
    validate_citations(
        value, {u["id"] for u in workspace.units() if u["status"] == UnitStatus.READY}
    )
    if note_id is None:
        if expected_revision != 0:
            raise ValueError("New notes start at revision 1")
        return workspace.create_note(value)
    return workspace.save_note(note_id, value, expected_revision)


def answer_note_id(job_id, revision):
    return hashlib.sha256(f"answer:{job_id}:r{revision}".encode()).hexdigest()[:16]


def note_from_answer(workspace, job_id, *, revision=None, title=None):
    from brofessor.features.questions import saved_answer
    from brofessor.models import Note

    job, draft = saved_answer(workspace, job_id, revision)
    origin = {"job_id": job_id, "revision": draft["revision"]}
    note_id = answer_note_id(job_id, draft["revision"])
    value = Note(
        title=title if title is not None else job["params"]["focus"][:120],
        text=draft["data"]["answer"],
        citations=draft["data"]["citations"],
    ).model_dump()
    validate_citations(
        value, {u["id"] for u in workspace.units() if u["status"] == UnitStatus.READY}
    )
    result = workspace.create_note(value, note_id=note_id, origin=origin)
    if result["origin"] != origin:
        raise ValueError("Note ID collision")
    return result


def note_evidence(workspace, note_id, revision=None):
    note = workspace.note(note_id, revision)
    if note is None:
        raise ValueError("The requested note revision does not exist")
    names = {s["id"]: s["name"] for s in workspace.sources()}
    units = {u["id"]: u for u in workspace.units()}
    return [
        {
            "citation": key,
            "source": names[units[key]["source_id"]],
            "locator": units[key]["locator"],
            "text": units[key]["text"],
        }
        for key in note["data"]["citations"]
    ]


def question_context(workspace, job_id):
    from brofessor.features.questions import history

    job = workspace.job(job_id)
    if job["kind"] != JobKind.ASK:
        raise ValueError("Choose a question job")
    return {
        "turns": history(
            workspace,
            job["params"].get("conversation", []),
            job["params"]["source_ids"],
            collections=job["params"].get("collections", []),
        ),
        "omitted": job["params"].get("conversation_omitted", 0),
    }


def series_episode(workspace, series_job_id, number, *, revision=None, start_worker=True):
    """Pin one saved plan revision; repeated requests reuse the same episode job."""
    from brofessor.features.podcasts.series import Series, episode_context

    parent = workspace.job(series_job_id)
    if parent["kind"] != JobKind.PODCAST_SERIES or parent["status"] != JobStatus.SUCCEEDED:
        raise ValueError("Choose a completed podcast series plan")
    draft = workspace.draft(series_job_id, revision)
    if draft is None:
        raise ValueError("The requested series plan revision does not exist")
    plan = Series.model_validate(draft["data"]).model_dump()
    episode_context(plan, number)
    params = parent["params"].copy()
    if params.get("collections"):
        params["source_snapshot_job"] = parent["id"]
    params["language"] = plan["language"]
    params["series"] = {"job_id": series_job_id, "revision": draft["revision"], "episode": number}
    if "task_title" in params:
        params["task_title"] = plan["episodes"][number - 1]["title"]
    key = f"series:{series_job_id}:r{draft['revision']}:episode:{number}"
    previous = workspace.job_by_request_key(key)
    if previous:
        result = _remember_task(workspace, previous)
    else:
        from brofessor.application.tasks import ModelOrigin, models

        choices = {**models(workspace, series_job_id)["data"], "origin": ModelOrigin.PARENT}
        if params.get("auto_audio", True):
            from brofessor.infrastructure.speech.catalogue import get

            # A newly created episode pins today's task choice; retries keep it.
            params["auto_audio"] = get(choices["speech_model"])
        result = _submit_draft(
            workspace, JobKind.PODCAST, _with_models(params, choices), key, model_choices=choices
        )
    if start_worker:
        from brofessor.application.worker import ensure_worker

        ensure_worker(workspace)
    return result


def _speech_inputs(spec):
    return {
        key: value
        for key, value in spec.items()
        if key not in ("name", "notes", "requirements", "license", "legacy")
    }


def uses_current_voice(job, language, model=None):
    """Compare a saved audio/preview job with the catalog, without loading any audio."""
    from brofessor.infrastructure.speech.catalogue import get, reference, selected
    from brofessor.infrastructure.speech.references import preset_snapshot

    if job["kind"] not in AUDIO_RENDER_JOB_KINDS:
        return False
    params = job["params"]
    spec = get(model or selected())
    if params.get("model") != reference(spec) or "model_spec" not in params:
        return False
    if language not in spec["languages"]:
        return False
    if spec.get("preset_references"):
        spec = preset_snapshot(spec, language, portable=True)
    return _speech_inputs(params["model_spec"]) == _speech_inputs(spec)


def _render_key(params):
    identity = dict(params)
    if "model_spec" in params:
        identity["model_spec"] = _speech_inputs(params["model_spec"])
    return "render:" + hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()


def render(
    workspace: Workspace,
    draft_job_id: str,
    *,
    model=None,
    revision=None,
    turn: int | None = None,
    request_key=None,
    start_worker=True,
) -> JobRecord:
    automatic = request_key is None
    original = workspace.job(draft_job_id)
    if original["kind"] in TRANSLATION_JOB_KINDS:
        from brofessor.features.books import translation as book_translation

        if model is not None or turn is not None:
            raise ValueError("Speech options do not apply to a book translation")
        return book_translation.render(
            workspace,
            draft_job_id,
            revision=revision,
            request_key=request_key,
            start_worker=start_worker,
        )
    if revision is not None and (type(revision) is not int or revision < 1):
        raise ValueError("Choose a positive saved draft revision")
    draft = workspace.draft(draft_job_id, revision)
    if (
        original["kind"] not in (JobKind.PODCAST, JobKind.SLIDES, JobKind.AUDIOBOOK)
        or draft is None
    ):
        raise ValueError("Generate a podcast, audiobook or slides draft first")
    spec = None
    if original["kind"] in (JobKind.PODCAST, JobKind.AUDIOBOOK):
        from brofessor.infrastructure.speech.catalogue import get, reference
        from brofessor.infrastructure.speech.catalogue import selected as selected_model

        if model is None:
            from brofessor.application.tasks import models

            model = models(workspace, draft_job_id)["data"].get("speech_model")
        spec = get(model or selected_model())
        model = reference(spec)
    elif model is not None:
        raise ValueError("A speech model applies only to podcast audio")
    kind = "render_" + original["kind"]
    params = {
        "draft_job_id": draft_job_id,
        "revision": draft["revision"],
    }
    if turn is not None:
        if original["kind"] != JobKind.PODCAST:
            raise ValueError("Choose a podcast to preview a turn")
        if type(turn) is not int or not 1 <= turn <= len(draft["data"]["turns"]):
            raise ValueError("Choose an existing turn number (starting at 1)")
        kind = JobKind.PREVIEW_TURN
        params.update(model=model, turn=turn)
    elif spec is not None:
        params["model"] = model
        if original["kind"] == JobKind.PODCAST:
            params["minutes"] = original["params"]["minutes"]

    # Keep automatic retries for pre-upgrade PPTX jobs on their original request key.
    if kind == JobKind.RENDER_SLIDES and request_key is None and "minutes" in original["params"]:
        old_key = _render_key({**params, "model": None, "minutes": original["params"]["minutes"]})
        if workspace.job_by_request_key(old_key):
            request_key = old_key
    explicit_key = request_key is not None
    previous = workspace.job_by_request_key(request_key) if explicit_key else None
    if previous is not None:
        ignored = {"minutes", "model"} if kind == JobKind.RENDER_SLIDES else {"model_spec"}
        if (
            previous["kind"] != kind
            or {key: value for key, value in previous["params"].items() if key not in ignored}
            != params
        ):
            raise ValueError("Request key already belongs to a different operation")
        # Explicit retries keep the first snapshot, even if preferences changed.
        params = previous["params"]
    elif spec is not None:
        if draft["data"]["language"] not in spec["languages"]:
            raise ValueError(f"Selected speech model does not support {draft['data']['language']}")
        from brofessor.infrastructure.speech.engines import validate_text

        if original["kind"] == JobKind.AUDIOBOOK:
            from brofessor.features.books.audiobooks import turns as narration_turns

            turns = narration_turns(draft["data"])
        else:
            turns = draft["data"]["turns"]
        for item in turns if turn is None else [turns[turn - 1]]:
            validate_text(spec, item["text"])
        if spec.get("preset_references"):
            from brofessor.infrastructure.speech.references import MissingVoicePack, preset_snapshot

            try:
                spec = preset_snapshot(spec, draft["data"]["language"])
            except MissingVoicePack as error:
                error.revision = draft["revision"]
                if automatic:
                    portable = preset_snapshot(spec, draft["data"]["language"], portable=True)
                    key = _render_key({**params, "model_spec": portable})
                    previous = workspace.job_by_request_key(key)
                    while (
                        previous
                        and previous["kind"] == kind
                        and _render_key(previous["params"]) == key
                        and previous["status"] == JobStatus.SUCCEEDED
                    ):
                        if rendered_file(workspace, previous):
                            return previous
                        previous = workspace.job_by_request_key(f"replace-missing:{previous['id']}")
                raise
        if spec.get("requires_reference") or spec.get("references"):
            from brofessor.infrastructure.speech.references import freeze
            from brofessor.infrastructure.speech.references import selected as selected_references

            spec["references"] = freeze(
                workspace.path,
                spec.get("references") or selected_references(draft["data"]["language"]),
            )
        params["model_spec"] = spec
    if not explicit_key:
        # Manual and automatic narration share the identity of frozen inputs.
        request_key = _render_key(params)
    try:
        result = workspace.submit(kind, params, request_key)
    except ValueError:
        # Another client may have submitted between lookup/freeze and enqueue.
        previous = workspace.job_by_request_key(request_key)
        if previous is None or previous["kind"] != kind:
            raise
        if explicit_key:
            matches = {k: v for k, v in previous["params"].items() if k != "model_spec"} == {
                k: v for k, v in params.items() if k != "model_spec"
            }
        else:
            matches = _render_key(previous["params"]) == request_key
        if not matches:
            raise
        result = previous
    # A moved or partially restored project may retain the job but lack its file.
    # Explicit request keys still identify the first operation exactly.
    while (
        automatic
        and result["status"] == JobStatus.SUCCEEDED
        and rendered_file(workspace, result) is None
    ):
        result = workspace.submit(kind, result["params"], f"replace-missing:{result['id']}")
    if start_worker:
        from brofessor.application.worker import ensure_worker

        ensure_worker(workspace)
    return result


def rendered_file(workspace, job):
    if job["kind"] in TRANSLATION_JOB_KINDS:
        from brofessor.features.books.translation import rendered_artifact

        saved = workspace.draft(job["id"])
        artifact = rendered_artifact(workspace, job, saved["revision"]) if saved else None
        return artifact_path(workspace, artifact["path"]) if artifact else None
    kind = (
        ArtifactKind.AUDIOBOOK
        if job["kind"] == JobKind.RENDER_AUDIOBOOK
        else ArtifactKind.PDF
        if job["kind"] == JobKind.RENDER_PDF
        else ArtifactKind.EPUB
        if job["kind"] in (JobKind.TRANSLATE_EPUB, JobKind.RENDER_EPUB)
        else (ArtifactKind.PPTX if job["kind"] == JobKind.RENDER_SLIDES else ArtifactKind.AUDIO)
    )
    for artifact in workspace.artifacts(job["id"]):
        if artifact["kind"] == kind:
            path = artifact_path(workspace, artifact["path"])
            if path.is_file():
                return path
    return None


def download_model(workspace: Workspace, model: str, *, start_worker=True) -> JobRecord:
    from brofessor.infrastructure.speech.catalogue import get

    item = get(model)
    job = workspace.submit(
        JobKind.DOWNLOAD_MODEL, {"model": item["id"], "model_spec": item}, reuse_active=True
    )
    if start_worker:
        from brofessor.application.worker import ensure_worker

        ensure_worker(workspace)
    return job


def artifact_path(workspace: Workspace, path: str) -> Path:
    resolved = (workspace.path / path).resolve()
    if not resolved.is_relative_to(workspace.path):
        raise ValueError("Artifact is outside the workspace")
    return resolved


def search(workspace, query, *, source_ids=None, limit=8):
    from brofessor.infrastructure.formats.ingestion import search_units

    if type(limit) is not int or not 1 <= limit <= 50:
        raise ValueError("Search limit must be 1–50")
    names = {s["id"]: s["name"] for s in workspace.sources()}
    if source_ids is None:
        source_ids = [s["id"] for s in workspace.sources() if not s.get("hidden")]
    if source_ids is not None and not set(source_ids) <= names.keys():
        raise ValueError("Select existing sources for search")
    return [
        {**u, "source": names[u["source_id"]]}
        for u in search_units(workspace.units(source_ids), query, limit)
    ]


def answer_evidence(workspace, job_id, revision=None):
    """Resolve saved answer/report quotes and provenance for both frontends."""
    job = workspace.job(job_id)
    if job["kind"] not in (JobKind.ASK, JobKind.REPORT, JobKind.STUDY, JobKind.REVIEW_STUDY):
        raise ValueError("Choose a question, report or study job")
    draft = workspace.draft(job_id, revision)
    if draft is None:
        return []
    from brofessor.features.sources import navigation as source_navigation

    names = source_navigation.names(workspace, job)
    units = {u["id"]: u for u in source_navigation.units(workspace, job)}
    content = draft["data"]
    collection = {
        JobKind.REPORT: "sections",
        JobKind.STUDY: "questions",
        JobKind.REVIEW_STUDY: "findings",
    }.get(job["kind"])
    if collection:
        from brofessor.features.questions import references

        content = references(content[collection])
    result = []
    for key in content["citations"]:
        unit = units[key]
        result.append(
            {
                "citation": key,
                "source_id": unit["source_id"],
                "source": names[unit["source_id"]],
                "locator": unit["locator"],
                "text": unit["text"],
                "quotes": [q["text"] for q in content.get("quotes", []) if q["citation"] == key],
            }
        )
    return result


def coverage(workspace: Workspace, job_id: str) -> dict | None:
    """Reading progress and citations from the current saved draft, including edits."""
    job = workspace.job(job_id)
    if job["kind"] in (
        JobKind.RENDER_SLIDES,
        JobKind.RENDER_PODCAST,
        JobKind.RENDER_AUDIOBOOK,
        JobKind.PREVIEW_TURN,
    ):
        job_id = job["params"]["draft_job_id"]
        draft = workspace.draft(job_id, job["params"]["revision"])
    else:
        draft = workspace.draft(job_id)
    path = workspace.path / JOBS_DIRECTORY / job_id / COVERAGE_FILENAME
    if not path.exists():
        return None
    report = json.loads(path.read_text())
    if "units" not in report:
        source_job = workspace.job(job_id)
        report["units"] = [
            {
                "id": unit["id"],
                "source_id": unit["source_id"],
                "locator": unit["locator"],
                "status": ReadingStatus.READ
                if unit["id"] in report["read"]
                else ReadingStatus.EXCLUDED
                if unit["status"] != UnitStatus.READY
                else ReadingStatus.PENDING,
                "reason": "" if unit["status"] == UnitStatus.READY else unit["status"],
            }
            for unit in workspace.units(source_job["params"]["source_ids"])
        ]
    cited = set()

    def visit(node):
        if isinstance(node, dict):
            cited.update(node.get("citations", []))
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    if draft:
        content = draft["data"]
        if job["kind"] == JobKind.PREVIEW_TURN:
            content = content["turns"][job["params"]["turn"] - 1]
        visit(content)
    from brofessor.features.sources import navigation as source_navigation

    names = source_navigation.names(workspace, workspace.job(job_id))
    for unit in report.get("units", []):
        unit["source"] = names.get(unit["source_id"], unit["source_id"])
        unit["cited"] = unit["id"] in cited
    report["cited_count"] = len(cited)
    report["draft_revision"] = draft["revision"] if draft else None
    return report


def task_details(workspace, job_id):
    from brofessor.features.sources import collections
    from brofessor.features.sources import navigation as source_navigation

    job = workspace.job(job_id)
    names = {s["id"]: s["name"] for s in workspace.sources()}
    selected = [
        {"id": i, "name": names.get(i, i), "kind": "file"}
        for i in job["params"].get("source_ids", [])
    ]
    selected += [
        {"id": r["id"], "name": r["root"], "kind": collections.DIRECTORY_SOURCE_KIND}
        for r in job["params"].get("collections", [])
    ]
    value = {
        "request": job["params"].get("focus", ""),
        "selected_sources": selected,
        "navigation": source_navigation.report(workspace, job),
        "coverage": coverage(workspace, job_id),
    }
    return value if any(value.values()) else {}
