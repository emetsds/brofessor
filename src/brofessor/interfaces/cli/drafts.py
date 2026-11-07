"""CLI commands: drafts."""

import json
from pathlib import Path

import typer

from brofessor.application import service
from brofessor.contracts.jobs import JobKind
from brofessor.interfaces.cli.common import (
    _managed,
    content_succeeded,
    render_and_show,
    show,
    wait_for_content,
)

app = typer.Typer(no_args_is_help=True)


@app.command("show")
def show_draft(
    ctx: typer.Context,
    job_id: str,
    revision: int | None = typer.Option(None, min=1, help="Read this saved draft revision."),
):
    draft = ctx.obj.draft(job_id, revision)
    if revision is not None and draft is None:
        raise typer.BadParameter("The requested draft revision does not exist")
    if draft and ctx.obj.job(job_id)["kind"] in (
        JobKind.ASK,
        JobKind.REPORT,
        JobKind.STUDY,
        JobKind.REVIEW_STUDY,
    ):
        draft["evidence"] = service.answer_evidence(ctx.obj, job_id, draft["revision"])
        if ctx.obj.job(job_id)["params"].get("conversation"):
            draft["conversation"] = service.question_context(ctx.obj, job_id)
    show(draft)


@app.command("save")
def save_draft(ctx: typer.Context, job_id: str, path: Path, expected_revision: int):
    """Save a revision. Changing the language code does not translate the written text."""
    show(service.edit_draft(ctx.obj, job_id, json.loads(path.read_text()), expected_revision))


@app.command("preview-turn")
def preview_turn(
    ctx: typer.Context,
    job_id: str,
    turn: int = typer.Argument(..., min=1, help="Turn number, starting at 1."),
    revision: int | None = typer.Option(None, min=1, help="Pin this saved script revision."),
    wait: bool = False,
):
    """Listen to one turn before updating the full episode."""
    render_and_show(ctx.obj, job_id, turn=turn, revision=revision, wait=wait)


@app.command("render")
def render_draft(
    ctx: typer.Context,
    job_id: str,
    model: str | None = typer.Option(
        None,
        "--tts-model",
        "--model",
        hidden=True,
        help="Pinned model override for legacy speech renders.",
    ),
    request_key: str | None = None,
    revision: int | None = typer.Option(None, min=1, help="Pin this saved draft revision."),
    wait: bool = False,
):
    render_and_show(
        ctx.obj, job_id, model=model, revision=revision, request_key=request_key, wait=wait
    )


@app.command("check")
def check_podcast_script(
    ctx: typer.Context,
    job_id: str,
    revision: int | None = typer.Option(None, min=1),
    request_key: str | None = None,
    wait: bool = False,
):
    """Review a saved podcast against cited originals, without changing its text."""
    from brofessor.features.podcasts.checks import report

    job = _managed(
        service.check_script, ctx.obj, job_id, revision=revision, request_key=request_key
    )
    if wait:
        job = wait_for_content(ctx.obj, job["id"])
    show({**job, "report": _managed(report, ctx.obj, job["id"])})
    if wait and not content_succeeded(job):
        raise typer.Exit(1)


@app.command("check-report")
def podcast_check_report(ctx: typer.Context, check_id: str):
    from brofessor.features.podcasts.checks import report

    show(_managed(report, ctx.obj, check_id))
