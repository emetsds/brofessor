"""CLI commands: sources."""

from pathlib import Path

import typer

from brofessor.interfaces.cli.common import (
    show,
)

app = typer.Typer(no_args_is_help=True)


@app.command("add")
def add_source(ctx: typer.Context, path: Path = typer.Argument(exists=True)):
    """Import a file, or connect a document directory without indexing it."""
    from brofessor.features.sources import collections

    try:
        show(collections.connect(ctx.obj, path) if path.is_dir() else ctx.obj.add_source(path))
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error


@app.command("list")
def list_sources(ctx: typer.Context):
    from brofessor.features.sources.collections import choices

    show(choices(ctx.obj))


@app.command("disconnect")
def disconnect_source(ctx: typer.Context, collection_id: str):
    """Disconnect a directory, keeping task snapshots and the original files."""
    from brofessor.features.sources.collections import disconnect

    try:
        disconnect(ctx.obj, collection_id)
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    show({"disconnected": collection_id})


@app.command("show")
def source_show(ctx: typer.Context, source_id: str):
    show(ctx.obj.units([source_id]))
