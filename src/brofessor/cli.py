"""CLI client of the same services used by Streamlit."""

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Annotated

import typer
from click import ClickException

from . import service
from .executors import DEFAULT_OLLAMA_PORT
from .workspace import Workspace

OllamaPort = Annotated[
    int, typer.Option(min=1, max=65535, help="Port of the local Ollama server (127.0.0.1).")
]

app = typer.Typer(no_args_is_help=True, help="brofessor: sources, podcasts and presentations")
source_app = typer.Typer(no_args_is_help=True)
job_app = typer.Typer(no_args_is_help=True)
draft_app = typer.Typer(no_args_is_help=True)
app.add_typer(source_app, name="source")
app.add_typer(job_app, name="job")
app.add_typer(draft_app, name="draft")


def show(value):
    typer.echo(json.dumps(value, ensure_ascii=False, indent=2))


@app.callback()
def main(
    ctx: typer.Context,
    workspace: Path = typer.Option(
        Path(".brofessor/workspace"), "--workspace", "-w", envvar="BROFESSOR_WORKSPACE"
    ),
):
    ctx.obj = Workspace(workspace)


@app.command()
def init(ctx: typer.Context):
    """Create or open a self-contained workspace directory."""
    show({"workspace": str(ctx.obj.path)})


@source_app.command("add")
def add_source(ctx: typer.Context, path: Path = typer.Argument(exists=True, dir_okay=False)):
    show(ctx.obj.add_source(path))


@source_app.command("list")
def list_sources(ctx: typer.Context):
    show(ctx.obj.sources())


@source_app.command("show")
def source_show(ctx: typer.Context, source_id: str):
    show(ctx.obj.units([source_id]))


@app.command()
def search(ctx: typer.Context, query: str):
    from .sources import search_units

    show(search_units(ctx.obj.units(), query))


def wait_for_job(workspace: Workspace, job_id: str) -> dict:
    """Wait for shared state, attempting at most one missing-worker restart.

    Restarting the worker recovers old running jobs as interrupted. This helper
    never resumes or resubmits a job, and never loops on a failing worker spawn.
    """
    from .worker import ensure_worker, is_running

    attempted_start = False
    startup_deadline = None
    log = workspace.path / "worker.log"
    while True:
        job = workspace.job(job_id)
        if job["status"] not in ("queued", "running"):
            return job
        if is_running(workspace):
            startup_deadline = None
        elif not attempted_start:
            attempted_start = True
            startup_deadline = time.monotonic() + 5
            try:
                ensure_worker(workspace)
            except OSError:
                raise ClickException(f"Could not start the worker. Inspect {log}") from None
        elif startup_deadline is None:
            raise ClickException(f"The worker stopped again during this wait. Inspect {log}")
        elif time.monotonic() >= startup_deadline:
            raise ClickException(f"The worker did not start within 5 seconds. Inspect {log}")
        time.sleep(0.1)


def submit_and_show(
    workspace,
    kind,
    sources,
    focus,
    language,
    provider,
    model,
    minutes,
    slide_count,
    wait,
    request_key,
    ollama_port=DEFAULT_OLLAMA_PORT,
):
    job = service.submit(
        workspace,
        kind,
        source_ids=sources or None,
        focus=focus,
        language=language,
        provider=provider,
        model=model,
        ollama_port=ollama_port,
        minutes=minutes,
        slide_count=slide_count,
        request_key=request_key,
    )
    if wait:
        job = wait_for_job(workspace, job["id"])
    show(job)
    if wait and job["status"] != "succeeded":
        raise typer.Exit(1)


@app.command()
def ask(
    ctx: typer.Context,
    question: str,
    provider: str = "codex",
    model: str | None = None,
    ollama_port: OllamaPort = DEFAULT_OLLAMA_PORT,
    language: str = "ru",
    source: list[str] = typer.Option(None),
    wait: bool = False,
    request_key: str | None = None,
):
    """Ask a grounded question over the selected sources."""
    submit_and_show(
        ctx.obj,
        "ask",
        source,
        question,
        language,
        provider,
        model,
        20,
        8,
        wait,
        request_key,
        ollama_port=ollama_port,
    )


@app.command()
def podcast(
    ctx: typer.Context,
    focus: str = "",
    minutes: int = 20,
    language: str = "ru",
    provider: str = "codex",
    model: str | None = None,
    ollama_port: OllamaPort = DEFAULT_OLLAMA_PORT,
    source: list[str] = typer.Option(None),
    wait: bool = False,
    request_key: str | None = None,
):
    """Prepare an editable dialogue. Use draft render to synthesize it."""
    submit_and_show(
        ctx.obj,
        "podcast",
        source,
        focus,
        language,
        provider,
        model,
        minutes,
        8,
        wait,
        request_key,
        ollama_port=ollama_port,
    )


@app.command()
def slides(
    ctx: typer.Context,
    focus: str = "",
    count: int = 8,
    language: str = "ru",
    provider: str = "codex",
    model: str | None = None,
    ollama_port: OllamaPort = DEFAULT_OLLAMA_PORT,
    source: list[str] = typer.Option(None),
    wait: bool = False,
    request_key: str | None = None,
):
    """Prepare editable slide content. Use draft render to create PPTX."""
    submit_and_show(
        ctx.obj,
        "slides",
        source,
        focus,
        language,
        provider,
        model,
        20,
        count,
        wait,
        request_key,
        ollama_port=ollama_port,
    )


@job_app.command("list")
def list_jobs(ctx: typer.Context):
    show(ctx.obj.jobs())


@job_app.command("show")
def show_job(ctx: typer.Context, job_id: str):
    show({**ctx.obj.job(job_id), "artifacts": ctx.obj.artifacts(job_id)})


@job_app.command("cancel")
def cancel_job(ctx: typer.Context, job_id: str):
    show(ctx.obj.cancel(job_id))


@job_app.command("resume")
def resume_job(ctx: typer.Context, job_id: str):
    from .worker import ensure_worker

    result = ctx.obj.resume(job_id)
    ensure_worker(ctx.obj)
    show(result)


@draft_app.command("show")
def show_draft(ctx: typer.Context, job_id: str):
    show(ctx.obj.draft(job_id))


@draft_app.command("save")
def save_draft(ctx: typer.Context, job_id: str, path: Path, expected_revision: int):
    """Save the JSON data object as a new revision, preserving previous edits."""
    show(service.edit_draft(ctx.obj, job_id, json.loads(path.read_text()), expected_revision))


@draft_app.command("render")
def render_draft(
    ctx: typer.Context,
    job_id: str,
    model: str | None = None,
    request_key: str | None = None,
    wait: bool = False,
):
    job = service.render(ctx.obj, job_id, model=model, request_key=request_key)
    if wait:
        job = wait_for_job(ctx.obj, job["id"])
    show({**job, "artifacts": ctx.obj.artifacts(job["id"])})
    if wait and job["status"] != "succeeded":
        raise typer.Exit(1)


@app.command()
def doctor(
    provider: str = "codex",
    model: str | None = None,
    ollama_port: OllamaPort = DEFAULT_OLLAMA_PORT,
):
    """Report local executor capabilities without performing inference."""
    from .executors import doctor as diagnose

    show(diagnose(provider, model, ollama_port=ollama_port))


@app.command()
def worker(ctx: typer.Context, once: bool = False):
    """Run a worker in this terminal. Ctrl-C interrupts safely."""
    from .worker import run

    if not run(ctx.obj, once=once):
        typer.echo("A worker already owns this workspace", err=True)
        raise typer.Exit(1)


@app.command()
def ui(
    ctx: typer.Context,
    port: int = typer.Option(8501, min=1, max=65535, help="Port for the local web UI."),
    ollama_port: OllamaPort = DEFAULT_OLLAMA_PORT,
):
    """Open the local Streamlit interface for this workspace."""
    module = Path(__file__).with_name("ui.py")
    raise typer.Exit(
        subprocess.call(
            [
                sys.executable,
                "-m",
                "streamlit",
                "run",
                str(module),
                "--server.address=127.0.0.1",
                "--server.headless=true",
                f"--server.port={port}",
                "--browser.gatherUsageStats=false",
                "--",
                "--workspace",
                str(ctx.obj.path),
                "--ollama-port",
                str(ollama_port),
            ]
        )
    )


if __name__ == "__main__":
    app()
