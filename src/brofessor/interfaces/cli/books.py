"""CLI commands: books."""

import typer

from brofessor.contracts.jobs import TRANSLATION_JOB_KINDS
from brofessor.interfaces.cli.common import (
    content_succeeded,
    show,
    wait_for_content,
)

app = typer.Typer(no_args_is_help=True, help="Inspect book terminology and revise one meaning.")


@app.command("glossary")
def book_glossary(
    ctx: typer.Context, job_id: str, revision: int | None = typer.Option(None, min=1)
):
    """Show meanings and their source occurrences from a saved translation."""
    job = ctx.obj.job(job_id)
    draft = ctx.obj.draft(job_id, revision)
    if job["kind"] not in TRANSLATION_JOB_KINDS or draft is None:
        raise typer.BadParameter("Choose a saved book translation")
    show(
        {
            "revision": draft["revision"],
            "terms": draft["data"]["terms"],
            "occurrences": draft["data"]["occurrences"],
            "retained_manual": draft["data"]["retained_manual"],
        }
    )


@app.command("term")
def revise_book_term(
    ctx: typer.Context,
    job_id: str,
    term_id: str,
    translation: str,
    revision: int | None = typer.Option(None, min=1),
    request_key: str | None = None,
    wait: bool = False,
):
    """Revise one meaning's aligned phrases; preserve other text and older revisions."""
    from brofessor.features.books.translation import revise_term

    try:
        job = revise_term(
            ctx.obj, job_id, term_id, translation, revision=revision, request_key=request_key
        )
        if wait:
            job = wait_for_content(ctx.obj, job["id"])
        show(job)
        if wait and not content_succeeded(job):
            raise typer.Exit(1)
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
