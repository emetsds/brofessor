"""CLI client of the same services used by Streamlit."""

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Annotated

import typer
from click import ClickException

from . import projects, service
from .executors import DEFAULT_OLLAMA_PORT
from .workspace import Workspace

OllamaPort = Annotated[
    int, typer.Option(min=1, max=65535, help="Port of the local Ollama server (127.0.0.1).")
]

app = typer.Typer(no_args_is_help=True, help="brofessor: sources, podcasts and presentations")
source_app = typer.Typer(no_args_is_help=True)
job_app = typer.Typer(no_args_is_help=True)
draft_app = typer.Typer(no_args_is_help=True)
note_app = typer.Typer(
    no_args_is_help=True, help="Create and edit project notes without a model call."
)
project_app = typer.Typer(no_args_is_help=True, help="Create, open and select local projects.")
tts_app = typer.Typer(no_args_is_help=True, help="List, download and select local speech models.")
series_app = typer.Typer(
    no_args_is_help=True, help="Plan a podcast series and prepare its episodes."
)
voice_app = typer.Typer(
    no_args_is_help=True, help="Set WAV voice samples and transcripts for F5/ESpeech."
)
tts_app.add_typer(voice_app, name="voice")
app.add_typer(source_app, name="source")
app.add_typer(job_app, name="job")
app.add_typer(draft_app, name="draft")
app.add_typer(note_app, name="note")
app.add_typer(project_app, name="project")
app.add_typer(tts_app, name="tts")
app.add_typer(series_app, name="series")


def show(value):
    typer.echo(json.dumps(value, ensure_ascii=False, indent=2))


@app.callback()
def main(
    ctx: typer.Context,
    workspace: Path | None = typer.Option(None, "--workspace", "-w", envvar="BROFESSOR_WORKSPACE"),
):
    if ctx.invoked_subcommand in ("project", "doctor"):
        ctx.obj = None
        return
    if workspace is None:
        current = projects.selected()
        if current is not None:
            if not current["available"] and ctx.invoked_subcommand not in ("ui", "tts"):
                raise ClickException(
                    "Selected project folder is unavailable. Use project open PATH"
                )
            workspace = Path(current["path"]) if current["available"] else None
        elif ctx.invoked_subcommand == "init":
            workspace = Path(projects.create("Default")["path"])
        elif ctx.invoked_subcommand not in ("ui", "tts"):
            raise ClickException("Choose a project first: project create NAME or project open PATH")
    ctx.obj = Workspace(workspace) if workspace is not None else None


@project_app.command("list")
def list_projects():
    show(projects.list_projects())


@project_app.command("create")
def create_project(name: str, directory: Path | None = None):
    """Create a project in the chosen projects directory and select it."""
    show(projects.create(name, root=directory))


@project_app.command("open")
def open_project(path: Path, name: str | None = None):
    """Register an existing workspace folder and select it without copying data."""
    show(projects.open_project(path, name=name))


@project_app.command("use")
def use_project(name: str):
    """Select a registered project by name or absolute path."""
    show(projects.use(name))


@tts_app.command("list")
def list_tts_models():
    from .speech_models import list_models

    show(list_models())


@tts_app.command("use")
def use_tts_model(model: str):
    from .speech_models import use

    show(use(model))


@tts_app.command("download")
def download_tts_model(ctx: typer.Context, model: str, wait: bool = False):
    """Download a pinned model in a background job; --wait shows progress on stderr."""
    if ctx.obj is None:
        raise ClickException("Choose a project first: project create NAME or project open PATH")
    job = service.download_model(ctx.obj, model)
    if wait:
        previous = None
        while job["status"] in ("queued", "running"):
            state = (job["progress"].get("completed", 0), job["progress"].get("total", 0))
            if state != previous and state[1]:
                typer.echo(f"{state[0] / 1e6:.0f} / {state[1] / 1e6:.0f} MB", err=True)
                previous = state
            time.sleep(0.25)
            from .worker import is_running

            if not is_running(ctx.obj):
                job = wait_for_job(ctx.obj, job["id"])
                break
            job = ctx.obj.job(job["id"])
    show(job)
    if wait and job["status"] != "succeeded":
        raise typer.Exit(1)


@voice_app.command("list")
def list_voice_samples(language: str = "ru"):
    from .speech_references import list_references

    show(list_references(language))


@voice_app.command("set")
def set_voice_sample(
    role: str,
    audio: Path = typer.Option(..., exists=True, dir_okay=False),
    text: str = typer.Option(...),
    language: str = "ru",
):
    from .speech_references import save

    show(save(role, language, audio.read_bytes(), text))


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
def search(ctx: typer.Context, query: str, source: list[str] = typer.Option(None), limit: int = 8):
    """Search original words locally; no model call or automatic translation."""
    show(service.search(ctx.obj, query, source_ids=source, limit=limit))


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
    episode_count=3,
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
        episode_count=episode_count,
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
    language: str | None = None,
    source: list[str] = typer.Option(None),
    wait: bool = False,
    request_key: str | None = None,
    reply_to: str | None = typer.Option(
        None, help="Continue a saved answer; inherits its sources and provider."
    ),
    revision: int | None = typer.Option(None, help="Saved parent-answer revision for --reply-to."),
):
    """Ask a grounded question over the selected sources."""
    if reply_to is not None:
        if any(
            getattr(ctx.get_parameter_source(name), "name", None) == "COMMANDLINE"
            for name in ("source", "provider", "model", "ollama_port")
        ):
            raise typer.BadParameter(
                "Follow-ups inherit sources, provider, model and Ollama port; omit those flags."
            )
        try:
            job = service.follow_up(
                ctx.obj,
                reply_to,
                question,
                revision=revision,
                language=language,
                request_key=request_key,
            )
        except ValueError as error:
            raise typer.BadParameter(str(error)) from error
        if wait:
            job = wait_for_job(ctx.obj, job["id"])
        show(job)
        if wait and job["status"] != "succeeded":
            raise typer.Exit(1)
        return
    if revision is not None:
        raise typer.BadParameter("--revision requires --reply-to")
    submit_and_show(
        ctx.obj,
        "ask",
        source,
        question,
        language or "ru",
        provider,
        model,
        20,
        8,
        wait,
        request_key,
        ollama_port=ollama_port,
    )


@note_app.command("create")
def create_note(
    ctx: typer.Context, title: str, path: Path, citation: list[str] = typer.Option(None)
):
    """Create a note from a UTF-8 text/Markdown file."""
    show(
        service.save_note(
            ctx.obj,
            {"title": title, "text": path.read_text(encoding="utf-8"), "citations": citation or []},
        )
    )


@note_app.command("list")
def list_notes(ctx: typer.Context):
    show(ctx.obj.notes())


@note_app.command("show")
def show_note(ctx: typer.Context, note_id: str, revision: int | None = None):
    note = ctx.obj.note(note_id, revision)
    if note is None:
        raise typer.BadParameter("The requested note revision does not exist")
    note["evidence"] = service.note_evidence(ctx.obj, note_id, note["revision"])
    show(note)


@note_app.command("save")
def save_note(ctx: typer.Context, note_id: str, path: Path, expected_revision: int):
    """Save only the edited data object as JSON, preserving note origin and history."""
    show(
        service.save_note(
            ctx.obj,
            json.loads(path.read_text(encoding="utf-8")),
            note_id=note_id,
            expected_revision=expected_revision,
        )
    )


@note_app.command("from-answer")
def note_from_answer(
    ctx: typer.Context, job_id: str, revision: int | None = None, title: str | None = None
):
    """Save an answer revision once; repeating this preserves your note edits."""
    show(service.note_from_answer(ctx.obj, job_id, revision=revision, title=title))


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


@series_app.command("plan")
def plan_series(
    ctx: typer.Context,
    focus: str = "",
    episodes: int = 3,
    minutes: int = 20,
    language: str = "ru",
    provider: str = "codex",
    model: str | None = None,
    ollama_port: OllamaPort = DEFAULT_OLLAMA_PORT,
    source: list[str] = typer.Option(None),
    wait: bool = False,
    request_key: str | None = None,
):
    """Save an editable series plan. Minutes is the target for each episode."""
    submit_and_show(
        ctx.obj,
        "podcast_series",
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
        episode_count=episodes,
    )


@series_app.command("episode")
def prepare_series_episode(
    ctx: typer.Context,
    series_id: str,
    number: int,
    revision: int | None = None,
    wait: bool = False,
):
    """Prepare one episode from a saved plan revision, then use draft render."""
    job = service.series_episode(ctx.obj, series_id, number, revision=revision)
    if wait:
        job = wait_for_job(ctx.obj, job["id"])
    show(job)
    if wait and job["status"] != "succeeded":
        raise typer.Exit(1)


@job_app.command("list")
def list_jobs(ctx: typer.Context):
    show(ctx.obj.jobs())


@job_app.command("show")
def show_job(ctx: typer.Context, job_id: str):
    show({**ctx.obj.job(job_id), "artifacts": ctx.obj.artifacts(job_id)})


@job_app.command("cancel")
def cancel_job(ctx: typer.Context, job_id: str):
    show(ctx.obj.cancel(job_id))


@job_app.command("coverage")
def show_coverage(ctx: typer.Context, job_id: str):
    """Show fragment reading status and citations in the saved result."""
    show(service.coverage(ctx.obj, job_id))


@job_app.command("resume")
def resume_job(ctx: typer.Context, job_id: str):
    from .worker import ensure_worker

    result = ctx.obj.resume(job_id)
    ensure_worker(ctx.obj)
    show(result)


@draft_app.command("show")
def show_draft(ctx: typer.Context, job_id: str):
    draft = ctx.obj.draft(job_id)
    if draft and ctx.obj.job(job_id)["kind"] == "ask":
        draft["evidence"] = service.answer_evidence(ctx.obj, job_id, draft["revision"])
        if ctx.obj.job(job_id)["params"].get("conversation"):
            draft["conversation"] = service.question_context(ctx.obj, job_id)
    show(draft)


@draft_app.command("save")
def save_draft(ctx: typer.Context, job_id: str, path: Path, expected_revision: int):
    """Save the JSON data object as a new revision, preserving previous edits."""
    show(service.edit_draft(ctx.obj, job_id, json.loads(path.read_text()), expected_revision))


@draft_app.command("render")
def render_draft(
    ctx: typer.Context,
    job_id: str,
    model: str | None = typer.Option(
        None,
        "--tts-model",
        "--model",
        help="Speech model ID from tts list, repo@revision, or local folder.",
    ),
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
    if ctx.obj is not None:
        projects.open_project(ctx.obj.path)
    workspace_args = ["--workspace", str(ctx.obj.path)] if ctx.obj is not None else []
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
                *workspace_args,
                "--ollama-port",
                str(ollama_port),
            ]
        )
    )


if __name__ == "__main__":
    app()
