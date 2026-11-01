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
        from .speech_models import get, reference

        model = reference(model)
    kind = "render_" + original["kind"]
    params = {
        "draft_job_id": draft_job_id,
        "revision": draft["revision"],
        "model": model,
        "minutes": original["params"]["minutes"],
    }
    previous = workspace.job_by_request_key(request_key) if request_key else None
    if (
        previous
        and previous["kind"] == kind
        and {key: value for key, value in previous["params"].items() if key != "model_spec"}
        == params
    ):
        # The first submit owns its snapshot, including legacy jobs without one.
        params = previous["params"]
    elif original["kind"] == "podcast":
        try:
            spec = get(model)
        except ValueError:
            spec = None  # The existing explicit repo@revision/local-directory API.
        if spec and draft["data"]["language"] not in spec["languages"]:
            raise ValueError(f"Selected speech model does not support {draft['data']['language']}")
        if spec:
            from .speech import validate_text

            for turn in draft["data"]["turns"]:
                validate_text(spec, turn["text"])
            if spec.get("requires_reference"):
                from .speech_references import freeze, selected

                spec["references"] = freeze(workspace.path, selected(draft["data"]["language"]))
            params["model_spec"] = spec
    result = workspace.submit(kind, params, request_key)
    if start_worker:
        from .worker import ensure_worker

        ensure_worker(workspace)
    return result


def render_request_key(workspace: Workspace, draft_job_id: str, model: str) -> str:
    """Stable UI audio request identity, retaining matching pre-snapshot jobs."""
    from .speech_models import reference

    draft = workspace.draft(draft_job_id)
    base = f"render:{draft_job_id}:{draft['revision']}"
    resolved = reference(model)
    from .speech_models import get

    try:
        spec = get(model)
    except ValueError:
        spec = {}
    if spec.get("requires_reference"):
        import hashlib
        import json
        from .speech_references import selected

        refs = {
            role: {key: value for key, value in item.items() if key in ("sha256", "text")}
            for role, item in selected(draft["data"]["language"]).items()
        }
        resolved += ":" + hashlib.sha256(json.dumps(refs, sort_keys=True).encode()).hexdigest()[:16]
    legacy = f"{base}:{model}"
    previous = workspace.job_by_request_key(legacy)
    if (
        previous
        and previous["kind"] == "render_podcast"
        and previous["params"]["model"] == resolved
    ):
        return legacy
    return f"{base}:{resolved}"


def download_model(workspace: Workspace, model: str, *, start_worker=True) -> dict:
    from .speech_models import get

    item = get(model)
    job = workspace.submit("download_model", {"model": item["id"], "model_spec": item})
    if start_worker:
        from .worker import ensure_worker

        ensure_worker(workspace)
    return job


def artifact_path(workspace: Workspace, path: str) -> Path:
    resolved = (workspace.path / path).resolve()
    if not resolved.is_relative_to(workspace.path):
        raise ValueError("Artifact is outside the workspace")
    return resolved
