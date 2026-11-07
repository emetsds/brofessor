"""CLI commands: notes."""

import json
from pathlib import Path

import typer

from brofessor.application import service
from brofessor.interfaces.cli.common import (
    show,
)

app = typer.Typer(no_args_is_help=True, help="Create and edit project notes without a model call.")


@app.command("create")
def create_note(
    ctx: typer.Context, title: str, path: Path, citation: list[str] = typer.Option(None)
):
    """Create a note from a UTF-8 text/Markdown file."""
    show(
        service.save_note(
            ctx.obj,
            {"title": title, "text": path.read_text(encoding="utf-8"), "citations": citation or []},
        )
    )


@app.command("list")
def list_notes(ctx: typer.Context):
    show(ctx.obj.notes())


@app.command("show")
def show_note(ctx: typer.Context, note_id: str, revision: int | None = None):
    note = ctx.obj.note(note_id, revision)
    if note is None:
        raise typer.BadParameter("The requested note revision does not exist")
    note["evidence"] = service.note_evidence(ctx.obj, note_id, note["revision"])
    show(note)


@app.command("save")
def save_note(ctx: typer.Context, note_id: str, path: Path, expected_revision: int):
    """Save only the edited data object as JSON, preserving note origin and history."""
    show(
        service.save_note(
            ctx.obj,
            json.loads(path.read_text(encoding="utf-8")),
            note_id=note_id,
            expected_revision=expected_revision,
        )
    )


@app.command("from-answer")
def note_from_answer(
    ctx: typer.Context, job_id: str, revision: int | None = None, title: str | None = None
):
    """Save an answer revision once; repeating this preserves your note edits."""
    show(service.note_from_answer(ctx.obj, job_id, revision=revision, title=title))
