import asyncio
import fcntl
import json
import os
import subprocess
import sys

import httpx
import pytest

from brofessor.application import maintenance, projects
from brofessor.contracts.jobs import JobKind, JobStatus
from brofessor.infrastructure.speech import catalogue as speech_models
from brofessor.infrastructure.storage import preferences
from brofessor.infrastructure.storage.locks import ResourceBusy, audio_cache_lock, models_lock
from brofessor.infrastructure.storage.workspace import Workspace
from brofessor.infrastructure.text.runners import CancelledError


@pytest.fixture(autouse=True)
def isolated_user(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))


@pytest.fixture
def catalog(monkeypatch):
    dependency = {
        "id": "shared-codec",
        "repo": "test/codec",
        "revision": "c" * 40,
        "files": {"codec.bin": 5},
        "download_bytes": 5,
    }
    first = {
        "id": "first",
        "name": "First",
        "repo": "test/speech",
        "revision": "a" * 40,
        "engine": "qwen3-base-mlx",
        "files": {"shared.bin": 6, "own.bin": 3},
        "download_bytes": 9,
        "dependencies": [dependency],
    }
    second = {
        **first,
        "id": "second",
        "name": "Second",
        "revision": "b" * 40,
        "legacy": True,
        "files": {"shared.bin": 6},
        "download_bytes": 6,
    }
    monkeypatch.setattr(speech_models, "CATALOG", [first, second])
    dep = speech_models.snapshot(dependency)
    dep.mkdir(parents=True)
    (dep / "codec.bin").write_bytes(b"codec")
    repo = speech_models.snapshot(first).parent.parent
    blobs = repo / "blobs"
    blobs.mkdir(parents=True)
    (blobs / "shared").write_bytes(b"shared")
    (blobs / "own").write_bytes(b"own")
    for item in [first, second]:
        target = speech_models.snapshot(item)
        target.mkdir(parents=True)
        (target / "shared.bin").symlink_to("../../blobs/shared")
    (speech_models.snapshot(first) / "own.bin").symlink_to("../../blobs/own")
    return first, second, dependency


def test_jobs_read_does_not_create_service_or_missing_projects(tmp_path, catalog):
    assert maintenance.jobs() == []
    assert not (preferences.data_directory() / "maintenance").exists()
    old = Workspace(tmp_path / "old-project")
    projects.open_project(old.path)
    historic = old.submit(JobKind.DOWNLOAD_MODEL, {"model": "first"})
    missing = tmp_path / "missing"
    with preferences.edit() as values:
        values["projects"].append({"name": "Unavailable", "path": str(missing)})
    current = maintenance.download_speech("first", start_worker=False)
    assert maintenance.download_speech("first", start_worker=False)["id"] == current["id"]
    found = maintenance.jobs()
    assert {(j["id"], j["workspace_path"]) for j in found} == {
        (historic["id"], str(old.path)),
        (current["id"], str(maintenance.workspace().path)),
    }
    assert current["params"]["model_spec"] == catalog[0]
    assert not missing.exists()
    assert len(projects.list_projects()) == 2  # The service workspace is not a user project.


def test_dead_download_is_reported_interrupted_and_resumed_in_place(catalog):
    first, _, _ = catalog
    job = maintenance.download_speech(first["id"], start_worker=False)
    target = maintenance.workspace()
    target.claim()
    target.update_job(job["id"], progress={"completed": 4, "total": 14})
    original = target.job(job["id"])["params"]
    shown = maintenance.jobs()[0]
    assert shown["status"] == "interrupted" and not shown["worker_running"]
    assert target.job(job["id"])["status"] == "running"  # Observation does not recover a worker.
    resumed = maintenance.resume(job["id"], start_worker=False)
    assert resumed["id"] == job["id"] and resumed["status"] == "queued"
    assert resumed["params"] == original and resumed["progress"]["completed"] == 4
    assert maintenance.download_speech(first["id"], start_worker=False)["id"] == job["id"]


def test_resume_resolves_symlink_aliases_of_the_maintenance_folder(catalog, tmp_path, monkeypatch):
    job = maintenance.download_speech(catalog[0]["id"], start_worker=False)
    target = maintenance.workspace()
    target.cancel(job["id"])
    alias = tmp_path / "data-alias"
    alias.symlink_to(preferences.data_directory().parent, target_is_directory=True)
    monkeypatch.setenv("XDG_DATA_HOME", str(alias))
    shown = maintenance.jobs()[0]
    assert shown["workspace_path"] == str(target.path)
    continued = maintenance.resume(
        job["id"], workspace_path=alias / "brofessor" / "maintenance", start_worker=False
    )
    assert continued["id"] == job["id"] and continued["status"] == "queued"


def test_concurrent_download_requests_and_resume_reuse_one_attempt(catalog):
    from concurrent.futures import ThreadPoolExecutor

    first, _, _ = catalog

    def request(_):
        return maintenance.download_speech(first["id"], start_worker=False)

    with ThreadPoolExecutor(max_workers=3) as pool:
        submitted = list(pool.map(request, range(3)))
    assert len({job["id"] for job in submitted}) == 1
    job = submitted[0]
    maintenance.cancel(job["id"])
    with ThreadPoolExecutor(max_workers=3) as pool:
        continued = list(pool.map(request, range(3)))
    assert {item["id"] for item in continued} == {job["id"]}
    assert len(maintenance.workspace().jobs()) == 1


def test_live_historical_download_is_reused_and_failed_retry_does_not_hide_it(tmp_path, catalog):
    from brofessor.application.worker import worker_lock

    first, _, _ = catalog
    old = Workspace(tmp_path / "old-project")
    projects.open_project(old.path)
    historic = old.submit(JobKind.DOWNLOAD_MODEL, {"model": first["id"], "model_spec": first})
    old.claim()
    retry = maintenance.workspace().submit("download_model", historic["params"])
    maintenance.workspace().update_job(retry["id"], status=JobStatus.FAILED, error="failed attempt")
    with worker_lock(old):
        assert maintenance.latest_jobs()[0]["id"] == historic["id"]
        returned = maintenance.download_speech(first["id"], start_worker=False)
        assert returned["id"] == historic["id"] and returned["workspace_path"] == str(old.path)
        assert old.job(historic["id"])["status"] == "running"


def test_completed_download_after_removal_starts_new_attempt_without_erasing_history(catalog):
    first, _, _ = catalog
    job = maintenance.download_speech(first["id"], start_worker=False)
    target = maintenance.workspace()
    target.update_job(job["id"], status=JobStatus.SUCCEEDED)
    maintenance.remove_speech(first["id"])
    new = maintenance.download_speech(first["id"], start_worker=False)
    assert new["id"] != job["id"]
    assert target.job(job["id"])["status"] == "succeeded"
    assert maintenance.latest_jobs()[0]["id"] == new["id"]


def test_remove_pinned_model_preserves_shared_blobs_dependencies_specs_and_partial(catalog):
    first, second, dependency = catalog
    repo = speech_models.snapshot(first).parent.parent
    partial = repo / "blobs" / "unfinished.incomplete"
    partial.write_bytes(b"partial")
    spec = speech_models._saved_spec(speech_models.reference(first))
    spec.parent.mkdir(parents=True)
    spec.write_text(json.dumps(first))
    legacy_copy = preferences.data_directory().parent / "legacy-hf-cache.bin"
    os.link(repo / "blobs" / "own", legacy_copy)
    inventory = {row["id"]: row for row in maintenance.speech_inventory()}
    assert inventory["first"]["installed"] and inventory["first"]["selectable"]
    assert inventory["second"]["installed"] and not inventory["second"]["selectable"]
    maintenance.remove_speech("first")
    assert not speech_models.snapshot(first).exists()
    assert (speech_models.snapshot(second) / "shared.bin").read_bytes() == b"shared"
    assert not (repo / "blobs" / "own").exists()
    assert legacy_copy.read_bytes() == b"own"
    assert (repo / "blobs" / "shared").exists()
    assert (speech_models.snapshot(dependency) / "codec.bin").read_bytes() == b"codec"
    assert json.loads(spec.read_text()) == first
    maintenance.remove_speech("second")
    assert not (repo / "blobs" / "shared").exists()
    assert partial.read_bytes() == b"partial"
    assert spec.exists()


def test_cross_repo_shared_store_survives_until_its_last_revision_is_removed(catalog, monkeypatch):
    shared = pytest.importorskip("huggingface_hub.utils._shared_blobs")
    first, second, _ = catalog
    hub = speech_models.cache_directory()
    original_blob = speech_models.snapshot(first).parent.parent / "blobs" / "shared"
    key = "f" * 64
    assert shared.publish_blob_to_shared_store(
        blob_path=str(original_blob), xet_hash=key, cache_dir=hub, expected_size=6
    )
    third = {**second, "id": "third", "repo": "test/other-repo", "revision": "d" * 40}
    monkeypatch.setattr(speech_models, "CATALOG", [first, second, third])
    target = speech_models.snapshot(third)
    target.mkdir(parents=True)
    other_blob = target.parent.parent / "blobs" / "shared"
    other_blob.parent.mkdir()
    assert shared.try_link_from_shared_store(
        blob_path=str(other_blob), xet_hash=key, cache_dir=hub, expected_size=6
    )
    (target / "shared.bin").symlink_to("../../blobs/shared")
    store = shared.shared_blob_path(hub, key)
    maintenance.remove_speech("first")
    maintenance.remove_speech("second")
    assert store.read_bytes() == b"shared"
    assert (target / "shared.bin").read_bytes() == b"shared"
    maintenance.remove_speech("third")
    assert not store.exists()


def test_stale_running_download_does_not_block_maintenance_forever(tmp_path, catalog):
    from brofessor.application.worker import worker_lock

    first, _, _ = catalog
    project = Workspace(tmp_path / "old-project")
    projects.open_project(project.path)
    job = project.submit(JobKind.DOWNLOAD_MODEL, {"model": "first", "model_spec": first})
    project.claim()
    with worker_lock(project):
        with pytest.raises(ResourceBusy):
            maintenance.clear_partial("first")
    maintenance.remove_speech("first")
    assert project.job(job["id"])["status"] == "running"  # Only a recovering worker changes it.


def test_partial_clear_preserves_finished_weights_and_dependency(catalog):
    first, second, dependency = catalog
    partial = speech_models.snapshot(first).parent.parent / "blobs" / "unfinished.incomplete"
    partial.write_bytes(b"partial")
    result = maintenance.clear_partial("first")
    assert result["removed_bytes"] == len(b"partial") and result["removed_files"] == 1
    assert speech_models.installed_path(first) is not None
    assert speech_models.installed_path(second) is not None
    assert speech_models.installed_path(dependency) is not None


def test_saved_dependency_reference_cannot_remove_a_shared_voice_or_codec_pack(catalog):
    _, _, dependency = catalog
    reference = speech_models.reference(dependency)
    spec = speech_models._saved_spec(reference)
    spec.parent.mkdir(parents=True)
    spec.write_text(json.dumps(dependency))
    with pytest.raises(ValueError, match="shared"):
        maintenance.remove_speech(reference)
    assert speech_models.installed_path(dependency) is not None


def test_historical_project_download_blocks_only_its_cache_resources(tmp_path, catalog):
    first, second, dependency = catalog
    project = Workspace(tmp_path / "old-project")
    projects.open_project(project.path)
    unrelated = project.submit(JobKind.DOWNLOAD_MODEL, {"model": "unknown-old-model"})
    queued = project.submit(JobKind.DOWNLOAD_MODEL, {"model": "first", "model_spec": first})
    with pytest.raises(ResourceBusy, match=queued["id"]):
        maintenance.remove_speech("second")
    with pytest.raises(ResourceBusy):
        maintenance.clear_partial("first")
    project.cancel(queued["id"])
    maintenance.remove_speech("second")
    assert speech_models.installed_path(first) is not None
    assert project.job(unrelated["id"])["status"] == "queued"


def test_native_hf_download_lock_blocks_cleanup_even_for_unregistered_workspace(catalog):
    first, _, _ = catalog
    lock = (
        speech_models.cache_directory()
        / ".locks"
        / speech_models.snapshot(first).parent.parent.name
        / "blob.lock"
    )
    lock.parent.mkdir(parents=True)
    with lock.open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ResourceBusy):
            maintenance.remove_speech("first")
        with pytest.raises(ResourceBusy):
            maintenance.clear_partial("first")
    assert speech_models.installed_path(first) is not None


@pytest.mark.parametrize("engine", ["qwen3-base-mlx", "qwen3-mlx"])
def test_legacy_qwen_synthesis_lock_blocks_model_cleanup(catalog, monkeypatch, engine):
    first, second, _ = catalog
    monkeypatch.setattr(speech_models, "CATALOG", [{**first, "engine": engine}, second])
    lock = preferences.data_directory() / "qwen-speech.lock"
    with lock.open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ResourceBusy, match="Qwen speech"):
            maintenance.remove_speech("first")
        with pytest.raises(ResourceBusy, match="Qwen speech"):
            maintenance.clear_partial("first")
    assert speech_models.installed_path(first) is not None
    maintenance.remove_speech("first")
    assert not speech_models.snapshot(first).exists()


def test_url_cache_remove_and_partial_clear_keep_download_lock(monkeypatch):
    item = {
        "id": "url-model",
        "name": "URL model",
        "url": "https://example.invalid/model.pt",
        "revision": "pinned",
        "files": {"model.pt": 5},
        "download_bytes": 5,
        "engine": "silero",
    }
    monkeypatch.setattr(speech_models, "CATALOG", [item])
    target = speech_models.snapshot(item)
    target.mkdir(parents=True)
    (target / "model.pt").write_bytes(b"model")
    partial = target / "model.pt.part"
    partial.write_bytes(b"partial")
    lock = target / ".download.lock"
    with lock.open("a") as handle:
        inode = lock.stat().st_ino
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ResourceBusy):
            maintenance.clear_partial("url-model")
    with (preferences.data_directory() / "qwen-speech.lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        maintenance.clear_partial("url-model")
        assert not partial.exists() and (target / "model.pt").read_bytes() == b"model"
        maintenance.remove_speech("url-model")
    assert not (target / "model.pt").exists() and lock.stat().st_ino == inode


def test_audio_clear_preserves_outputs_originals_recovery_and_checkpoints(tmp_path):
    project = Workspace(tmp_path / "unregistered-project")
    preserved = [
        "originals/source.epub",
        "jobs/job/podcast.mp3",
        "jobs/job/podcast.wav",
        "jobs/job/checkpoints/accepted.json",
        "recovery/note/copy.json",
        "voice-samples/ref.wav",
    ]
    for name in preserved:
        path = project.path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"preserve")
    cache = project.path / "audio-segments"
    cache.mkdir()
    (cache / "accepted.wav").write_bytes(b"audio")
    (cache / "accepted.json").write_bytes(b"meta")
    assert maintenance.audio_cache_info(project)["bytes"] == 9
    with audio_cache_lock(project):
        with pytest.raises(ResourceBusy):
            maintenance.clear_audio_cache(project)
    result = maintenance.clear_audio_cache(project)
    assert result["removed_bytes"] == 9 and result["removed_files"] == 2
    assert not cache.exists()
    assert all((project.path / name).read_bytes() == b"preserve" for name in preserved)


def test_symlink_cache_folder_cannot_delete_external_data(tmp_path):
    project = Workspace(tmp_path / "project")
    external = tmp_path / "external"
    external.mkdir()
    (external / "source.txt").write_text("preserve")
    (project.path / "audio-segments").symlink_to(external, target_is_directory=True)
    with pytest.raises(ValueError):
        maintenance.clear_audio_cache(project)
    assert (external / "source.txt").read_text() == "preserve"


@pytest.mark.parametrize("kind", ["render_podcast", "preview_turn"])
def test_legacy_render_blocks_only_its_live_workspace_audio_cache(tmp_path, kind):
    from brofessor.application.worker import worker_lock

    project = Workspace(tmp_path / "unregistered-project")
    other = Workspace(tmp_path / "other-project")
    for item in [project, other]:
        cache = item.path / "audio-segments"
        cache.mkdir()
        (cache / "accepted.wav").write_bytes(b"audio")
    job = project.submit(kind, {})
    project.claim()
    with worker_lock(project):
        with pytest.raises(ResourceBusy, match=job["id"]):
            maintenance.clear_audio_cache(project)
        assert (project.path / "audio-segments" / "accepted.wav").read_bytes() == b"audio"
        assert maintenance.clear_audio_cache(other)["removed_bytes"] == 5
    assert maintenance.clear_audio_cache(project)["removed_bytes"] == 5
    assert project.job(job["id"])["status"] == "running"  # Cleanup does not recover old jobs.

    cache = project.path / "audio-segments"
    cache.mkdir()
    (cache / "accepted.wav").write_bytes(b"audio")
    project.update_job(job["id"], status=JobStatus.SUCCEEDED)
    project.submit(JobKind.RENDER_SLIDES, {})
    project.claim()
    with worker_lock(project):
        assert maintenance.clear_audio_cache(project)["removed_bytes"] == 5


def test_models_guard_is_cross_process_and_cancellation_preserves_owner(tmp_path):
    script = "from brofessor.infrastructure.storage.locks import models_lock\nwith models_lock():\n print('ready',flush=True)\n input()\n"
    process = subprocess.Popen(
        [sys.executable, "-c", script], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True
    )
    try:
        assert process.stdout.readline().strip() == "ready"
        with models_lock(wait=False):
            pass
        with pytest.raises(ResourceBusy):
            with models_lock(exclusive=True, wait=False):
                pass
        calls = 0

        def check():
            nonlocal calls
            calls += 1
            if calls > 1:
                raise CancelledError("stop")

        with pytest.raises(CancelledError):
            with models_lock(exclusive=True, check=check):
                pass
        assert process.poll() is None
    finally:
        process.communicate("\n", timeout=5)
    with models_lock(exclusive=True, wait=False):
        pass


@pytest.fixture
def ollama(monkeypatch):
    state = {"disabled": True, "loaded": False, "terminal": True, "requests": []}
    model = {"name": "test:latest", "model": "test:latest", "size": 42, "digest": "123"}

    def handle(request):
        state["requests"].append((request.method, request.url.path, request.content))
        path = request.url.path
        if path == "/api/status":
            return httpx.Response(200, json={"cloud": {"disabled": state["disabled"]}})
        if path == "/api/tags":
            return httpx.Response(
                200,
                json={
                    "models": [
                        model,
                        {**model, "name": "bad:cloud"},
                        {**model, "name": "remote:latest", "remote_host": "remote"},
                    ]
                },
            )
        if path == "/api/show":
            return httpx.Response(200, json={})
        if path == "/api/ps":
            return httpx.Response(200, json={"models": [model] if state["loaded"] else []})
        if path == "/api/pull":
            messages = [
                {"status": "pulling manifest"},
                {"status": "pulling layer", "digest": "layer", "total": 42, "completed": 42},
            ]
            if state["terminal"]:
                messages.append({"status": "success"})
            return httpx.Response(200, content="\n".join(json.dumps(v) for v in messages))
        if path == "/api/delete":
            return httpx.Response(200)
        pytest.fail(f"Unexpected API call {request.method} {path}")

    original = httpx.AsyncClient

    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return original(**kwargs, transport=httpx.MockTransport(handle))

    monkeypatch.setattr(httpx, "AsyncClient", client)
    return state


def test_ollama_inventory_pull_and_explicit_delete_use_official_local_only_api(ollama):
    assert [m["name"] for m in maintenance.ollama_models("127.0.0.1:11434")] == ["test:latest"]
    job = maintenance.download_ollama("127.0.0.1:11434", "test", start_worker=False)
    assert job["kind"] == "download_ollama_model" and job["status"] == "queued"
    assert (
        maintenance.download_ollama("127.0.0.1:11434", "test", start_worker=False)["id"]
        == job["id"]
    )
    progress = []
    result = maintenance.pull_ollama(job["params"], progress=progress.append)
    assert result["model"] == "test:latest" and progress[-1]["completed"] == 42
    assert maintenance.remove_ollama("127.0.0.1:11434", "test")["removed"]
    deleted = [body for method, path, body in ollama["requests"] if method == "DELETE"]
    assert [json.loads(body) for body in deleted] == [{"model": "test:latest"}]
    assert not any(path in {"/api/chat", "/api/generate"} for _, path, _ in ollama["requests"])


def test_ollama_loaded_model_is_never_unloaded_or_deleted(ollama):
    ollama["loaded"] = True
    with pytest.raises(ResourceBusy):
        maintenance.remove_ollama("127.0.0.1:11434", "test")
    assert not any(method == "DELETE" for method, _, _ in ollama["requests"])


def test_ollama_rejects_cloud_and_truncated_pull_before_success(ollama):
    ollama["disabled"] = False
    with pytest.raises(RuntimeError, match="cloud"):
        maintenance.ollama_models("127.0.0.1:11434")
    with pytest.raises(RuntimeError):
        maintenance.download_ollama("127.0.0.1:11434", "test:cloud", start_worker=False)
    ollama["disabled"] = True
    ollama["terminal"] = False
    with pytest.raises(RuntimeError, match="before a success"):
        maintenance.pull_ollama({"model": "test", "ollama_address": "127.0.0.1:11434"})


def test_cancelled_pull_closes_http_stream_without_stopping_server(monkeypatch, ollama):
    closed = []

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'{"status":"pulling manifest"}\n'
            await asyncio.sleep(20)

        async def aclose(self):
            closed.append(True)

    original = maintenance._client

    def client(address):
        instance = original(address)
        transport = instance._transport
        original_handler = transport.handler

        def handle(request):
            if request.url.path == "/api/pull":
                return httpx.Response(200, stream=Stream())
            return original_handler(request)

        transport.handler = handle
        return instance

    monkeypatch.setattr(maintenance, "_client", client)
    calls = 0

    def cancelled():
        nonlocal calls
        calls += 1
        return calls > 3

    with pytest.raises(CancelledError):
        maintenance.pull_ollama({"model": "test", "ollama_address": "127.0.0.1:11434"}, cancelled)
    assert closed and not any(method == "DELETE" for method, _, _ in ollama["requests"])
