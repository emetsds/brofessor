"""CLI commands: tasks."""

import typer

from brofessor.application import projects, service
from brofessor.contracts.jobs import ALL_TASK_KINDS_FILTER
from brofessor.infrastructure.storage import preferences
from brofessor.interfaces.cli.common import (
    OllamaAddress,
    _managed,
    _project,
    content_succeeded,
    show,
    wait_for_content,
)

app = typer.Typer(no_args_is_help=True, help="Inspect tasks and choose models for future runs.")


@app.command("list")
def list_tasks(
    ctx: typer.Context, deleted: bool = False, query: str = "", kind: str = ALL_TASK_KINDS_FILTER
):
    from brofessor.application import tasks

    show(_managed(tasks.list_tasks, _project(ctx), deleted=deleted, query=query, kind=kind))


@app.command("delete")
def delete_task(ctx: typer.Context, task_id: str, yes: bool = typer.Option(False, "--yes", "-y")):
    """Move a whole task, including related runs, into the project's trash."""
    from brofessor.application import tasks

    if not yes:
        typer.confirm("Move this task and all related runs to trash?", abort=True)
    show(_managed(tasks.delete, _project(ctx), task_id))


@app.command("restore")
def restore_task(ctx: typer.Context, task_id: str):
    """Restore a complete task from trash."""
    from brofessor.application import tasks

    show(_managed(tasks.restore, _project(ctx), task_id))


@app.command("recent")
def recent_tasks(limit: int = typer.Option(20, min=1, max=30)):
    from brofessor.application import tasks

    show(_managed(tasks.recent_tasks, limit))


@app.command("show")
def show_task(ctx: typer.Context, task_id: str):
    from brofessor.application import tasks

    w = _project(ctx)
    job = _managed(w.job, task_id)
    models = _managed(tasks.models, w, task_id)
    notice = tasks.record_open(w, task_id)
    from brofessor.application.progress import snapshot

    show(
        {
            "job": job,
            "title": tasks.title(w, job),
            "models": models,
            "details": service.task_details(w, task_id),
            "workflow": snapshot(w, task_id),
            **({"notice": notice} if notice else {}),
        }
    )


@app.command("models")
def task_models(
    ctx: typer.Context,
    task_id: str,
    provider: str | None = None,
    model: str | None = None,
    ollama_address: OllamaAddress = None,
    speech_model: str | None = None,
    use_defaults: bool = False,
    expected_revision: int | None = None,
):
    """Show or save persistent model choices for future runs of this task."""
    from brofessor.application import tasks

    w = _project(ctx)
    saved = _managed(tasks.models, w, task_id)
    version = saved["revision"] if expected_revision is None else expected_revision
    custom = any(v is not None for v in (provider, model, ollama_address, speech_model))
    if use_defaults and custom:
        raise typer.BadParameter("Choose defaults or explicit model settings")
    if use_defaults:
        saved = _managed(tasks.apply_defaults, w, task_id, version)
    elif custom:
        values = dict(saved["data"])
        if provider is not None and provider != values.get("provider"):
            choice = _managed(preferences.text_connection, provider, for_edit=True)
            values = {
                k: v for k, v in values.items() if k not in ("provider", "model", "ollama_address")
            }
            values.update(choice)
        if model is not None:
            values["model"] = model
        if ollama_address is not None:
            values["ollama_address"] = ollama_address
        if speech_model is not None:
            values["speech_model"] = speech_model
        saved = _managed(tasks.save_models, w, task_id, values, version)
    show(saved)


@app.command("regenerate")
def regenerate_task(
    ctx: typer.Context,
    task_id: str,
    revision: int | None = None,
    request_key: str | None = None,
    wait: bool = False,
):
    from brofessor.application import tasks

    w = _project(ctx)
    job = _managed(tasks.regenerate, w, task_id, revision=revision, request_key=request_key)
    if wait:
        job = wait_for_content(w, job["id"])
    show(job)
    if wait and not content_succeeded(job):
        raise typer.Exit(1)


@app.command("rename")
def rename_task(ctx: typer.Context, task_id: str, title: str):
    from brofessor.application import tasks

    show(_managed(tasks.rename, _project(ctx), task_id, title))


@app.command("audio")
def initial_task_audio(
    ctx: typer.Context, task_id: str, cancel: bool = False, resume: bool = False
):
    """Inspect, cancel or resume the task's pinned first narration."""
    from brofessor.application import initial_audio

    if cancel and resume:
        raise typer.BadParameter("Choose either --cancel or --resume")
    function = (
        initial_audio.cancel if cancel else initial_audio.resume if resume else initial_audio.state
    )
    show(_managed(function, _project(ctx), task_id))


@app.command("progress")
def task_progress(ctx: typer.Context, task_id: str):
    from brofessor.application.progress import snapshot

    show(_managed(snapshot, _project(ctx), task_id))


@app.command("search")
def search_all_tasks(query: str):
    """Find projects and grouped tasks by word prefixes, without changing recent tasks."""
    from brofessor.application import tasks

    show(tasks.search_projects(projects.list_projects(), query))
