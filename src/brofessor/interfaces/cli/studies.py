"""CLI commands: studies."""

import json
from pathlib import Path

import typer

from brofessor.contracts.content import ContentLanguage
from brofessor.contracts.jobs import JobKind
from brofessor.interfaces.cli.common import (
    OllamaAddress,
    _managed,
    content_succeeded,
    show,
    submit_and_show,
    wait_for_content,
)

app = typer.Typer(
    no_args_is_help=True, help="Prepare practice questions, save answers and review them."
)


@app.command("create")
def create_study(
    ctx: typer.Context,
    focus: str,
    count: int = typer.Option(6, min=2, max=12),
    provider: str | None = None,
    model: str | None = None,
    ollama_address: OllamaAddress = None,
    language: str = ContentLanguage.RU,
    source: list[str] = typer.Option(None),
    wait: bool = False,
    request_key: str | None = None,
    title: str = "",
):
    """Prepare grounded application and explanation questions."""
    submit_and_show(
        ctx.obj,
        JobKind.STUDY,
        source,
        focus,
        language,
        provider,
        model,
        wait,
        request_key,
        ollama_address=ollama_address,
        title=title,
        question_count=count,
    )


@app.command("answer")
def answer_study(ctx: typer.Context, job_id: str, path: Path, expected_revision: int):
    """Save a JSON map of question IDs to your answers, preserving other answers."""
    from brofessor.features.studies import save_answers

    show(_managed(save_answers, ctx.obj, job_id, json.loads(path.read_text()), expected_revision))


@app.command("review")
def review_study(
    ctx: typer.Context,
    job_id: str,
    revision: int | None = typer.Option(None, min=1),
    wait: bool = False,
    request_key: str | None = None,
):
    """Check a pinned saved set of learner answers against original sources."""
    from brofessor.features.studies import submit_review

    job = _managed(submit_review, ctx.obj, job_id, revision=revision, request_key=request_key)
    if wait:
        job = wait_for_content(ctx.obj, job["id"])
    show(job)
    if wait and not content_succeeded(job):
        raise typer.Exit(1)
