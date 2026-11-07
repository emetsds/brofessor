"""Top-level CLI commands: administration."""

import subprocess
import sys
from importlib.resources import as_file, files

import typer

from brofessor.application import projects, service
from brofessor.infrastructure.storage import preferences
from brofessor.interfaces.cli.common import (
    OllamaAddress,
    connection_options,
    show,
)


def init(ctx: typer.Context):
    """Create or open a self-contained workspace directory."""
    show({"workspace": str(ctx.obj.path)})


def search(ctx: typer.Context, query: str, source: list[str] = typer.Option(None), limit: int = 8):
    """Search original words locally; no model call or automatic translation."""
    show(service.search(ctx.obj, query, source_ids=source, limit=limit))


def config(
    provider: str | None = None,
    model: str | None = None,
    ollama_address: OllamaAddress = None,
    language: str | None = None,
    speech_model: str | None = None,
):
    """Show the text connection or save defaults used by CLI and UI."""
    editing = provider is not None or model is not None or ollama_address is not None
    if language is not None or speech_model is not None:
        previous = preferences.settings(for_edit=True)
        connection = (
            connection_options(provider, model, ollama_address, for_edit=True)
            if editing
            else {k: v for k, v in previous.items() if k in ("provider", "model", "ollama_address")}
        )
        try:
            show(
                preferences.save_settings(
                    **connection,
                    language=language or previous["language"],
                    speech_model=speech_model or previous["speech_model"],
                )
            )
        except (OSError, ValueError) as error:
            raise typer.BadParameter(str(error)) from error
        return
    connection = connection_options(provider, model, ollama_address, for_edit=editing)
    if editing:
        try:
            preferences.save_text_connection(**connection)
        except (ValueError, OSError) as error:
            raise typer.BadParameter(str(error)) from error
    show(connection)


def doctor(
    provider: str | None = None,
    model: str | None = None,
    ollama_address: OllamaAddress = None,
):
    """Report local executor capabilities without performing inference."""
    from brofessor.infrastructure.text.runners import doctor as diagnose

    show(diagnose(**connection_options(provider, model, ollama_address)))


def worker(ctx: typer.Context, once: bool = False):
    """Run a worker in this terminal. Ctrl-C interrupts safely."""
    from brofessor.application.worker import run

    if not run(ctx.obj, once=once):
        typer.echo("A worker already owns this workspace", err=True)
        raise typer.Exit(1)


def ui(
    ctx: typer.Context,
    port: int = typer.Option(8501, min=1, max=65535, help="Port for the local web UI."),
    ollama_address: OllamaAddress = None,
):
    """Open the local Streamlit interface for this workspace."""
    module = files("brofessor.interfaces.web").joinpath("app.py")
    if ctx.obj is not None:
        projects.open_project(ctx.obj.path)
    workspace_args = ["--workspace", str(ctx.obj.path)] if ctx.obj is not None else []
    with as_file(module) as app_path:
        raise typer.Exit(
            subprocess.call(
                [
                    sys.executable,
                    "-m",
                    "streamlit",
                    "run",
                    str(app_path),
                    "--server.address=127.0.0.1",
                    "--server.headless=true",
                    f"--server.port={port}",
                    "--browser.gatherUsageStats=false",
                    "--client.toolbarMode=minimal",
                    "--client.showSidebarNavigation=false",
                    "--theme.primaryColor=#2d5d9e",
                    "--theme.baseFontSize=16",
                    "--",
                    *workspace_args,
                    *(["--ollama-address", ollama_address] if ollama_address is not None else []),
                ]
            )
        )
