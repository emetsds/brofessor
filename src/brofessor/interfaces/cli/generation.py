"""Top-level CLI commands: generation."""

import json
from pathlib import Path

import typer

from brofessor.application import service
from brofessor.contracts.content import ContentLanguage
from brofessor.contracts.jobs import JobKind
from brofessor.features.reports import ReportTemplate
from brofessor.interfaces.cli.common import (
    OllamaAddress,
    _managed,
    connection_options,
    content_succeeded,
    show,
    submit_and_show,
    wait_for_content,
)


def translate_book(
    ctx: typer.Context,
    source_id: str,
    language: str = ContentLanguage.RU,
    provider: str | None = None,
    model: str | None = None,
    ollama_address: OllamaAddress = None,
    glossary: Path | None = typer.Option(
        None, exists=True, dir_okay=False, help="JSON list of term/sense/translation entries."
    ),
    request_key: str | None = None,
    wait: bool = False,
    title: str = "",
):
    """Translate one EPUB 2/3 or supported text-layer PDF with a contextual glossary."""
    try:
        from brofessor.features.books.translation import kind_for_source

        connection = connection_options(provider, model, ollama_address)
        entries = json.loads(glossary.read_text(encoding="utf-8")) if glossary else None
        job = service.submit(
            ctx.obj,
            kind_for_source(ctx.obj, source_id),
            source_ids=[source_id],
            language=language,
            glossary=entries,
            title=title,
            request_key=request_key,
            **connection,
        )
        if wait:
            job = wait_for_content(ctx.obj, job["id"])
        show(job)
        if wait and not content_succeeded(job):
            raise typer.Exit(1)
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error


def ask(
    ctx: typer.Context,
    question: str,
    provider: str | None = None,
    model: str | None = None,
    ollama_address: OllamaAddress = None,
    language: str | None = None,
    source: list[str] = typer.Option(None),
    wait: bool = False,
    request_key: str | None = None,
    reply_to: str | None = typer.Option(
        None, help="Continue a saved answer; inherits its sources and provider."
    ),
    revision: int | None = typer.Option(None, help="Saved parent-answer revision for --reply-to."),
    title: str = "",
):
    """Ask a grounded question over the selected sources."""
    if reply_to is not None:
        if any(
            getattr(ctx.get_parameter_source(name), "name", None) == "COMMANDLINE"
            for name in ("source", "provider", "model", "ollama_address")
        ):
            raise typer.BadParameter(
                "Follow-ups inherit sources, provider, model and Ollama address; omit those flags."
            )
        try:
            job = service.follow_up(
                ctx.obj,
                reply_to,
                question,
                title=title,
                revision=revision,
                language=language,
                request_key=request_key,
            )
        except ValueError as error:
            raise typer.BadParameter(str(error)) from error
        if wait:
            job = wait_for_content(ctx.obj, job["id"])
        show(job)
        if wait and not content_succeeded(job):
            raise typer.Exit(1)
        return
    if revision is not None:
        raise typer.BadParameter("--revision requires --reply-to")
    submit_and_show(
        ctx.obj,
        JobKind.ASK,
        source,
        question,
        language or ContentLanguage.RU,
        provider,
        model,
        wait,
        request_key,
        ollama_address=ollama_address,
        title=title,
    )


def report(
    ctx: typer.Context,
    focus: str,
    template: str = typer.Option(
        ReportTemplate.COMPARISON, help="comparison, guide, reference or arguments"
    ),
    provider: str | None = None,
    model: str | None = None,
    ollama_address: OllamaAddress = None,
    language: str = ContentLanguage.RU,
    source: list[str] = typer.Option(None),
    wait: bool = False,
    request_key: str | None = None,
    terminology_job: str | None = None,
    terminology_revision: int | None = typer.Option(None, min=1),
    title: str = "",
):
    """Prepare an editable written report with original citations and a Markdown file."""
    if (terminology_job is None) != (terminology_revision is None):
        raise typer.BadParameter(
            "Pin accepted terminology with both --terminology-job and --terminology-revision"
        )
    submit_and_show(
        ctx.obj,
        JobKind.REPORT,
        source,
        focus,
        language,
        provider,
        model,
        wait,
        request_key,
        ollama_address=ollama_address,
        title=title,
        template=template,
        terminology={"job_id": terminology_job, "revision": terminology_revision}
        if terminology_job
        else None,
    )


def audiobook(
    ctx: typer.Context,
    source_id: str,
    language: str = ContentLanguage.RU,
    speech_model: str | None = None,
    translation_job: str | None = None,
    translation_revision: int | None = typer.Option(None, min=1),
    request_key: str | None = None,
    wait: bool = False,
    title: str = "",
):
    """Prepare complete original or saved translated text; draft render creates MP3 and chaptered M4B."""
    from brofessor.features.books.audiobooks import submit

    if (translation_job is None) != (translation_revision is None):
        raise typer.BadParameter(
            "Pin a translation with --translation-job and --translation-revision"
        )
    reference = (
        {"job_id": translation_job, "revision": translation_revision} if translation_job else None
    )
    job = _managed(
        submit,
        ctx.obj,
        source_id,
        language=language,
        speech_model=speech_model,
        translation=reference,
        title=title,
        request_key=request_key,
    )
    if wait:
        job = wait_for_content(ctx.obj, job["id"])
    show(job)
    if wait and not content_succeeded(job):
        raise typer.Exit(1)


def podcast(
    ctx: typer.Context,
    focus: str = "",
    minutes: int = 20,
    language: str = ContentLanguage.RU,
    provider: str | None = None,
    model: str | None = None,
    ollama_address: OllamaAddress = None,
    source: list[str] = typer.Option(None),
    wait: bool = False,
    request_key: str | None = None,
    speech_model: str | None = None,
    writing_method: str | None = typer.Option(
        None, help="classic (default) or originals (experimental source-backed writer)."
    ),
    title: str = "",
    auto_audio: bool = True,
):
    """Prepare a dialogue and narrate it locally; --no-auto-audio keeps only the script."""
    submit_and_show(
        ctx.obj,
        JobKind.PODCAST,
        source,
        focus,
        language,
        provider,
        model,
        wait,
        request_key,
        ollama_address=ollama_address,
        title=title,
        minutes=minutes,
        speech_model=speech_model,
        auto_audio=auto_audio,
        writing_method=writing_method,
    )


def slides(
    ctx: typer.Context,
    focus: str = "",
    count: int = 8,
    language: str = ContentLanguage.RU,
    provider: str | None = None,
    model: str | None = None,
    ollama_address: OllamaAddress = None,
    source: list[str] = typer.Option(None),
    wait: bool = False,
    request_key: str | None = None,
    title: str = "",
):
    """Prepare editable slide content. Use draft render to create PPTX."""
    submit_and_show(
        ctx.obj,
        JobKind.SLIDES,
        source,
        focus,
        language,
        provider,
        model,
        wait,
        request_key,
        ollama_address=ollama_address,
        title=title,
        slide_count=count,
    )
