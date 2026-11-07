"""Inspect editable templates and preview their complete local message framing."""

import json
from contextlib import nullcontext
from pathlib import Path

import typer

from brofessor import prompts
from brofessor.contracts.jobs import TEXT_JOB_KINDS
from brofessor.contracts.text import TextProvider
from brofessor.infrastructure.storage.workspace import DATABASE_FILENAME, Workspace
from brofessor.interfaces.cli.common import CommandError, show
from brofessor.prompts import examples

app = typer.Typer(no_args_is_help=True, help="Read and preview prompts without model calls.")


def _scope(ctx, job, legacy):
    if job and legacy:
        raise CommandError("Choose --job or --legacy")
    if job:
        if ctx.obj is None:
            raise CommandError("Use --workspace PATH before prompts to inspect a saved job")
        path = Path(ctx.obj).expanduser().resolve()
        if not (path / DATABASE_FILENAME).is_file():
            raise CommandError("The project folder is unavailable")
        saved = Workspace(path).job(job)
        if saved["kind"] not in TEXT_JOB_KINDS:
            raise CommandError("Choose a text-generation job")
        return prompts.use_snapshot(saved["params"].get(prompts.SNAPSHOT_KEY))
    return prompts.use_snapshot(None) if legacy else nullcontext()


@app.command("list")
def list_prompts():
    """List IDs, editable paths, purposes, variables, schemas and shared parts."""
    show(
        {
            key: {**value, "location": str(prompts.location(key))}
            for key, value in prompts.catalogue().items()
        }
    )


@app.command("show")
def show_prompt(ctx: typer.Context, identifier: str, job: str | None = None, legacy: bool = False):
    """Print exact template text; --job reads frozen inputs, --legacy the migration set."""
    try:
        with _scope(ctx, job, legacy):
            # Populate each named variable with its own literal marker to show the template.
            spec = prompts.catalogue().get(identifier)
            if spec is None:
                raise prompts.PromptError(f"Unknown prompt ID: {identifier}")
            text = prompts.render(
                identifier, **{name: "{{" + name + "}}" for name in spec["variables"]}
            )
            typer.echo(text, nl=False)
    except (OSError, ValueError, KeyError) as error:
        raise CommandError(str(error)) from error


@app.command("preview")
def preview_prompt(
    ctx: typer.Context,
    identifier: str | None = typer.Argument(None),
    provider: str = TextProvider.CODEX,
    variables: Path | None = typer.Option(
        None, help="JSON object of named inputs; omitted for a synthetic example."
    ),
    all_templates: bool = typer.Option(False, "--all", help="Preview every available template."),
    job: str | None = typer.Option(
        None,
        help="Use a saved job's templates with the preview inputs; does not replay its sources.",
    ),
    legacy: bool = False,
):
    """Show composed messages, including runner instructions; no model, shell or network call."""
    if bool(identifier) == all_templates:
        raise CommandError("Choose a prompt ID or --all")
    if all_templates and variables:
        raise CommandError("Use --variables with one prompt ID")
    try:
        inputs = json.loads(variables.read_text(encoding="utf-8")) if variables else None
        with _scope(ctx, job, legacy):
            if all_templates:
                result = [
                    examples.preview(key, provider=provider) for key in sorted(prompts.available())
                ]
            else:
                result = examples.preview(identifier, provider=provider, variables=inputs)
            show(result)
    except (OSError, ValueError, KeyError) as error:
        raise CommandError(str(error)) from error
