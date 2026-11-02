"""User operations shared by the CLI and Streamlit. No frontend imports."""

import json
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
    episode_count=3,
    request_key=None,
    start_worker=True,
) -> dict:
    if kind not in ("ask", "podcast", "slides", "podcast_series"):
        raise ValueError("Choose ask, podcast, slides or podcast_series")
    if provider not in ("codex", "claude", "ollama"):
        raise ValueError("Choose codex, claude or ollama")
    ollama_url(ollama_port)
    if language not in ("ru", "en"):
        raise ValueError("Choose ru or en")
    if not 1 <= minutes <= 60 or not 1 <= slide_count <= 40:
        raise ValueError("Minutes must be 1–60 (under 20 is preview), slides 1–40")
    if kind == "podcast_series" and (
        type(episode_count) is not int or not 2 <= episode_count <= 12 or minutes < 20
    ):
        raise ValueError("Series need 2–12 episodes, each 20–60 minutes")
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
    if kind == "podcast_series":
        params["episode_count"] = episode_count
    result = workspace.submit(kind, params, request_key)
    if start_worker:
        from .worker import ensure_worker

        ensure_worker(workspace)
    return result


def edit_draft(workspace: Workspace, job_id: str, data: dict, expected_revision: int) -> dict:
    from .series import Series

    job = workspace.job(job_id)
    schema = {"ask": Answer, "podcast": Podcast, "slides": Slides, "podcast_series": Series}.get(
        job["kind"]
    )
    if schema is None:
        raise ValueError("This job has no editable draft")
    value = schema.model_validate(data).model_dump()
    allowed = {u["id"] for u in workspace.units(job["params"]["source_ids"])}
    validate_citations(value, allowed)
    if job["kind"] == "ask":
        from .questions import validate_answer

        previous = workspace.draft(job_id)
        require_quotes = "quotes" in data or (previous is not None and "quotes" in previous["data"])
        validate_answer(
            value, workspace.units(job["params"]["source_ids"]), require_quotes=require_quotes
        )
        if not require_quotes and "quotes" not in data:
            value.pop("quotes")  # Preserve legacy answers without claiming quote verification.
    saved = workspace.save_draft(job_id, value, expected_revision)
    output = workspace.path / "jobs" / job_id / f"draft-r{saved['revision']}.json"
    atomic_json(output, saved["data"])
    workspace.add_artifact(job_id, output, "json", {"revision": saved["revision"]})
    return saved


def follow_up(
    workspace,
    job_id,
    question,
    *,
    revision=None,
    language=None,
    request_key=None,
    start_worker=True,
):
    from . import questions

    if not question.strip():
        raise ValueError("A question is required")
    parent, draft = questions.saved_answer(workspace, job_id, revision)
    params = {
        key: value
        for key, value in parent["params"].items()
        if key not in ("conversation", "conversation_omitted")
    }
    params["focus"] = question
    params["language"] = language if language is not None else params["language"]
    if params["language"] not in ("ru", "en"):
        raise ValueError("Choose ru or en")
    references = [
        *parent["params"].get("conversation", []),
        {"job_id": job_id, "revision": draft["revision"]},
    ]
    omitted = parent["params"].get("conversation_omitted", 0)
    while True:
        try:
            questions.history(workspace, references, params["source_ids"])
            break
        except questions.HistoryLimit:
            if len(references) == 1:
                raise
            references.pop(0)
            omitted += 1
    params["conversation"] = references
    if omitted:
        params["conversation_omitted"] = omitted
    result = workspace.submit("ask", params, request_key)
    if start_worker:
        from .worker import ensure_worker

        ensure_worker(workspace)
    return result


def save_note(workspace, data, *, note_id=None, expected_revision=0):
    from .models import Note

    value = Note.model_validate(data).model_dump()
    validate_citations(value, {u["id"] for u in workspace.units() if u["status"] == "ready"})
    if note_id is None:
        if expected_revision != 0:
            raise ValueError("New notes start at revision 1")
        return workspace.create_note(value)
    return workspace.save_note(note_id, value, expected_revision)


def note_from_answer(workspace, job_id, *, revision=None, title=None):
    import hashlib
    from .questions import saved_answer
    from .models import Note

    job, draft = saved_answer(workspace, job_id, revision)
    origin = {"job_id": job_id, "revision": draft["revision"]}
    note_id = hashlib.sha256(f"answer:{job_id}:r{draft['revision']}".encode()).hexdigest()[:16]
    value = Note(
        title=title if title is not None else job["params"]["focus"][:120],
        text=draft["data"]["answer"],
        citations=draft["data"]["citations"],
    ).model_dump()
    validate_citations(value, {u["id"] for u in workspace.units() if u["status"] == "ready"})
    result = workspace.create_note(value, note_id=note_id, origin=origin)
    if result["origin"] != origin:
        raise ValueError("Note ID collision")
    return result


def note_evidence(workspace, note_id, revision=None):
    note = workspace.note(note_id, revision)
    if note is None:
        raise ValueError("The requested note revision does not exist")
    names = {s["id"]: s["name"] for s in workspace.sources()}
    units = {u["id"]: u for u in workspace.units()}
    return [
        {
            "citation": key,
            "source": names[units[key]["source_id"]],
            "locator": units[key]["locator"],
            "text": units[key]["text"],
        }
        for key in note["data"]["citations"]
    ]


def question_context(workspace, job_id):
    from .questions import history

    job = workspace.job(job_id)
    if job["kind"] != "ask":
        raise ValueError("Choose a question job")
    return {
        "turns": history(
            workspace, job["params"].get("conversation", []), job["params"]["source_ids"]
        ),
        "omitted": job["params"].get("conversation_omitted", 0),
    }


def series_episode(workspace, series_job_id, number, *, revision=None, start_worker=True):
    """Pin one saved plan revision; repeated requests reuse the same episode job."""
    from .series import Series, episode_context

    parent = workspace.job(series_job_id)
    if parent["kind"] != "podcast_series" or parent["status"] != "succeeded":
        raise ValueError("Choose a completed podcast series plan")
    draft = workspace.draft(series_job_id, revision)
    if draft is None:
        raise ValueError("The requested series plan revision does not exist")
    plan = Series.model_validate(draft["data"]).model_dump()
    episode_context(plan, number)
    params = {key: value for key, value in parent["params"].items() if key != "episode_count"}
    params["language"] = plan["language"]
    params["series"] = {"job_id": series_job_id, "revision": draft["revision"], "episode": number}
    result = workspace.submit(
        "podcast", params, f"series:{series_job_id}:r{draft['revision']}:episode:{number}"
    )
    if start_worker:
        from .worker import ensure_worker

        ensure_worker(workspace)
    return result


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


def search(workspace, query, *, source_ids=None, limit=8):
    from .sources import search_units

    if type(limit) is not int or not 1 <= limit <= 50:
        raise ValueError("Search limit must be 1–50")
    names = {s["id"]: s["name"] for s in workspace.sources()}
    if source_ids is not None and not set(source_ids) <= names.keys():
        raise ValueError("Select existing sources for search")
    return [
        {**u, "source": names[u["source_id"]]}
        for u in search_units(workspace.units(source_ids), query, limit)
    ]


def answer_evidence(workspace, job_id, revision=None):
    """Resolve the saved answer's quotes and provenance for both frontends."""
    job = workspace.job(job_id)
    if job["kind"] != "ask":
        raise ValueError("Choose a question job")
    draft = workspace.draft(job_id, revision)
    if draft is None:
        return []
    names = {s["id"]: s["name"] for s in workspace.sources()}
    units = {u["id"]: u for u in workspace.units(job["params"]["source_ids"])}
    result = []
    for key in draft["data"]["citations"]:
        unit = units[key]
        result.append(
            {
                "citation": key,
                "source_id": unit["source_id"],
                "source": names[unit["source_id"]],
                "locator": unit["locator"],
                "text": unit["text"],
                "quotes": [
                    q["text"] for q in draft["data"].get("quotes", []) if q["citation"] == key
                ],
            }
        )
    return result


def coverage(workspace: Workspace, job_id: str) -> dict | None:
    """Reading progress and citations from the current saved draft, including edits."""
    job = workspace.job(job_id)
    if job["kind"] in ("render_slides", "render_podcast"):
        job_id = job["params"]["draft_job_id"]
        draft = workspace.draft(job_id, job["params"]["revision"])
    else:
        draft = workspace.draft(job_id)
    path = workspace.path / "jobs" / job_id / "coverage.json"
    if not path.exists():
        return None
    report = json.loads(path.read_text())
    if "units" not in report:
        source_job = workspace.job(job_id)
        report["units"] = [
            {
                "id": unit["id"],
                "source_id": unit["source_id"],
                "locator": unit["locator"],
                "status": "read"
                if unit["id"] in report["read"]
                else "excluded"
                if unit["status"] != "ready"
                else "pending",
                "reason": "" if unit["status"] == "ready" else unit["status"],
            }
            for unit in workspace.units(source_job["params"]["source_ids"])
        ]
    cited = set()

    def visit(node):
        if isinstance(node, dict):
            cited.update(node.get("citations", []))
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    if draft:
        visit(draft["data"])
    names = {source["id"]: source["name"] for source in workspace.sources()}
    for unit in report.get("units", []):
        unit["source"] = names.get(unit["source_id"], unit["source_id"])
        unit["cited"] = unit["id"] in cited
    report["cited_count"] = len(cited)
    report["draft_revision"] = draft["revision"] if draft else None
    return report
