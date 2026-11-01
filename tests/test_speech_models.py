"""Model-download lifecycle with tiny synthetic weights; no network or inference."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from brofessor import media, service, speech_models, worker
from brofessor.cli import app
from brofessor.executors import CancelledError
from brofessor.workspace import Workspace


@pytest.fixture
def models(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setattr(speech_models, "_legacy_caches", lambda: [])
    entries = []
    for index, original in enumerate(speech_models.CATALOG):
        if original.get("engine") != "qwen3-mlx":
            continue
        entries.append(
            {
                **original,
                "repo": f"test/voice-{index}",
                "revision": str(index) * 40,
                "files": {"config.json": 2, "model.safetensors": 7},
                "download_bytes": 9,
            }
        )
    monkeypatch.setattr(speech_models, "CATALOG", entries)
    return entries


def write_weights(path):
    path.mkdir(parents=True, exist_ok=True)
    (path / "config.json").write_bytes(b"{}")
    (path / "model.safetensors").write_bytes(b"weights")


def test_download_is_pinned_reports_progress_and_reuses_weights_between_projects(
    models, tmp_path, monkeypatch
):
    calls = []

    def download(**kwargs):
        calls.append(kwargs)
        assert kwargs["token"] is False
        assert kwargs["revision"] == models[0]["revision"]
        bar = kwargs["tqdm_class"](total=9, unit="B", name="huggingface_hub.snapshot_download")
        bar.update(4)
        write_weights(speech_models.snapshot(models[0]))
        bar.close()

    monkeypatch.setattr(speech_models, "_snapshot_download", download)
    first = Workspace(tmp_path / "first")
    job = service.download_model(first, models[0]["id"], start_worker=False)
    assert worker.run(first, once=True)
    result = first.job(job["id"])
    assert result["status"] == "succeeded"
    assert result["progress"]["completed"] == result["progress"]["total"] == 9
    assert speech_models.installed_path(models[0]["id"]).is_relative_to(tmp_path / "data")
    second = Workspace(tmp_path / "second")
    reused = service.download_model(second, models[0]["id"], start_worker=False)
    worker.run(second, once=True)
    assert second.job(reused["id"])["status"] == "succeeded"
    assert len(calls) == 1


def test_incomplete_or_damaged_weights_are_not_installed(models):
    path = speech_models.snapshot(models[0])
    path.mkdir(parents=True)
    (path / "config.json").write_bytes(b"{}")
    assert speech_models.installed_path(models[0]["id"]) is None
    write_weights(path)
    assert speech_models.installed_path(models[0]["id"]) == path
    (path / "model.safetensors").write_bytes(b"broken")
    assert speech_models.installed_path(models[0]["id"]) is None


def test_complete_legacy_weights_are_imported_without_network(models, tmp_path, monkeypatch):
    legacy_cache = tmp_path / "legacy"
    legacy = speech_models.snapshot(models[0], legacy_cache)
    write_weights(legacy)
    monkeypatch.setattr(speech_models, "_legacy_caches", lambda: [legacy_cache])
    monkeypatch.setattr(
        speech_models, "_snapshot_download", lambda **kwargs: pytest.fail("Unexpected network")
    )
    result = speech_models.download(models[0]["id"])
    assert (Path(result["path"]) / "model.safetensors").read_bytes() == b"weights"
    assert (legacy / "model.safetensors").read_bytes() == b"weights"


def test_failed_download_can_resume_after_reopening_project(models, tmp_path, monkeypatch):
    count = 0

    def download(**kwargs):
        nonlocal count
        count += 1
        path = speech_models.snapshot(models[0])
        path.mkdir(parents=True, exist_ok=True)
        (path / "config.json").write_bytes(b"{}")
        if count == 1:
            raise RuntimeError("Synthetic download interruption")
        assert (path / "config.json").read_bytes() == b"{}"
        write_weights(path)

    monkeypatch.setattr(speech_models, "_snapshot_download", download)
    workspace = Workspace(tmp_path / "workspace")
    job = service.download_model(workspace, models[0]["id"], start_worker=False)
    worker.run(workspace, once=True)
    assert workspace.job(job["id"])["status"] == "failed"
    assert not workspace.artifacts(job["id"])
    reopened = Workspace(workspace.path)
    reopened.resume(job["id"])
    worker.run(reopened, once=True)
    assert reopened.job(job["id"])["status"] == "succeeded"


def test_cancel_preserves_partial_files_without_publishing_success(models, monkeypatch):
    stop = False

    def download(**kwargs):
        nonlocal stop
        path = speech_models.snapshot(models[0])
        path.mkdir(parents=True)
        (path / "config.json").write_bytes(b"{}")
        bar = kwargs["tqdm_class"](total=9, unit="B", name="huggingface_hub.snapshot_download")
        stop = True
        bar.update(2)

    monkeypatch.setattr(speech_models, "_snapshot_download", download)
    with pytest.raises(CancelledError):
        speech_models.download(models[0]["id"], cancelled=lambda: stop)
    assert speech_models.installed_path(models[0]["id"]) is None
    assert (speech_models.snapshot(models[0]) / "config.json").exists()


def test_render_pins_selected_model_before_preferences_change(models, tmp_path):
    workspace = Workspace(tmp_path / "workspace")
    source = tmp_path / "source.txt"
    source.write_text("A measured result")
    workspace.add_source(source)
    citation = workspace.units()[0]["id"]
    draft = service.submit(workspace, "podcast", start_worker=False)
    workspace.save_draft(
        draft["id"],
        {
            "title": "Test",
            "language": "en",
            "turns": [
                {"speaker": "host", "text": "Question?", "citations": [citation]},
                {"speaker": "guest", "text": "Answer.", "citations": [citation]},
            ],
        },
    )
    speech_models.use(models[0]["id"])
    render = service.render(workspace, draft["id"], start_worker=False)
    speech_models.use(models[1]["id"])
    assert render["params"]["model"] == f"{models[0]['repo']}@{models[0]['revision']}"
    models[0]["voices"] = {"host": "Changed", "guest": "Changed"}
    assert render["params"]["model_spec"]["voices"] == {"host": "Ryan", "guest": "Vivian"}
    assert media._model_identity(models[0]["id"])["revision"] == models[0]["revision"]


def test_retired_qwen_reference_uses_shared_installed_snapshot(models, monkeypatch):
    import copy
    from brofessor import speech

    old = copy.deepcopy(models[0])
    write_weights(speech_models.snapshot(old))
    models[0]["revision"] = "e" * 40
    calls = []
    marker = object()

    def load(spec, location):
        calls.append(location)
        return marker

    monkeypatch.setattr(speech, "load", load)
    monkeypatch.setattr(
        "huggingface_hub.snapshot_download", lambda *a, **kw: pytest.fail("Unexpected network")
    )
    identity = media._model_identity(f"{old['repo']}@{old['revision']}")
    assert media._load_speech_model(identity) is marker
    assert calls == [speech_models.snapshot(old)]


@pytest.mark.parametrize("legacy", [True, False])
def test_render_request_key_survives_snapshot_addition_and_distinguishes_revisions(
    models, tmp_path, legacy
):
    workspace = Workspace(tmp_path / "workspace")
    source = tmp_path / "source.txt"
    source.write_text("Synthetic evidence")
    workspace.add_source(source)
    citation = workspace.units()[0]["id"]
    draft = service.submit(workspace, "podcast", start_worker=False)
    workspace.save_draft(
        draft["id"],
        {
            "title": "Test",
            "language": "ru",
            "turns": [
                {"speaker": "host", "text": "Вопрос?", "citations": [citation]},
                {"speaker": "guest", "text": "Ответ.", "citations": [citation]},
            ],
        },
    )
    choice = models[0]["id"]
    if legacy:
        key = f"render:{draft['id']}:1:{choice}"
        original = workspace.submit(
            "render_podcast",
            {
                "draft_job_id": draft["id"],
                "revision": 1,
                "model": speech_models.reference(choice),
                "minutes": 20,
            },
            key,
        )
    else:
        key = service.render_request_key(workspace, draft["id"], choice)
        original = service.render(
            workspace, draft["id"], model=choice, request_key=key, start_worker=False
        )
    models[0]["notes"] = "Updated description, same requested model"
    assert service.render_request_key(workspace, draft["id"], choice) == key
    repeated = service.render(
        workspace, draft["id"], model=choice, request_key=key, start_worker=False
    )
    assert repeated["id"] == original["id"]
    models[0]["revision"] = "c" * 40
    changed_key = service.render_request_key(workspace, draft["id"], choice)
    assert changed_key != key
    changed = service.render(
        workspace, draft["id"], model=choice, request_key=changed_key, start_worker=False
    )
    assert changed["id"] != original["id"]
    with pytest.raises(ValueError, match="different operation"):
        service.render(workspace, draft["id"], model=choice, request_key=key, start_worker=False)


def test_cli_download_uses_same_worker_and_returns_installed_result(models, tmp_path, monkeypatch):
    monkeypatch.setattr(
        speech_models,
        "_snapshot_download",
        lambda **kwargs: write_weights(speech_models.snapshot(models[0])),
    )
    monkeypatch.setattr(worker, "ensure_worker", lambda workspace: worker.run(workspace, once=True))
    result = CliRunner().invoke(
        app, ["-w", str(tmp_path / "workspace"), "tts", "download", models[0]["id"], "--wait"]
    )
    assert result.exit_code == 0, result.output
    assert '"status": "succeeded"' in result.output
    assert speech_models.installed_path(models[0]["id"]) is not None


@pytest.mark.parametrize("interrupted", [False, True])
def test_download_keeps_submitted_revision_when_catalog_changes(
    models, tmp_path, monkeypatch, interrupted
):
    import copy

    submitted = copy.deepcopy(models[0])
    calls = []

    def download(**kwargs):
        calls.append(kwargs["revision"])
        if interrupted and len(calls) == 1:
            raise RuntimeError("Synthetic interruption")
        write_weights(speech_models.snapshot(submitted))

    monkeypatch.setattr(speech_models, "_snapshot_download", download)
    workspace = Workspace(tmp_path / "workspace")
    job = service.download_model(workspace, submitted["id"], start_worker=False)
    if interrupted:
        worker.run(workspace, once=True)
        assert workspace.job(job["id"])["status"] == "failed"
        workspace.resume(job["id"])
    models[0]["revision"] = "f" * 40
    worker.run(workspace, once=True)
    assert workspace.job(job["id"])["status"] == "succeeded"
    assert set(calls) == {submitted["revision"]}
    artifact = workspace.artifacts(job["id"])[0]
    assert artifact["metadata"]["revision"] == submitted["revision"]
    old_reference = f"{submitted['repo']}@{submitted['revision']}"
    assert speech_models.get(old_reference)["revision"] == submitted["revision"]
    assert speech_models.installed_path(old_reference) == speech_models.snapshot(submitted)
