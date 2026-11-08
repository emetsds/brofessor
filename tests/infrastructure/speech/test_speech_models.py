"""Model-download lifecycle with tiny synthetic weights; no network or inference."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from brofessor.application import service, worker
from brofessor.contracts.jobs import JobKind
from brofessor.infrastructure.formats import audio as media
from brofessor.infrastructure.speech import catalogue as speech_models
from brofessor.infrastructure.storage import preferences
from brofessor.infrastructure.storage.workspace import Workspace
from brofessor.infrastructure.text.runners import CancelledError
from brofessor.interfaces.cli.app import app


@pytest.fixture
def models(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setattr(speech_models, "_external_caches", lambda: [])
    entries = [
        {
            "id": f"test-{index}",
            "name": f"Test voice {index}",
            "engine": "qwen3-base-mlx",
            "repo": f"test/voice-{index}",
            "revision": str(index) * 40,
            "files": {"config.json": 2, "model.safetensors": 7},
            "download_bytes": 9,
            "voices": {"host": "Ryan", "guest": "Vivian"},
            "languages": ["ru", "en"],
            "settings": {"seed": 42},
        }
        for index in range(2)
    ]
    monkeypatch.setattr(speech_models, "CATALOG", entries)
    preferences.update(tts_model=entries[0]["id"])
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


def test_external_pinned_weights_are_imported_without_network(models, tmp_path, monkeypatch):
    legacy_cache = tmp_path / "legacy"
    legacy = speech_models.snapshot(models[0], legacy_cache)
    write_weights(legacy)
    monkeypatch.setattr(speech_models, "_external_caches", lambda: [legacy_cache])
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
    preferences.update(tts_model=models[0]["id"])
    draft = service.submit(workspace, JobKind.PODCAST, start_worker=False)
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
    render = service.render(workspace, draft["id"], start_worker=False)
    preferences.update(tts_model=models[1]["id"])
    assert render["params"]["model"] == f"{models[0]['repo']}@{models[0]['revision']}"
    models[0]["voices"] = {"host": "Changed", "guest": "Changed"}
    assert render["params"]["model_spec"]["voices"] == {"host": "Ryan", "guest": "Vivian"}
    assert media._model_identity(models[0]["id"])["revision"] == models[0]["revision"]


@pytest.mark.parametrize("choice", ["unknown/repository@" + "a" * 40, "local-folder"])
def test_new_render_rejects_models_outside_catalog_before_queueing(
    models, tmp_path, monkeypatch, choice
):
    workspace = Workspace(tmp_path / "workspace")
    path = tmp_path / "source.txt"
    path.write_text("Synthetic evidence")
    workspace.add_source(path)
    citation = workspace.units()[0]["id"]
    job = service.submit(workspace, JobKind.PODCAST, start_worker=False)
    workspace.save_draft(
        job["id"],
        {
            "title": "Test",
            "language": "ru",
            "turns": [
                {"speaker": "host", "text": "Вопрос?", "citations": [citation]},
                {"speaker": "guest", "text": "Ответ.", "citations": [citation]},
            ],
        },
    )
    folder = tmp_path / "local-folder"
    folder.mkdir()
    (folder / "config.json").write_text("{}")
    model = str(folder) if choice == "local-folder" else choice
    monkeypatch.setattr(
        "brofessor.application.worker.ensure_worker",
        lambda *_: pytest.fail("Worker must not start"),
    )
    with pytest.raises(ValueError, match="Unknown TTS model"):
        service.render(workspace, job["id"], model=model)
    result = CliRunner().invoke(
        app, ["-w", str(workspace.path), "draft", "render", job["id"], "--tts-model", model]
    )
    assert result.exit_code == 2 and "Unknown TTS model" in result.output
    assert len(workspace.jobs()) == 1


def test_explicit_render_retry_preserves_snapshot_and_rejects_a_different_model(models, tmp_path):
    workspace = Workspace(tmp_path / "workspace")
    source = tmp_path / "source.txt"
    source.write_text("Synthetic evidence")
    workspace.add_source(source)
    citation = workspace.units()[0]["id"]
    draft = service.submit(workspace, JobKind.PODCAST, start_worker=False)
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
    key = "explicit-render-retry"
    original = service.render(
        workspace, draft["id"], model=choice, request_key=key, start_worker=False
    )
    models[0]["notes"] = "Updated description, same requested model"
    repeated = service.render(
        workspace, draft["id"], model=choice, request_key=key, start_worker=False
    )
    assert repeated["id"] == original["id"]
    models[0]["revision"] = "c" * 40
    changed = service.render(workspace, draft["id"], model=choice, start_worker=False)
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


def test_public_catalog_contains_only_the_chosen_speech_method():
    assert [m["id"] for m in speech_models.list_models()] == ["qwen3-base"]
    with pytest.raises(ValueError, match="Unknown TTS model"):
        speech_models.get("f5-tts")


@pytest.mark.parametrize("saved", ["f5-tts", "retired-or-unknown"])
def test_retired_preference_falls_back_without_changing_saved_values(tmp_path, monkeypatch, saved):
    from brofessor.infrastructure.storage import preferences

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    preferences.update(tts_model=saved, ui_language="en")
    assert speech_models.selected() == "qwen3-base"
    assert preferences.read() == {"tts_model": saved, "ui_language": "en"}
    with pytest.raises(ValueError):
        preferences.save_settings("codex", language="en", speech_model=saved)
    assert preferences.read()["tts_model"] == saved
