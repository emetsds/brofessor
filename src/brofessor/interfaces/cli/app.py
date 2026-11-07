"""Compose the CLI; business operations live in application services."""

from pathlib import Path

import typer

from brofessor.application import projects as project_service
from brofessor.infrastructure.storage.workspace import DATABASE_FILENAME, Workspace
from brofessor.interfaces.cli import (
    administration,
    books,
    drafts,
    generation,
    jobs,
    models,
    notes,
    projects,
    prompts,
    series,
    sources,
    speech,
    studies,
    tasks,
)
from brofessor.interfaces.cli.common import CommandError

app = typer.Typer(
    no_args_is_help=True, help="brofessor: sources, book translation, podcasts and presentations"
)

app.add_typer(projects.app, name="project")
app.add_typer(sources.app, name="source")
app.add_typer(jobs.app, name="job")
app.add_typer(drafts.app, name="draft")
app.add_typer(notes.app, name="note")
app.add_typer(speech.app, name="tts")
app.add_typer(series.app, name="series")
app.add_typer(tasks.app, name="task")
app.add_typer(models.app, name="models")
app.add_typer(books.app, name="book")
app.add_typer(studies.app, name="study")
app.add_typer(prompts.app, name="prompts")


@app.callback()
def main(
    ctx: typer.Context,
    workspace: Path | None = typer.Option(None, "--workspace", "-w", envvar="BROFESSOR_WORKSPACE"),
):
    if ctx.invoked_subcommand == "prompts":
        ctx.obj = workspace
        return
    if ctx.invoked_subcommand in ("project", "doctor", "config"):
        ctx.obj = None
        return
    if workspace is None:
        current = project_service.selected()
        if current is not None:
            if not current["available"] and ctx.invoked_subcommand not in (
                "ui",
                "tts",
                "models",
                "task",
            ):
                raise CommandError("Selected project folder is unavailable. Use project open PATH")
            workspace = Path(current["path"]) if current["available"] else None
        elif ctx.invoked_subcommand == "init":
            workspace = Path(project_service.create("Default")["path"])
        elif ctx.invoked_subcommand not in ("ui", "tts", "task", "models"):
            raise CommandError("Choose a project first: project create NAME or project open PATH")
    if (
        workspace is not None
        and ctx.invoked_subcommand in ("task", "models")
        and not (Path(workspace) / DATABASE_FILENAME).is_file()
    ):
        raise CommandError("The project folder is unavailable")
    ctx.obj = Workspace(workspace) if workspace is not None else None


app.command()(administration.init)
app.command()(administration.search)
app.command()(administration.config)
app.command("translate")(generation.translate_book)
app.command()(generation.ask)
app.command()(generation.report)
app.command()(generation.audiobook)
app.command()(generation.podcast)
app.command()(generation.slides)
app.command()(administration.doctor)
app.command()(administration.worker)
app.command()(administration.ui)


if __name__ == "__main__":
    app()
