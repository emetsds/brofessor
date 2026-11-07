"""CLI commands: speech."""

from pathlib import Path

import typer

from brofessor.application import service
from brofessor.contracts.content import ContentLanguage
from brofessor.infrastructure.speech.catalogue import DEFAULT_ID
from brofessor.infrastructure.storage.workspace import Workspace
from brofessor.interfaces.cli.common import (
    content_succeeded,
    show,
    wait_for_content,
)

app = typer.Typer(no_args_is_help=True, help="Inspect and download local speech support.")


voice_app = typer.Typer(
    no_args_is_help=True, help="Set WAV voice samples and transcripts for F5/ESpeech."
)

app.add_typer(voice_app, name="voice", hidden=True)


@app.command("list")
def list_tts_models():
    from brofessor.infrastructure.speech.catalogue import list_models

    show(list_models())


@app.command("use", hidden=True)
def use_tts_model(model: str):
    from brofessor.infrastructure.speech.catalogue import use

    show(use(model))


@app.command("download")
def download_tts_model(
    ctx: typer.Context, model: str = typer.Argument(DEFAULT_ID), wait: bool = False
):
    """Download a pinned model in a background job; --wait shows progress on stderr."""
    if ctx.obj is None:
        from brofessor.application import maintenance

        job = maintenance.download_speech(model)
        target = Workspace(job["workspace_path"])
    else:
        target = ctx.obj
        job = service.download_model(target, model)
    if wait:
        job = wait_for_content(target, job["id"])
    show(job)
    if wait and not content_succeeded(job):
        raise typer.Exit(1)


@voice_app.command("list")
def list_voice_samples(language: str = ContentLanguage.RU):
    from brofessor.infrastructure.speech.references import list_references

    show(list_references(language))


@voice_app.command("set")
def set_voice_sample(
    role: str,
    audio: Path = typer.Option(..., exists=True, dir_okay=False),
    text: str = typer.Option(...),
    language: str = ContentLanguage.RU,
):
    from brofessor.infrastructure.speech.references import save

    show(save(role, language, audio.read_bytes(), text))
