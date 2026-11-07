"""CLI commands: jobs."""

import typer

from brofessor.application import service
from brofessor.interfaces.cli.common import (
    show,
)

app = typer.Typer(no_args_is_help=True)


@app.command("sources")
def job_sources(ctx: typer.Context, job_id: str):
    """Show the saved navigation trace and exact originals used by this task."""
    from brofessor.features.sources.navigation import report

    show(report(ctx.obj, ctx.obj.job(job_id)))


@app.command("list")
def list_jobs(ctx: typer.Context):
    show(ctx.obj.jobs())


@app.command("show")
def show_job(ctx: typer.Context, job_id: str):
    show({**ctx.obj.job(job_id), "artifacts": ctx.obj.artifacts(job_id)})


@app.command("cancel")
def cancel_job(ctx: typer.Context, job_id: str):
    show(ctx.obj.cancel(job_id))


@app.command("coverage")
def show_coverage(ctx: typer.Context, job_id: str):
    """Show fragment reading status and citations in the saved result."""
    show(service.coverage(ctx.obj, job_id))


@app.command("resume")
def resume_job(ctx: typer.Context, job_id: str):
    from brofessor.application.worker import ensure_worker

    result = ctx.obj.resume(job_id)
    ensure_worker(ctx.obj)
    show(result)
