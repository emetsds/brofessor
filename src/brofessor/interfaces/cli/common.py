"""Shared CLI output, connection options, and bounded job waiting."""

import json
import shlex
import time
from typing import Annotated

import typer

from brofessor.application import service
from brofessor.application.worker import WORKER_LOG_FILENAME
from brofessor.contracts.jobs import ACTIVE_JOB_STATUSES, JobKind, JobStatus
from brofessor.contracts.text import TextProvider
from brofessor.infrastructure.storage import preferences
from brofessor.infrastructure.storage.workspace import Workspace
from brofessor.infrastructure.text.runners import normalize_ollama_address


class CommandError(typer.Exit):
    """Show an operational failure using Typer's public API across supported versions."""

    def __init__(self, message):
        self.message = message
        typer.echo(f"Error: {message}", err=True)
        super().__init__(1)

    def __str__(self):
        return self.message


def validate_ollama_address(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        return normalize_ollama_address(value)
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error


OllamaAddress = Annotated[
    str | None,
    typer.Option(
        callback=validate_ollama_address, help="Ollama server IP:port, e.g. 127.0.0.1:11434."
    ),
]


def show(value):
    typer.echo(json.dumps(value, ensure_ascii=False, indent=2))


def wait_for_job(workspace: Workspace, job_id: str) -> dict:
    """Wait for shared state, attempting at most one missing-worker restart.

    Restarting the worker recovers old running jobs as interrupted. This helper
    never resumes or resubmits a job, and never loops on a failing worker spawn.
    """
    from brofessor.application.worker import ensure_worker, is_running

    attempted_start = False
    startup_deadline = None
    previous_size = None
    log = workspace.path / WORKER_LOG_FILENAME
    while True:
        job = workspace.job(job_id)
        if job.get("kind") == JobKind.DOWNLOAD_MODEL and job["progress"].get("total"):
            progress = job["progress"]
            size = (round(progress.get("completed", 0) / 1e6), round(progress["total"] / 1e6))
            if size != previous_size:
                typer.echo(f"{size[0]} / {size[1]} MB", err=True)
                previous_size = size
        if job["status"] not in ACTIVE_JOB_STATUSES:
            return job
        if is_running(workspace):
            startup_deadline = None
        elif not attempted_start:
            attempted_start = True
            startup_deadline = time.monotonic() + 5
            try:
                ensure_worker(workspace)
            except OSError:
                raise CommandError(f"Could not start the worker. Inspect {log}") from None
        elif startup_deadline is None:
            raise CommandError(f"The worker stopped again during this wait. Inspect {log}")
        elif time.monotonic() >= startup_deadline:
            raise CommandError(f"The worker did not start within 5 seconds. Inspect {log}")
        time.sleep(0.1)


def wait_for_content(workspace, job_id):
    job = wait_for_job(workspace, job_id)
    if (
        job["status"] == JobStatus.SUCCEEDED
        and job.get("kind") == JobKind.PODCAST
        and job.get("params", {}).get("auto_audio")
    ):
        from brofessor.application import initial_audio

        audio = initial_audio.continue_audio(workspace, job_id, start_worker=False)
        if audio.get("render"):
            wait_for_job(workspace, audio["render_id"])
            audio = initial_audio.state(workspace, job_id)
            audio["artifacts"] = workspace.artifacts(audio["render_id"])
        return {**job, "initial_audio": audio}
    return job


def content_succeeded(job):
    audio = job.get("initial_audio")
    return job["status"] == JobStatus.SUCCEEDED and (
        audio is None or audio.get("render", {}).get("status") == JobStatus.SUCCEEDED
    )


def connection_options(provider, model, ollama_address, *, for_edit=False):
    try:
        connection = preferences.text_connection(provider, for_edit=for_edit)
        if connection["provider"] is None:
            raise ValueError("Choose --provider codex, claude or ollama")
        if model is not None:
            connection["model"] = model.strip() or None
        if ollama_address is not None:
            if connection["provider"] != TextProvider.OLLAMA:
                raise ValueError("--ollama-address applies only to --provider ollama")
            connection["ollama_address"] = ollama_address
        return connection
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error


def submit_and_show(
    workspace,
    kind,
    sources,
    focus,
    language,
    provider,
    model,
    wait,
    request_key,
    *,
    ollama_address,
    **options,
):
    connection = connection_options(provider, model, ollama_address)
    try:
        job = service.submit(
            workspace,
            kind,
            source_ids=sources or None,
            focus=focus,
            language=language,
            request_key=request_key,
            **connection,
            **options,
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    if wait:
        job = wait_for_content(workspace, job["id"])
    show(job)
    if wait and not content_succeeded(job):
        raise typer.Exit(1)


def render_and_show(
    workspace, job_id, *, wait, turn=None, revision=None, model=None, request_key=None
):
    from brofessor.infrastructure.speech.references import MissingVoicePack

    try:
        job = service.render(
            workspace, job_id, turn=turn, model=model, revision=revision, request_key=request_key
        )
    except MissingVoicePack as error:
        cli = ["brofessor", "-w", str(workspace.path)]
        download = shlex.join([*cli, "tts", "download", *([model] if model else []), "--wait"])
        action = ["render", job_id] if turn is None else ["preview-turn", job_id, str(turn)]
        if model:
            action.extend(["--tts-model", model])
        if request_key is not None:
            action.extend(["--request-key", request_key])
        resume = shlex.join([*cli, "draft", *action, "--revision", str(error.revision), "--wait"])
        typer.echo(
            f"{error}\n{download}\nThen continue from the saved revision:\n{resume}", err=True
        )
        raise typer.Exit(1) from error
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    if wait:
        job = wait_for_content(workspace, job["id"])
    show({**job, "artifacts": workspace.artifacts(job["id"])})
    if wait and not content_succeeded(job):
        raise typer.Exit(1)


def _managed(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except (ValueError, OSError, RuntimeError) as error:
        raise CommandError(str(error)) from error


def _project(ctx):
    if ctx.obj is None:
        raise CommandError("Choose a project first: project create NAME or project open PATH")
    return ctx.obj


def _ollama_address(address):
    return address or preferences.text_connection(TextProvider.OLLAMA, for_edit=True).get(
        "ollama_address"
    )
