"""CLI commands: projects."""

from pathlib import Path

import typer

from brofessor.application import projects
from brofessor.interfaces.cli.common import (
    _managed,
    show,
)

app = typer.Typer(no_args_is_help=True, help="Create, open and select local projects.")


@app.command("list")
def list_projects():
    show(projects.list_projects())


@app.command("create")
def create_project(name: str, directory: Path | None = None):
    """Create a project in the chosen projects directory and select it."""
    show(projects.create(name, root=directory))


@app.command("open")
def open_project(path: Path, name: str | None = typer.Option(None, hidden=True)):
    """Register an existing workspace folder and select it without copying data."""
    show(projects.open_project(path, name=name))


@app.command("use")
def use_project(name: str):
    """Select a registered project by name or absolute path."""
    show(projects.use(name))


@app.command("delete")
def delete_project(name: str, yes: bool = typer.Option(False, "--yes", "-y")):
    """Remove a project from the app; its directory is retained for restoration."""
    if not yes:
        typer.confirm("Remove this project from the app? Its files will be kept.", abort=True)
    show(_managed(projects.delete, name))


@app.command("deleted")
def deleted_projects():
    """List removed projects and their retained directories."""
    show(_managed(projects.deleted_projects))


@app.command("restore")
def restore_project(name: str):
    """Restore a removed project by name or absolute path."""
    show(_managed(projects.restore, name))
