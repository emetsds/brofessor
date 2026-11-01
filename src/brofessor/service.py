"""User operations shared by the CLI and Streamlit. No frontend imports."""

from pathlib import Path

from .executors import DEFAULT_OLLAMA_PORT, ollama_url
from .models import Answer, Podcast, Slides, validate_citations
from .workspace import Workspace, atomic_json


def submit(
    workspace: Workspace,
    kind: str,
    *,
    source_ids=None,
    focus="",
    language="ru",
    provider="codex",
    model=None,
    ollama_port=DEFAULT_OLLAMA_PORT,
    minutes=20,
    slide_count=8,
    request_key=None,
    start_worker=True,
) -> dict:
    if kind not in ("ask", "podcast", "slides"):
        raise ValueError("Choose ask, podcast or slides")
    if provider not in ("codex", "claude", "ollama"):
        raise ValueError("Choose codex, claude or ollama")
    ollama_url(ollama_port)
    if language not in ("ru", "en"):
        raise ValueError("Choose ru or en")
    if not 1 <= minutes <= 60 or not 1 <= slide_count <= 40:
        raise ValueError("Minutes must be 1–60 (under 20 is preview), slides 1–40")
    ids = source_ids if source_ids is not None else [s["id"] for s in workspace.sources()]
    known = {s["id"] for s in workspace.sources()}
    if not ids or not set(ids) <= known:
        raise ValueError("Select existing sources before starting a job")
    if kind == "ask" and not focus.strip():
        raise ValueError("A question is required")
    params = {
        "source_ids": ids,
        "focus": focus,
        "language": language,
        "provider": provider,
        "model": model,
        "minutes": minutes,
        "slide_count": slide_count,
    }
    # Omit the default to preserve request keys for jobs created before port selection.
    if provider == "ollama" and ollama_port != DEFAULT_OLLAMA_PORT:
        params["ollama_port"] = ollama_port
    result = workspace.submit(kind, params, request_key)
    if start_worker:
        from .worker import ensure_worker

        ensure_worker(workspace)
    return result


def edit_draft(workspace: Workspace, job_id: str, data: dict, expected_revision: int) -> dict:
    job = workspace.job(job_id)
    schema = {"ask": Answer, "podcast": Podcast, "slides": Slides}.get(job["kind"])
    if schema is None:
        raise ValueError("This job has no editable draft")
    value = schema.model_validate(data).model_dump()
    allowed = {u["id"] for u in workspace.units(job["params"]["source_ids"])}
    validate_citations(value, allowed)
    saved = workspace.save_draft(job_id, value, expected_revision)
    output = workspace.path / "jobs" / job_id / f"draft-r{saved['revision']}.json"
    atomic_json(output, saved["data"])
    workspace.add_artifact(job_id, output, "json", {"revision": saved["revision"]})
    return saved


def render(
    workspace: Workspace, draft_job_id: str, *, model=None, request_key=None, start_worker=True
) -> dict:
    original = workspace.job(draft_job_id)
    draft = workspace.draft(draft_job_id)
    if original["kind"] not in ("podcast", "slides") or draft is None:
        raise ValueError("Generate a podcast or slides draft first")
    if original["kind"] == "podcast":
        from .speech_models import reference

        model = reference(model)
    result = workspace.submit(
        "render_" + original["kind"],
        {
            "draft_job_id": draft_job_id,
            "revision": draft["revision"],
            "model": model,
            "minutes": original["params"]["minutes"],
        },
        request_key,
    )
    if start_worker:
        from .worker import ensure_worker

        ensure_worker(workspace)
    return result


def download_model(workspace: Workspace, model: str, *, start_worker=True) -> dict:
    from .speech_models import get

    item = get(model)
    job = workspace.submit("download_model", {"model": item["id"]})
    if start_worker:
        from .worker import ensure_worker

        ensure_worker(workspace)
    return job


def artifact_path(workspace: Workspace, path: str) -> Path:
    resolved = (workspace.path / path).resolve()
    if not resolved.is_relative_to(workspace.path):
        raise ValueError("Artifact is outside the workspace")
    return resolved
