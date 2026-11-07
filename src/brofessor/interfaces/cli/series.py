"""CLI commands: series."""

import typer

from brofessor.application import service
from brofessor.contracts.content import ContentLanguage
from brofessor.contracts.jobs import JobKind
from brofessor.interfaces.cli.common import (
    OllamaAddress,
    content_succeeded,
    show,
    submit_and_show,
    wait_for_content,
)

app = typer.Typer(no_args_is_help=True, help="Plan a podcast series and prepare its episodes.")


@app.command("plan")
def plan_series(
    ctx: typer.Context,
    focus: str = "",
    episodes: int = 3,
    minutes: int = 20,
    language: str = ContentLanguage.RU,
    provider: str | None = None,
    model: str | None = None,
    ollama_address: OllamaAddress = None,
    source: list[str] = typer.Option(None),
    wait: bool = False,
    request_key: str | None = None,
    speech_model: str | None = None,
    writing_method: str | None = typer.Option(
        None, help="classic (default) or originals for future episodes."
    ),
    title: str = "",
    auto_audio: bool = True,
):
    """Save an editable series plan. Minutes is the target for each episode."""
    submit_and_show(
        ctx.obj,
        JobKind.PODCAST_SERIES,
        source,
        focus,
        language,
        provider,
        model,
        wait,
        request_key,
        ollama_address=ollama_address,
        title=title,
        minutes=minutes,
        episode_count=episodes,
        speech_model=speech_model,
        auto_audio=auto_audio,
        writing_method=writing_method,
    )


@app.command("episode")
def prepare_series_episode(
    ctx: typer.Context,
    series_id: str,
    number: int,
    revision: int | None = None,
    wait: bool = False,
):
    """Prepare an episode and follow the saved automatic narration policy."""
    job = service.series_episode(ctx.obj, series_id, number, revision=revision)
    if wait:
        job = wait_for_content(ctx.obj, job["id"])
    show(job)
    if wait and not content_succeeded(job):
        raise typer.Exit(1)
