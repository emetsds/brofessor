"""Explicit model and cache maintenance through the existing services and worker."""

import asyncio
import platform
import shutil
import sqlite3
import time
from contextlib import ExitStack, closing, contextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import httpx

from brofessor.application import projects
from brofessor.contracts.jobs import (
    ACTIVE_JOB_STATUSES,
    RESUMABLE_JOB_STATUSES,
    JobKind,
    JobStatus,
    StageId,
)
from brofessor.contracts.text import TextProvider
from brofessor.infrastructure.speech import catalogue as speech_models
from brofessor.infrastructure.speech.contracts import (
    QWEN_SPEECH_LOCK_FILENAME,
    SpeechEngine,
)
from brofessor.infrastructure.storage import preferences
from brofessor.infrastructure.storage.locks import (
    ResourceBusy,
    _lock,
    audio_cache_lock,
    models_lock,
)
from brofessor.infrastructure.storage.workspace import (
    AUDIO_SEGMENTS_DIRECTORY,
    DATABASE_FILENAME,
    Workspace,
)
from brofessor.infrastructure.text import runners as executors


def workspace():
    return Workspace(preferences.data_directory() / "maintenance")


def jobs():
    """Read maintenance and historical project downloads without opening/migrating projects."""
    paths = {(preferences.data_directory() / "maintenance").resolve()}
    try:
        paths.update(
            Path(p["path"]).expanduser().resolve()
            for p in projects.list_projects()
            if p["available"]
        )
    except (OSError, ValueError):
        pass
    found = []
    for folder in paths:
        database = folder / DATABASE_FILENAME
        if not database.is_file():
            continue
        try:
            with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as connection:
                connection.row_factory = sqlite3.Row
                rows = connection.execute(
                    "SELECT * FROM jobs WHERE kind IN (?,?)",
                    (JobKind.DOWNLOAD_MODEL, JobKind.DOWNLOAD_OLLAMA_MODEL),
                ).fetchall()
                found.extend({**Workspace._job(row), "workspace_path": str(folder)} for row in rows)
        except (OSError, sqlite3.Error, ValueError):
            continue  # An unavailable old project does not hide current service work.
    workers = {}
    for job in found:
        folder = job["workspace_path"]
        if folder not in workers:
            workers[folder] = _worker_running(folder)
        job["worker_running"] = workers[folder]
        if job["status"] == JobStatus.RUNNING and not workers[folder]:
            job["status"] = JobStatus.INTERRUPTED
    return sorted(found, key=lambda item: item["created"], reverse=True)


def _worker_running(folder):
    from brofessor.application.worker import worker_lock

    try:
        with worker_lock(SimpleNamespace(path=Path(folder))) as lock:
            return lock is None
    except FileNotFoundError:
        return False


def _job_target(job_id, workspace_path=None):
    expected = Path(workspace_path).expanduser().resolve() if workspace_path is not None else None
    matches = [
        job
        for job in jobs()
        if job["id"] == job_id
        and (expected is None or Path(job["workspace_path"]).resolve() == expected)
    ]
    if len(matches) != 1:
        raise ValueError("Choose a unique model job from models jobs")
    return Workspace(matches[0]["workspace_path"])


def _resume(target, job_id):
    from brofessor.application.worker import worker_lock

    with worker_lock(target) as lock:
        if lock is not None:
            target.recover()
        job = target.job(job_id)
        if job["status"] in RESUMABLE_JOB_STATUSES:
            job = target.resume(job_id)
        elif job["status"] not in ACTIVE_JOB_STATUSES:
            raise ValueError("Only unfinished model downloads can be resumed")
    return job


def _submission_lock():
    return _lock(
        preferences.data_directory() / "locks" / "model-download-jobs.lock",
        exclusive=True,
        wait=True,
        check=None,
        description="Model downloads",
    )


def resume(job_id, *, workspace_path=None, start_worker=True):
    """Recover a dead worker if needed and continue the same pinned download."""
    with _submission_lock():
        target = _job_target(job_id, workspace_path)
        job = _resume(target, job_id)
    if start_worker:
        from brofessor.application.worker import ensure_worker

        ensure_worker(target)
    return {**job, "workspace_path": str(target.path)}


def cancel(job_id, *, workspace_path=None):
    target = _job_target(job_id, workspace_path)
    return {**target.cancel(job_id), "workspace_path": str(target.path)}


def _download(kind, params, *, start_worker):
    with _submission_lock():
        matches = [job for job in jobs() if job["kind"] == kind and job["params"] == params]
        # An older live request takes precedence over a newer failed attempt.
        previous = next((j for j in matches if j["status"] in ACTIVE_JOB_STATUSES), None)
        previous = previous or next(iter(matches), None)
        if previous and previous["status"] != JobStatus.SUCCEEDED:
            target = Workspace(previous["workspace_path"])
            job = _resume(target, previous["id"])
        else:
            target = workspace()
            job = target.submit(kind, params, reuse_active=True)
    if start_worker:
        from brofessor.application.worker import ensure_worker

        ensure_worker(target)
    return {**job, "workspace_path": str(target.path)}


def latest_jobs(downloads=None):
    """One current attempt per pinned speech model or Ollama server/model."""
    latest = {}
    for job in jobs() if downloads is None else downloads:
        params = job["params"]
        spec = params.get("model_spec")
        model = speech_models.reference(spec) if spec else params.get("model")
        key = (job["kind"], model, params.get("ollama_address"))
        previous = latest.get(key)
        priority = (job["status"] in ACTIVE_JOB_STATUSES, job["created"])
        if previous is None or priority > (
            previous["status"] in ACTIVE_JOB_STATUSES,
            previous["created"],
        ):
            latest[key] = job
    return sorted(latest.values(), key=lambda job: job["created"], reverse=True)


def download_speech(model, *, start_worker=True):
    item = speech_models.get(model)
    return _download(
        JobKind.DOWNLOAD_MODEL, {"model": item["id"], "model_spec": item}, start_worker=start_worker
    )


def _owned(path, root):
    root = root.resolve()
    if path.is_symlink() or not path.resolve().is_relative_to(root) or path.resolve() == root:
        raise ValueError("Refusing a cache path outside the managed application storage")
    return path


def _speech_target(model):
    if not isinstance(model, str):
        raise ValueError("Choose a catalog model or its saved pinned reference")
    item = speech_models.get(model)
    root = speech_models.cache_directory().parent
    return item, _owned(speech_models.snapshot(item), root)


def _files(path):
    if not path.exists():
        return []
    return [p for p in path.rglob("*") if p.is_symlink() or p.is_file()]


def _usage(path, *, logical=False):
    count, size = 0, 0
    for file in _files(path):
        try:
            stat = file.stat() if logical else file.lstat()
        except FileNotFoundError:
            continue
        size += stat.st_size
        count += 1
    return {"bytes": size, "files": count}


def _partial_files(item, target):
    folder = target.parent.parent
    return [
        file
        for file in _files(folder)
        if file.name.endswith((".incomplete", ".part", ".importing", ".localizing"))
        and not file.is_dir()
    ]


def _resource_folders(item):
    target = _owned(speech_models.snapshot(item), speech_models.cache_directory().parent)
    found = {target.parent.parent}
    for dependency in item.get("dependencies", []):
        found.update(_resource_folders(dependency))
    return found


def _live_job(job):
    if job["status"] == JobStatus.QUEUED:
        return True
    if job["status"] != JobStatus.RUNNING:
        return False
    # A dead old worker can leave a stale running row. New workers take the
    # shared resource guard before touching any cache, after recovering rows.
    return _worker_running(job["workspace_path"])


def _pending_speech(item):
    target = speech_models.snapshot(item)
    requested = {target.parent.parent}
    for job in jobs():
        if job["kind"] != JobKind.DOWNLOAD_MODEL or job["status"] not in ACTIVE_JOB_STATUSES:
            continue
        try:
            saved = job["params"].get("model_spec")
            saved = saved if isinstance(saved, dict) else speech_models.get(job["params"]["model"])
            overlap = requested & _resource_folders(saved)
        except (KeyError, TypeError, ValueError):
            continue  # An unrelated unknown historical ID must not block every model.
        if overlap and _live_job(job):
            raise ResourceBusy(
                f"Model files belong to an unfinished download ({job['id']}); cancel or finish it first"
            )


@contextmanager
def _native_model_locks(item, target):
    paths = sorted(
        (speech_models.cache_directory() / ".locks" / target.parent.parent.name).glob("*.lock")
    )
    with ExitStack() as stack:
        if item.get("engine") == SpeechEngine.QWEN_BASE:
            stack.enter_context(
                _lock(
                    preferences.data_directory() / QWEN_SPEECH_LOCK_FILENAME,
                    exclusive=True,
                    wait=False,
                    check=None,
                    description="Qwen speech synthesis",
                )
            )
        for path in paths:
            _owned(path, speech_models.cache_directory().parent)
            stack.enter_context(
                _lock(path, exclusive=True, wait=False, check=None, description="Model download")
            )
        yield


def speech_inventory(model=None):
    rows = []
    apple = platform.system() == "Darwin" and platform.machine() == "arm64"
    with models_lock():
        for item in [speech_models.get(model)] if model is not None else speech_models.CATALOG:
            target = _owned(speech_models.snapshot(item), speech_models.cache_directory().parent)
            partial = _partial_files(item, target)
            rows.append(
                {
                    "id": item["id"],
                    "reference": speech_models.reference(item),
                    "name": item["name"],
                    "selectable": True,
                    "installed": speech_models.installed_path(item) is not None,
                    "compatible": apple,
                    "download_bytes": speech_models.total_bytes(item),
                    "path": str(target),
                    "stored_bytes": _usage(target, logical=True)["bytes"],
                    "partial_bytes": sum(p.lstat().st_size for p in partial),
                    "partial_files": len(partial),
                    "dependencies": [
                        {
                            "id": dep["id"],
                            "path": str(speech_models.snapshot(dep)),
                            "stored_bytes": _usage(speech_models.snapshot(dep), logical=True)[
                                "bytes"
                            ],
                        }
                        for dep in item.get("dependencies", [])
                    ],
                }
            )
    return rows


def remove_speech(model):
    """Remove exactly one pinned revision; shared dependencies and saved specs remain."""
    with models_lock(exclusive=True, wait=False):
        item, target = _speech_target(model)
        if any(
            speech_models.snapshot(dependency) == target
            for entry in speech_models.CATALOG
            for dependency in entry.get("dependencies", [])
        ):
            raise ValueError(
                "This component is shared by speech profiles; remove model weights instead"
            )
        _pending_speech(item)
        with _native_model_locks(item, target):
            return _remove_speech(item, target)


def _remove_speech(item, target):
    before = _usage(target, logical=True)
    result = {"path": str(target), "removed_bytes": 0, "removed_files": 0}
    if not target.exists():
        return result
    from huggingface_hub import scan_cache_dir

    hub = speech_models.cache_directory()
    info = scan_cache_dir(hub)
    repo = next((r for r in info.repos if r.repo_path == target.parent.parent), None)
    revision = (
        next((r for r in repo.revisions if r.snapshot_path == target), None) if repo else None
    )
    if revision is None:
        # An incomplete/corrupt snapshot cannot justify deleting any shared blob.
        shutil.rmtree(target)
        result["warning"] = "Only the incomplete snapshot was removed; shared blobs remain"
    else:
        strategy = replace(info, repos=frozenset({repo})).delete_revisions(item["revision"])
        if strategy.repos:
            # HF's whole-repo shortcut would also discard unrelated partial downloads.
            # Keep the repo and remove only this snapshot and its unshared blob entries.
            strategy = replace(
                strategy,
                repos=frozenset(),
                snapshots=frozenset({target}),
                refs=frozenset(repo.repo_path / "refs" / ref for ref in revision.refs),
                blobs=frozenset(
                    f.blob_path for f in revision.files if not f.blob_path.is_relative_to(target)
                ),
            )
        for path in [*strategy.blobs, *strategy.refs, *strategy.snapshots]:
            if not path.resolve().is_relative_to(hub.resolve()):
                raise ValueError("A cached model points outside managed model storage")
        strategy.execute()
        result["estimated_freed_bytes"] = strategy.expected_freed_size
    result.update(removed_bytes=before["bytes"], removed_files=before["files"])
    return result


def clear_partial(model):
    with models_lock(exclusive=True, wait=False):
        item, target = _speech_target(model)
        _pending_speech(item)
        with _native_model_locks(item, target):
            paths = _partial_files(item, target)
            size = sum(path.lstat().st_size for path in paths)
            for path in paths:
                path.unlink()
            return {"path": str(target), "removed_bytes": size, "removed_files": len(paths)}


def _audio_path(project):
    root = Path(getattr(project, "path", project)).expanduser().resolve()
    return _owned(root / AUDIO_SEGMENTS_DIRECTORY, root)


def audio_cache_info(project):
    target = _audio_path(project)
    return {"path": str(target), **_usage(target)}


def _pending_audio(project):
    folder = Path(getattr(project, "path", project)).expanduser().resolve()
    database = folder / DATABASE_FILENAME
    if not database.is_file():
        return
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as connection:
        row = connection.execute(
            "SELECT id FROM jobs WHERE status=? AND kind IN (?,?) LIMIT 1",
            (JobStatus.RUNNING, JobKind.RENDER_PODCAST, JobKind.PREVIEW_TURN),
        ).fetchone()
    # An already-running pre-update worker does not hold the new audio guard.
    # Check this workspace directly, including projects absent from the registry.
    if row and _live_job({"status": JobStatus.RUNNING, "workspace_path": str(folder)}):
        raise ResourceBusy(
            f"Project audio belongs to a running render ({row[0]}); wait for it to finish"
        )


def clear_audio_cache(project):
    with audio_cache_lock(project, exclusive=True, wait=False):
        target = _audio_path(project)
        _pending_audio(project)
        before = _usage(target)
        if target.exists():
            shutil.rmtree(target)
        return {
            "path": str(target),
            "removed_bytes": before["bytes"],
            "removed_files": before["files"],
        }


async def _verify_ollama(client):
    status = await executors._get_object(client, "GET", "/api/status")
    cloud = status.get("cloud")
    if not isinstance(cloud, dict) or cloud.get("disabled") is not True:
        raise RuntimeError("Ollama cloud features must be disabled on the selected server")


def _client(address):
    return httpx.AsyncClient(
        base_url=executors.ollama_url(executors.normalize_ollama_address(address)),
        timeout=30,
        trust_env=False,
        follow_redirects=False,
    )


async def _ollama_models(address):
    async with _client(address) as client:
        await _verify_ollama(client)
        value = await executors._get_object(client, "GET", "/api/tags")
        if not isinstance(value.get("models"), list):
            raise RuntimeError("Ollama returned invalid model metadata")
        found = []
        for item in value["models"]:
            if not isinstance(item, dict) or executors._remote(item):
                continue
            name = item.get("name", item.get("model"))
            if not isinstance(name, str):
                continue
            try:
                executors.validate_ollama_model(name)
            except RuntimeError:
                continue
            if type(item.get("size")) is int and item["size"] > 0:
                found.append({**item, "name": name})
        return found


def ollama_models(address):
    return _ollama_result(_ollama_models(address))


def _ollama_result(operation):
    try:
        return asyncio.run(operation)
    except httpx.HTTPError as error:
        raise RuntimeError(f"Could not reach the selected Ollama server: {error}") from error


def download_ollama(address, model, *, start_worker=True):
    executors.validate_ollama_model(model)
    address = executors.normalize_ollama_address(address)
    return _download(
        JobKind.DOWNLOAD_OLLAMA_MODEL,
        {"provider": TextProvider.OLLAMA, "model": model, "ollama_address": address},
        start_worker=start_worker,
    )


async def _pull(address, model, progress):
    async with _client(address) as client:
        await _verify_ollama(client)
        layers = {}
        success = False
        async with client.stream(
            "POST", "/api/pull", json={"model": model, "stream": True}
        ) as response:
            if response.status_code != 200:
                raise RuntimeError(f"Ollama pull returned HTTP {response.status_code}")
            buffer = bytearray()

            def consume(line):
                nonlocal success
                value = executors._json_object(line.decode("utf-8"), "Ollama pull")
                if value.get("error"):
                    raise RuntimeError(f"Ollama pull failed: {str(value['error'])[:300]}")
                status = value.get("status")
                if not isinstance(status, str):
                    raise RuntimeError("Ollama pull returned invalid progress")
                success = status == "success"
                if "digest" in value and "total" in value:
                    total, completed = value["total"], value.get("completed", 0)
                    digest = str(value["digest"])[:200]
                    if (
                        type(total) is not int
                        or type(completed) is not int
                        or not 0 <= completed <= total
                        or (len(layers) >= 4096 and digest not in layers)
                    ):
                        raise RuntimeError("Ollama pull returned invalid layer sizes")
                    layers[digest] = (completed, total)
                progress(
                    {
                        "stage": StageId.DOWNLOADING_MODEL,
                        "provider": TextProvider.OLLAMA,
                        "model": model,
                        "status": status[:200],
                        "completed": sum(x[0] for x in layers.values()),
                        "total": sum(x[1] for x in layers.values()),
                    }
                )

            async for chunk in response.aiter_bytes(chunk_size=16384):
                buffer.extend(chunk)
                while b"\n" in buffer:
                    line, _, rest = buffer.partition(b"\n")
                    buffer = bytearray(rest)
                    if len(line) > 65536:
                        raise RuntimeError("Ollama pull progress line exceeded its limit")
                    if line.strip():
                        consume(line)
                if len(buffer) > 65536:
                    raise RuntimeError("Ollama pull progress line exceeded its limit")
            if buffer.strip():
                consume(buffer)
        if not success:
            raise RuntimeError("Ollama pull ended before a success result")
        profile = await executors._ollama_preflight(client, model)
        return {
            "model": profile["model"],
            "ollama_address": address,
            "digest": profile.get("digest"),
        }


def pull_ollama(params, cancelled=lambda: False, progress=lambda value: None):
    model = params["model"]
    executors.validate_ollama_model(model)
    address = executors.ollama_address_for_job(params)

    def check():
        executors._check_cancel(cancelled)

    async def bounded():
        task = asyncio.create_task(_pull(address, model, progress))
        deadline = time.monotonic() + 4 * 60 * 60
        try:
            while not task.done():
                check()
                if time.monotonic() > deadline:
                    raise RuntimeError("Ollama model download timed out; resume to continue")
                await asyncio.wait({task}, timeout=0.1)
            check()
            return await task
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    with models_lock(check=check):
        return _ollama_result(bounded())


def remove_ollama(address, model):
    executors.validate_ollama_model(model)
    address = executors.normalize_ollama_address(address)

    async def remove():
        async with _client(address) as client:
            profile = await executors._ollama_preflight(client, model)
            running = await executors._get_object(client, "GET", "/api/ps")
            if not isinstance(running.get("models"), list) or any(
                not isinstance(item, dict) for item in running["models"]
            ):
                raise RuntimeError("Cannot verify which Ollama models are loaded")
            for entry in running.get("models", []):
                if entry.get("name", entry.get("model")) == profile["model"] or (
                    profile.get("digest") and entry.get("digest") == profile["digest"]
                ):
                    raise ResourceBusy("The Ollama model is loaded; wait for it to be released")
            response = await client.request(
                "DELETE", "/api/delete", json={"model": profile["model"]}
            )
            if response.status_code not in (200, 404):
                raise RuntimeError(f"Ollama delete returned HTTP {response.status_code}")
            return {
                "model": profile["model"],
                "ollama_address": address,
                "removed": response.status_code == 200,
            }

    with models_lock(exclusive=True, wait=False):
        return _ollama_result(remove())
