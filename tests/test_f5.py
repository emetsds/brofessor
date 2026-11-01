"""Pinned component downloads and reference-based rendering, without real models."""

import copy
import io
import wave
from pathlib import Path

import pytest
from typer.testing import CliRunner

from brofessor import media, service, speech_models, speech_references
from brofessor.cli import app
from brofessor.workspace import Workspace


def wav(value=1, seconds=3):
    output = io.BytesIO()
    with wave.open(output, "wb") as stream:
        stream.setparams((1, 2, 24000, 0, "NONE", "none"))
        stream.writeframes(int(value).to_bytes(2, "little", signed=True) * (24000 * seconds))
    return output.getvalue()


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setattr(speech_models, "_legacy_caches", lambda: [])


def setup_draft(tmp_path):
    workspace = Workspace(tmp_path / "workspace")
    source = tmp_path / "source.txt"
    source.write_text("Synthetic evidence")
    workspace.add_source(source)
    citation = workspace.units()[0]["id"]
    job = service.submit(workspace, "podcast", language="en", start_worker=False)
    workspace.save_draft(
        job["id"],
        {
            "title": "Test",
            "language": "en",
            "turns": [
                {"speaker": "host", "text": "What happened?", "citations": [citation]},
                {"speaker": "guest", "text": "A test happened.", "citations": [citation]},
            ],
        },
    )
    return workspace, job


@pytest.mark.parametrize(
    "audio,text",
    [
        (b"bad", "Text"),
        (wav(0), "Text"),
        (wav(), " "),
        (wav(seconds=1), "Text"),
        (wav()[:-5], "Text"),
    ],
)
def test_invalid_samples_do_not_change_preferences(audio, text):
    with pytest.raises(ValueError):
        speech_references.save("host", "en", audio, text)
    assert speech_references.list_references("en") == {}


def test_cli_voice_configuration_and_immutable_render_snapshot(tmp_path):
    sample = tmp_path / "sample.wav"
    sample.write_bytes(wav())
    cli = CliRunner()
    for role in ("host", "guest"):
        result = cli.invoke(
            app,
            [
                "tts",
                "voice",
                "set",
                role,
                "--audio",
                str(sample),
                "--text",
                "Reference speech.",
                "--language",
                "en",
            ],
        )
        assert result.exit_code == 0, result.output
    workspace, draft = setup_draft(tmp_path)
    key = service.render_request_key(workspace, draft["id"], "f5-tts")
    job = service.render(
        workspace, draft["id"], model="f5-tts", request_key=key, start_worker=False
    )
    original = job["params"]["model_spec"]["references"]["host"]
    speech_references.save("host", "en", wav(2), "Another sample.")
    assert (workspace.path / original["path"]).read_bytes() == wav()
    assert service.render_request_key(workspace, draft["id"], "f5-tts") != key
    repeated = service.render(
        workspace, draft["id"], model="f5-tts", request_key=key, start_worker=False
    )
    assert repeated["params"]["model_spec"]["references"]["host"] == original


def test_missing_or_damaged_reference_rejects_job_before_enqueue(tmp_path):
    workspace, draft = setup_draft(tmp_path)
    with pytest.raises(ValueError, match="voice sample"):
        service.render(workspace, draft["id"], model="f5-tts", start_worker=False)
    for role in ("host", "guest"):
        speech_references.save(role, "en", wav(), "Reference speech.")
    ref = speech_references.selected("en")["host"]
    Path(ref["path"]).write_bytes(wav(2))
    with pytest.raises(ValueError, match="damaged"):
        service.render(workspace, draft["id"], model="f5-tts", start_worker=False)
    assert len(workspace.jobs()) == 1


def test_reference_samples_survive_closed_project_move(tmp_path):
    import shutil

    for role in ("host", "guest"):
        speech_references.save(role, "en", wav(), "Reference speech.")
    workspace, draft = setup_draft(tmp_path)
    job = service.render(workspace, draft["id"], model="f5-tts", start_worker=False)
    copied = tmp_path / "moved"
    shutil.copytree(workspace.path, copied)
    shutil.rmtree(workspace.path)
    for ref in speech_references.selected("en").values():
        Path(ref["path"]).unlink(missing_ok=True)
    refs = speech_references.resolve(copied, job["params"]["model_spec"]["references"])
    assert all(Path(ref["path"]).read_bytes() == wav() for ref in refs.values())


def test_vocoder_download_is_pinned_shared_and_reported(tmp_path, monkeypatch):
    models = [copy.deepcopy(speech_models.get(name)) for name in ("f5-tts", "espeech-rl-v2")]
    components = {}
    for item in models:
        for component in [*item["dependencies"], item]:
            component["files"] = {"weights.bin": 7}
            component["download_bytes"] = 7
            components[component["repo"]] = component
    monkeypatch.setattr(speech_models, "CATALOG", models)
    calls = []

    def download(**kwargs):
        spec = components[kwargs["repo_id"]]
        calls.append(kwargs["repo_id"])
        assert kwargs["revision"] == spec["revision"]
        folder = speech_models.snapshot(spec)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "weights.bin").write_bytes(b"weights")

    monkeypatch.setattr(speech_models, "_snapshot_download", download)
    progress = []
    for item in models:
        speech_models.download(item, progress=progress.append)
        assert speech_models.installed_path(item) is not None
    assert calls.count(models[0]["dependencies"][0]["repo"]) == 1
    assert progress[-1]["completed"] == progress[-1]["total"] == 14
    (speech_models.snapshot(models[0]["dependencies"][0]) / "weights.bin").unlink()
    assert speech_models.installed_path(models[0]) is None


def test_voice_changes_invalidate_only_affected_segments(tmp_path, monkeypatch):
    for role in ("host", "guest"):
        speech_references.save(role, "en", wav(), "Reference speech.")
    spec = speech_models.get("f5-tts")
    spec["references"] = speech_references.selected("en")
    monkeypatch.setattr(media, "_load_speech_model", lambda spec: object())
    monkeypatch.setattr(media, "_ffmpeg", lambda: None)
    monkeypatch.setattr(
        media,
        "_synthesize",
        lambda model, text, voice, language, output, cancelled: output.write_bytes(wav()),
    )
    plan = {
        "language": "en",
        "turns": [
            {"speaker": "host", "text": "A question."},
            {"speaker": "guest", "text": "An answer."},
        ],
    }
    media.render_audio(
        plan, tmp_path / "one.wav", segment_dir=tmp_path / "segments", model_spec=spec
    )
    speech_references.save("host", "en", wav(2), "New reference speech.")
    spec["references"] = speech_references.selected("en")
    result = media.render_audio(
        plan, tmp_path / "two.wav", segment_dir=tmp_path / "segments", model_spec=spec
    )
    assert [s["reused"] for s in result["segments"]] == [False, True]
