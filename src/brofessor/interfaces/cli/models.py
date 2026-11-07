"""CLI commands: models."""

import typer

from brofessor.contracts.text import TextProvider
from brofessor.infrastructure.storage.workspace import Workspace
from brofessor.interfaces.cli.common import (
    OllamaAddress,
    _managed,
    _ollama_address,
    _project,
    content_succeeded,
    show,
    wait_for_content,
)

app = typer.Typer(
    no_args_is_help=True, help="Manage shared model downloads and project audio caches."
)


@app.command("list")
def model_inventory(family: str = "speech", ollama_address: OllamaAddress = None):
    from brofessor.application import maintenance

    if family == "speech":
        show(_managed(maintenance.speech_inventory))
    elif family == TextProvider.OLLAMA:
        show(_managed(maintenance.ollama_models, _ollama_address(ollama_address)))
    else:
        raise typer.BadParameter("Choose speech or ollama")


@app.command("download")
def model_download(
    model: str, family: str = "speech", ollama_address: OllamaAddress = None, wait: bool = False
):
    from brofessor.application import maintenance

    if family == "speech":
        job = _managed(maintenance.download_speech, model)
    elif family == TextProvider.OLLAMA:
        job = _managed(maintenance.download_ollama, _ollama_address(ollama_address), model)
    else:
        raise typer.BadParameter("Choose speech or ollama")
    if wait:
        job = wait_for_content(Workspace(job["workspace_path"]), job["id"])
    show(job)
    if wait and not content_succeeded(job):
        raise typer.Exit(1)


@app.command("remove")
def model_remove(model: str, family: str = "speech", ollama_address: OllamaAddress = None):
    """Remove the named downloaded weights, retaining defaults and project data."""
    from brofessor.application import maintenance

    if family == "speech":
        show(_managed(maintenance.remove_speech, model))
    elif family == TextProvider.OLLAMA:
        show(_managed(maintenance.remove_ollama, _ollama_address(ollama_address), model))
    else:
        raise typer.BadParameter("Choose speech or ollama")


@app.command("clear-partial")
def model_clear_partial(model: str):
    from brofessor.application import maintenance

    show(_managed(maintenance.clear_partial, model))


@app.command("audio-cache")
def model_audio_cache(ctx: typer.Context, clear: bool = False):
    """Inspect or clear only the selected project's resynthesizable speech segments."""
    from brofessor.application import maintenance

    show(
        _managed(
            maintenance.clear_audio_cache if clear else maintenance.audio_cache_info, _project(ctx)
        )
    )


@app.command("jobs")
def model_jobs():
    from brofessor.application import maintenance

    show(_managed(maintenance.jobs))


@app.command("cancel")
def model_cancel(job_id: str):
    from brofessor.application import maintenance

    show(_managed(maintenance.cancel, job_id))


@app.command("resume")
def model_resume(job_id: str, wait: bool = False):
    from brofessor.application import maintenance

    job = _managed(maintenance.resume, job_id)
    w = Workspace(job["workspace_path"])
    if wait:
        job = wait_for_content(w, job["id"])
    show(job)
    if wait and not content_succeeded(job):
        raise typer.Exit(1)
