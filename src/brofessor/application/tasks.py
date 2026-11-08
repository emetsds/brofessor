"""User tasks group existing jobs; their future model choices remain project data."""

import re
import sqlite3
import time
from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path

from brofessor.contracts.jobs import (
    ACTIVE_JOB_STATUSES,
    ALL_TASK_KINDS_FILTER,
    PODCAST_JOB_KINDS,
    PRIMARY_JOB_KINDS,
    TRANSLATION_JOB_KINDS,
    InitialAudioState,
    JobKind,
    JobRecord,
    JobStatus,
    TaskStatus,
    TaskSummary,
)
from brofessor.contracts.text import DEFAULT_OLLAMA_ADDRESS, TEXT_PROVIDERS, TextProvider
from brofessor.infrastructure.storage import preferences
from brofessor.infrastructure.storage.workspace import DATABASE_FILENAME, Workspace
from brofessor.infrastructure.text.runners import normalize_ollama_address, validate_ollama_model

RECENT_LIMIT = 30


class ModelOrigin(StrEnum):
    APPLICATION = "application"
    PARENT = "parent"
    CUSTOM = "custom"


def root_job(job: JobRecord, by_id: Mapping[str, JobRecord]) -> str:
    seen = set()
    while job["id"] not in seen:
        seen.add(job["id"])
        params = job["params"]
        parent = params.get("draft_job_id")
        if params.get("series"):
            parent = params["series"]["job_id"]
        if params.get("conversation"):
            parent = params["conversation"][-1]["job_id"]
        if params.get("regeneration"):
            parent = params["regeneration"]["job_id"]
        if not parent or parent not in by_id:
            return job["id"]
        job = by_id[parent]
    return job["id"]


def _task(workspace: Workspace, job_id: str) -> JobRecord:
    """A series episode/follow-up has its own settings; a regenerated run shares them."""
    job = workspace.job(job_id)
    seen = set()
    while job["id"] not in seen:
        seen.add(job["id"])
        parent = job["params"].get("draft_job_id")
        if job["params"].get("regeneration"):
            parent = job["params"]["regeneration"]["job_id"]
        if not parent:
            break
        job = workspace.job(parent)
    if job["kind"] not in PRIMARY_JOB_KINDS:
        raise ValueError("Choose a content task")
    return job


def initial_title(kind, focus, value):
    if value is None:
        return None  # Existing clients keep their historical result-derived names.
    if not isinstance(value, str):
        raise ValueError("Task title must contain 1–160 printable characters")
    value = value.strip()
    if not value:
        words = re.findall(r"\S+", focus)
        value = " ".join(words[:7])[:80].rstrip()
        if not value:
            labels = {
                JobKind.PODCAST: "Подкаст",
                JobKind.PODCAST_SERIES: "Серия подкастов",
                JobKind.SLIDES: "Презентация",
                JobKind.ASK: "Вопрос по источникам",
                JobKind.REPORT: "Отчёт",
                JobKind.STUDY: "Проверка понимания",
                JobKind.AUDIOBOOK: "Аудиокнига",
                JobKind.TRANSLATE_EPUB: "Перевод книги",
                JobKind.TRANSLATE_PDF: "Перевод книги",
            }
            value = labels[kind]
    return validate_title(value)


def validate_title(value):
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value.strip()) > 160
        or any(ord(c) < 32 for c in value)
    ):
        raise ValueError("Task title must contain 1–160 printable characters")
    return value.strip()


def rename(workspace, job_id, value):
    task = _task(workspace, job_id)
    value = validate_title(value)
    with workspace.connect() as db:
        workspace._require_visible_task(db, task)
        db.execute(
            "INSERT INTO task_names VALUES (?,?) ON CONFLICT(task_id) DO UPDATE SET title=excluded.title",
            (task["id"], value),
        )
    return {"task_id": task["id"], "title": value}


def title(workspace: Workspace, job: JobRecord) -> str:
    task = (
        _task(workspace, job["id"])
        if job["kind"] in PRIMARY_JOB_KINDS or job["params"].get("draft_job_id")
        else job
    )
    with workspace.connect() as db:
        row = db.execute("SELECT title FROM task_names WHERE task_id=?", (task["id"],)).fetchone()
    if row:
        return row[0]
    if task["params"].get("task_title"):
        return task["params"]["task_title"]
    draft = workspace.draft(task["id"])
    return (draft["data"].get("title") if draft else None) or task["params"].get("focus") or ""


def deleted_roots(workspace):
    with workspace.connect() as db:
        return {row[0] for row in db.execute("SELECT root_id FROM deleted_tasks")}


def visible_jobs(workspace: Workspace) -> list[JobRecord]:
    jobs = workspace.jobs()
    deleted = deleted_roots(workspace)
    by_id = {job["id"]: job for job in jobs}
    return [job for job in jobs if root_job(job, by_id) not in deleted]


def delete(workspace, job_id):
    """Hide one complete task tree, preserving all revisions, sources and files."""
    with workspace.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        by_id = {row["id"]: workspace._job(row) for row in db.execute("SELECT * FROM jobs")}
        if job_id not in by_id:
            raise ValueError("Unknown task")
        root_id = root_job(by_id[job_id], by_id)
        if by_id[root_id]["kind"] not in PRIMARY_JOB_KINDS:
            raise ValueError("Choose a content task")
        if any(
            job["status"] in ACTIVE_JOB_STATUSES and root_job(job, by_id) == root_id
            for job in by_id.values()
        ):
            raise ValueError("Cancel active operations in this task before deleting it")
        db.execute("INSERT OR IGNORE INTO deleted_tasks VALUES (?,?)", (root_id, time.time()))
    return {"root_id": root_id, "deleted": True}


def restore(workspace, job_id):
    by_id = {job["id"]: job for job in workspace.jobs()}
    if job_id not in by_id:
        raise ValueError("Unknown task")
    root_id = root_job(by_id[job_id], by_id)
    with workspace.connect() as db:
        db.execute("DELETE FROM deleted_tasks WHERE root_id=?", (root_id,))
    return {"root_id": root_id, "deleted": False}


def matches_prefix(query, *texts):
    """Case-insensitive word prefixes in titles and the original task brief."""
    terms = re.findall(r"\w+", query.casefold())
    words = re.findall(r"\w+", " ".join(texts).casefold())
    return all(any(word.startswith(term) for word in words) for term in terms)


def list_tasks(
    workspace: Workspace, *, deleted=False, query="", kind=ALL_TASK_KINDS_FILTER
) -> list[TaskSummary]:
    if kind != ALL_TASK_KINDS_FILTER and kind not in PRIMARY_JOB_KINDS:
        raise ValueError("Choose a supported task type")
    jobs = workspace.jobs()
    by_id = {job["id"]: job for job in jobs}
    removed = deleted_roots(workspace)
    groups: dict[str, list[JobRecord]] = {}
    for job in jobs:
        if job["kind"] in PRIMARY_JOB_KINDS | {
            JobKind.RENDER_PODCAST,
            JobKind.RENDER_SLIDES,
            JobKind.RENDER_EPUB,
            JobKind.RENDER_PDF,
            JobKind.CHECK_PODCAST,
            JobKind.REVIEW_STUDY,
            JobKind.RENDER_AUDIOBOOK,
        }:
            groups.setdefault(root_job(job, by_id), []).append(job)
    # Read only titles, not hundreds of full saved scripts, for sidebar summaries.
    with workspace.connect() as db:
        titles = dict(
            db.execute(
                "SELECT d.job_id,json_extract(d.data,'$.title') FROM drafts d JOIN "
                "(SELECT job_id,MAX(revision) revision FROM drafts GROUP BY job_id) latest "
                "ON d.job_id=latest.job_id AND d.revision=latest.revision"
            ).fetchall()
        )
    with workspace.connect() as db:
        names = dict(db.execute("SELECT task_id,title FROM task_names"))

    def name(job):
        task = _task(workspace, job["id"])
        return (
            names.get(task["id"])
            or task["params"].get("task_title")
            or titles.get(job["id"])
            or job["params"].get("focus")
            or ""
        )

    with workspace.connect() as db:
        audio_states = {
            r["job_id"]: dict(r)
            for r in db.execute("SELECT job_id,state,render_id FROM initial_audio")
        }
    rows: list[TaskSummary] = []
    for root_id, group in groups.items():
        if (root_id in removed) != deleted:
            continue
        root = by_id[root_id]
        if root["kind"] not in PRIMARY_JOB_KINDS:
            continue
        children = [job for job in group if job["kind"] in PRIMARY_JOB_KINDS]
        matching = [
            job
            for job in children
            if (kind == ALL_TASK_KINDS_FILTER or job["kind"] == kind)
            and matches_prefix(query, name(job), job["params"].get("focus") or "")
        ]
        if not matching:
            continue
        match = root if root in matching else matching[0]
        latest = next((job for job in group if job["status"] in ACTIVE_JOB_STATUSES), group[0])
        status = latest["status"]
        continuation = audio_states.get(latest["id"])
        if continuation and status == JobStatus.SUCCEEDED and not continuation["render_id"]:
            status = {
                InitialAudioState.BLOCKED: TaskStatus.BLOCKED,
                InitialAudioState.PENDING: JobStatus.QUEUED,
                InitialAudioState.CANCELLED: JobStatus.CANCELLED,
            }.get(continuation["state"], status)
        rows.append(
            {
                "root_id": root_id,
                "child_id": children[0]["id"],
                "match_id": match["id"],
                "match_title": name(match),
                "title": name(root),
                "kind": root["kind"],
                "status": status,
                "workspace_path": str(workspace.path),
                "created": root["created"],
            }
        )
    return sorted(rows, key=lambda row: row["created"], reverse=True)


def record_open(workspace, job_id):
    """Optional navigation persistence must never undo a successfully saved job."""
    try:
        child = workspace.job(job_id)
        if child["kind"] not in PRIMARY_JOB_KINDS:
            if child["params"].get("draft_job_id"):
                child = workspace.job(child["params"]["draft_job_id"])
            else:
                return None
        by_id = {job["id"]: job for job in workspace.jobs()}
        root_id = root_job(child, by_id)
        if root_id in deleted_roots(workspace):
            return None
        row = {"workspace_path": str(workspace.path), "root_id": root_id, "child_id": child["id"]}
        with preferences.edit() as values:
            previous = values.get("recent_tasks", [])
            previous = previous if isinstance(previous, list) else []
            values["recent_tasks"] = [
                row,
                *(
                    item
                    for item in previous
                    if isinstance(item, dict)
                    and (item.get("workspace_path"), item.get("root_id"))
                    != (row["workspace_path"], root_id)
                ),
            ][:RECENT_LIMIT]
        return None
    except (OSError, ValueError, sqlite3.Error) as error:
        return f"Could not remember the task in recent tasks: {error}"


def recent_tasks(limit=20):
    values = preferences.read()
    entries = values.get("recent_tasks", [])
    if not isinstance(entries, list):
        return []
    projects = values.get("projects", [])
    removed_projects = {
        p.get("path") for p in values.get("deleted_projects", []) if isinstance(p, dict)
    }
    names = (
        {item.get("path"): item.get("name") for item in projects if isinstance(item, dict)}
        if isinstance(projects, list)
        else {}
    )
    resolved, result = {}, []
    for entry in entries[:RECENT_LIMIT]:
        if not isinstance(entry, dict) or not all(
            isinstance(entry.get(k), str) for k in ("workspace_path", "root_id", "child_id")
        ):
            continue
        path = Path(entry["workspace_path"]).expanduser().resolve()
        if str(path) in removed_projects:
            continue
        label = names.get(str(path)) or path.name
        row = {**entry, "project": label, "title": "", "kind": "", "status": "", "available": False}
        try:
            if str(path) not in resolved:
                database = path / DATABASE_FILENAME
                if not database.is_file():
                    raise ValueError("Project folder is unavailable")
                with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as db:
                    tables = {
                        item[0]
                        for item in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
                    }
                    if not {"jobs", "drafts", "artifacts", "sources", "units"} <= tables:
                        raise ValueError("Invalid project")
                workspace = Workspace(path)
                resolved[str(path)] = (
                    workspace,
                    {j["id"]: j for j in workspace.jobs()},
                    {r["root_id"]: r for r in list_tasks(workspace)},
                )
            workspace, jobs, summaries = resolved[str(path)]
            if entry["root_id"] in deleted_roots(workspace):
                continue
            summary = summaries[entry["root_id"]]
            child = jobs.get(entry["child_id"])
            child_id = (
                entry["child_id"]
                if child
                and child["kind"] in PRIMARY_JOB_KINDS
                and root_job(child, jobs) == entry["root_id"]
                else entry["root_id"]
            )
            row.update(summary, child_id=child_id, project=label, available=True)
        except (OSError, ValueError, KeyError, sqlite3.Error):
            pass
        result.append(row)
        if len(result) >= max(1, min(limit, RECENT_LIMIT)):
            break
    return result


def validate_models(kind, data):
    if kind == JobKind.AUDIOBOOK:
        from brofessor.infrastructure.speech.catalogue import get, selected

        if set(data) - {"speech_model", "origin"}:
            raise ValueError("An audiobook uses only a local speech model")
        speech = data.get("speech_model", selected())
        get(speech)
        origin = data.get("origin", ModelOrigin.CUSTOM)
        if origin not in (
            ModelOrigin.APPLICATION,
            ModelOrigin.PARENT,
            ModelOrigin.CUSTOM,
        ):
            raise ValueError("Invalid task model origin")
        return {"speech_model": speech, "origin": origin}
    allowed = {"provider", "model", "ollama_address", "origin"}
    if kind in PODCAST_JOB_KINDS:
        allowed.add("speech_model")
    if set(data) - allowed:
        raise ValueError("These model settings do not apply to this task")
    provider = data.get("provider")
    model = data.get("model")
    if provider not in TEXT_PROVIDERS:
        raise ValueError("Choose codex, claude or ollama")
    if model is not None and not isinstance(model, str):
        raise ValueError("Model must be a name or empty")
    model = model.strip() or None if model is not None else None
    result = {
        "provider": provider,
        "model": model,
        "origin": data.get("origin", ModelOrigin.CUSTOM),
    }
    if result["origin"] not in (
        ModelOrigin.APPLICATION,
        ModelOrigin.PARENT,
        ModelOrigin.CUSTOM,
    ):
        raise ValueError("Invalid task model origin")
    if provider == TextProvider.OLLAMA:
        try:
            validate_ollama_model(model)
        except RuntimeError as error:
            raise ValueError(str(error)) from error
        result["ollama_address"] = normalize_ollama_address(
            data.get("ollama_address", DEFAULT_OLLAMA_ADDRESS)
        )
    elif data.get("ollama_address") is not None:
        raise ValueError("Only Ollama uses a server address")
    if kind in PODCAST_JOB_KINDS:
        from brofessor.infrastructure.speech.catalogue import get, selected

        speech = data.get("speech_model", selected())
        get(speech)
        result["speech_model"] = speech
    return result


def initial_models(kind, params, *, speech_model=None, origin=None):
    data = {key: params[key] for key in ("provider", "model", "ollama_address") if key in params}
    if kind == JobKind.AUDIOBOOK:
        from brofessor.infrastructure.speech.catalogue import selected

        data = {"speech_model": speech_model or selected()}
    if params.get("provider") == TextProvider.OLLAMA:
        from brofessor.infrastructure.text.runners import ollama_address_for_job

        data["ollama_address"] = ollama_address_for_job(params)
    if kind in PODCAST_JOB_KINDS and speech_model is not None:
        data["speech_model"] = speech_model
    result = validate_models(kind, data)
    defaults = preferences.settings(for_edit=True)
    result["origin"] = origin or (
        ModelOrigin.APPLICATION
        if all(result.get(k) == defaults.get(k) for k in result if k != "origin")
        else ModelOrigin.CUSTOM
    )
    return result


def models(workspace, job_id):
    task = _task(workspace, job_id)
    saved = workspace.task_models(task["id"])
    if saved is not None:
        return saved
    raise ValueError("Task model settings are missing; create a new task")


def save_models(workspace, job_id, data, expected_revision):
    task = _task(workspace, job_id)
    value = validate_models(task["kind"], {**data, "origin": ModelOrigin.CUSTOM})
    return workspace.save_task_models(task["id"], value, expected_revision)


def apply_defaults(workspace, job_id, expected_revision):
    task = _task(workspace, job_id)
    defaults = preferences.settings()
    if task["kind"] == JobKind.AUDIOBOOK:
        return workspace.save_task_models(
            task["id"],
            {"speech_model": defaults["speech_model"], "origin": ModelOrigin.APPLICATION},
            expected_revision,
        )
    data = {
        key: value
        for key, value in defaults.items()
        if key != "language" and (key != "speech_model" or task["kind"] in PODCAST_JOB_KINDS)
    }
    data["origin"] = ModelOrigin.APPLICATION
    value = validate_models(task["kind"], data)
    return workspace.save_task_models(task["id"], value, expected_revision)


def regenerate(workspace, job_id, *, revision=None, request_key=None, start_worker=True):
    from brofessor.application import service

    job = workspace.job(job_id)
    if job["kind"] == JobKind.AUDIOBOOK:
        raise ValueError("Use draft render to regenerate audiobook audio from its saved text")
    if job["kind"] not in PRIMARY_JOB_KINDS:
        raise ValueError("Choose a content task")
    draft = workspace.draft(job_id, revision)
    if draft is None:
        raise ValueError("Choose a saved content revision")
    choices = models(workspace, job_id)["data"]
    params = {
        key: value
        for key, value in job["params"].items()
        if key not in ("provider", "model", "ollama_address", "regeneration")
    }
    params = service._with_models(params, choices)
    if job["kind"] in TRANSLATION_JOB_KINDS:
        params.pop("terminology_update", None)
        params["translation_version"] = 4
        params["reuse_glossary"] = True
        params["glossary_seed"] = [
            {key: term[key] for key in ("term", "sense", "translation")}
            for term in draft["data"]["terms"]
        ]
    params["regeneration"] = {"job_id": job_id, "revision": draft["revision"]}
    if params.get("auto_audio"):
        from brofessor.infrastructure.speech import catalogue as speech_models

        params["auto_audio"] = speech_models.get(choices["speech_model"])
    previous = workspace.job_by_request_key(request_key) if request_key else None
    ignore = {"provider", "model", "ollama_address"}
    if (
        previous
        and previous["kind"] == job["kind"]
        and {
            k: v
            for k, v in service._draft_params(job["kind"], previous["params"]).items()
            if k not in ignore
        }
        == {k: v for k, v in service._draft_params(job["kind"], params).items() if k not in ignore}
    ):
        result = service._remember_task(workspace, previous)
    else:
        result = service._submit_draft(
            workspace, job["kind"], params, request_key, model_choices=choices
        )
    if start_worker:
        from brofessor.application.worker import ensure_worker

        ensure_worker(workspace)
    return result


def search_projects(catalog, query):
    """Read grouped matches without opening tasks or changing navigation history."""
    if not query.strip():
        return []
    groups = []
    for project in catalog:
        matches = []
        if project["available"]:
            try:
                matches = list_tasks(Workspace(project["path"]), query=query)
            except (ValueError, OSError, sqlite3.Error):
                pass
        if matches or matches_prefix(query, project["name"]):
            groups.append({"project": project, "tasks": matches})
    return groups
