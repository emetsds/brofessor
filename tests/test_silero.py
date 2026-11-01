"""Silero contracts use tiny fake weights and a fake torch module, never inference."""

import contextlib
import copy
import hashlib
import sys
import wave
from types import SimpleNamespace

import httpx
import pytest

from brofessor import media, service, speech_models, worker
from brofessor.workspace import Workspace


@pytest.fixture
def silero(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    weights = b"test weights"
    spec = copy.deepcopy(next(m for m in speech_models.CATALOG if m.get("engine") == "silero"))
    spec.update(
        files={"model.pt": len(weights)},
        download_bytes=len(weights),
        sha256=hashlib.sha256(weights).hexdigest(),
        revision=hashlib.sha256(weights).hexdigest(),
    )
    monkeypatch.setattr(speech_models, "CATALOG", [spec])
    return spec, weights


def mock_http(monkeypatch, handler):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(speech_models.httpx, "stream", client.stream)


def test_http_model_is_verified_cached_and_reused(silero, monkeypatch):
    spec, weights = silero
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, content=weights)

    mock_http(monkeypatch, handler)
    first = speech_models.download(spec["id"])
    speech_models.download(spec["id"])
    assert first["revision"] == spec["sha256"]
    assert len(requests) == 1
    target = speech_models.installed_path(spec)
    (target / "model.pt").write_bytes(b"bad! weights")  # Same size, different checksum.
    assert speech_models.installed_path(spec) is None


def test_http_checksum_failure_never_publishes_installed_model(silero, monkeypatch):
    spec, weights = silero
    mock_http(monkeypatch, lambda request: httpx.Response(200, content=b"x" * len(weights)))
    with pytest.raises(RuntimeError, match="SHA-256"):
        speech_models.download(spec)
    assert speech_models.installed_path(spec) is None
    assert not (speech_models.snapshot(spec) / "model.pt.part").exists()


def test_complete_partial_file_can_finish_without_network(silero, monkeypatch):
    spec, weights = silero
    folder = speech_models.snapshot(spec)
    folder.mkdir(parents=True)
    (folder / "model.pt.part").write_bytes(weights)
    mock_http(monkeypatch, lambda request: pytest.fail("Already downloaded, no network needed"))
    speech_models.download(spec)
    assert speech_models.installed_path(spec) == folder


def test_unchanged_weights_are_not_rehashed_on_every_ui_poll(silero, monkeypatch):
    spec, weights = silero
    folder = speech_models.snapshot(spec)
    folder.mkdir(parents=True)
    output = folder / "model.pt"
    output.write_bytes(weights)
    original = hashlib.file_digest
    calls = []

    def digest(*args):
        calls.append(1)
        return original(*args)

    monkeypatch.setattr(hashlib, "file_digest", digest)
    for _ in range(3):
        assert speech_models.installed_path(spec) == folder
    assert len(calls) == 1
    output.write_bytes(b"x" * len(weights))
    assert speech_models.installed_path(spec) is None
    assert len(calls) == 2


def test_interrupted_http_download_resumes_original_revision(silero, tmp_path, monkeypatch):
    spec, _ = silero
    weights = b"a" * (1024 * 1024) + b"end"
    spec.update(files={"model.pt": len(weights)}, download_bytes=len(weights))
    spec["sha256"] = spec["revision"] = hashlib.sha256(weights).hexdigest()
    submitted = copy.deepcopy(spec)
    requests = []

    class Broken(httpx.SyncByteStream):
        def __iter__(self):
            yield weights[: 1024 * 1024]
            raise httpx.ReadError("Synthetic interruption")

    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(200, stream=Broken())
        assert request.headers["range"] == "bytes=1048576-"
        return httpx.Response(
            206,
            headers={"content-range": f"bytes 1048576-{len(weights) - 1}/{len(weights)}"},
            content=weights[1024 * 1024 :],
        )

    mock_http(monkeypatch, handler)
    workspace = Workspace(tmp_path / "workspace")
    job = service.download_model(workspace, spec["id"], start_worker=False)
    worker.run(workspace, once=True)
    assert workspace.job(job["id"])["status"] == "failed"
    spec["revision"] = "f" * 64
    workspace.resume(job["id"])
    worker.run(workspace, once=True)
    assert workspace.job(job["id"])["status"] == "succeeded"
    assert (speech_models.snapshot(submitted) / "model.pt").read_bytes() == weights


@pytest.mark.parametrize("text,spoken", [("Вопр+ос?", "Вопр+ос?"), ("„Вопр+ос?“", '"Вопр+ос?"')])
def test_silero_engine_uses_its_voices_and_common_audio_cache(
    silero, tmp_path, monkeypatch, text, spoken
):
    import numpy as np

    spec, weights = silero
    directory = speech_models.snapshot(spec)
    directory.mkdir(parents=True)
    (directory / "model.pt").write_bytes(weights)
    calls = []

    class Model:
        speakers = list(spec["voices"].values())

        def to(self, device):
            assert device == "cpu"

        def apply_tts(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(cpu=lambda: SimpleNamespace(numpy=lambda: np.ones(48000) * 0.1))

    def load_pickle(module, name):
        assert (module, name) == ("tts_models", "model")
        return Model()

    fake_torch = SimpleNamespace(
        set_num_threads=lambda n: None,
        device=lambda name: name,
        inference_mode=contextlib.nullcontext,
        package=SimpleNamespace(
            PackageImporter=lambda path: SimpleNamespace(load_pickle=load_pickle)
        ),
    )

    def write(path, audio, sample_rate, **kwargs):
        with wave.open(path, "wb") as stream:
            stream.setparams((1, 2, sample_rate, 0, "NONE", "none"))
            stream.writeframes(b"\x01\x00" * len(audio))

    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "soundfile", SimpleNamespace(write=write))
    monkeypatch.setattr(media, "_ffmpeg", lambda: None)
    plan = {
        "language": "ru",
        "turns": [
            {"speaker": "host", "text": text},
            {"speaker": "guest", "text": "Отв+ет."},
        ],
    }
    result = media.render_audio(
        plan, tmp_path / "one.wav", segment_dir=tmp_path / "segments", model_spec=spec
    )
    assert [call["speaker"] for call in calls] == list(spec["voices"].values())
    assert calls[0]["text"] == spoken
    assert plan["turns"][0]["text"] == text
    assert result["engine"] == "silero" and result["duration_seconds"] == 2.25
    repeated = media.render_audio(
        plan, tmp_path / "two.wav", segment_dir=tmp_path / "segments", model_spec=spec
    )
    assert all(segment["reused"] for segment in repeated["segments"])
    assert len(calls) == 2
    plan["language"] = "en"
    with pytest.raises(ValueError, match="does not support en"):
        media.render_audio(
            plan, tmp_path / "bad.wav", segment_dir=tmp_path / "segments", model_spec=spec
        )


@pytest.mark.parametrize("text", ["Открыто в 2025 году.", "Пример OpenAI."])
def test_silero_rejects_text_it_would_silently_drop(silero, tmp_path, text):
    spec, _ = silero
    with pytest.raises(ValueError, match="numbers and Latin"):
        media.render_audio(
            {"language": "ru", "turns": [{"speaker": "host", "text": text}]},
            tmp_path / "bad.wav",
            segment_dir=tmp_path / "segments",
            model_spec=spec,
        )


@pytest.mark.parametrize(
    "language,text,message",
    [("en", "An answer.", "does not support en"), ("ru", "Всего 12 страниц.", "numbers and Latin")],
)
def test_invalid_silero_request_does_not_enqueue_audio(silero, tmp_path, language, text, message):
    spec, _ = silero
    workspace = Workspace(tmp_path / "workspace")
    source = tmp_path / "source.txt"
    source.write_text("Synthetic evidence")
    workspace.add_source(source)
    citation = workspace.units()[0]["id"]
    job = service.submit(workspace, "podcast", language=language, start_worker=False)
    workspace.save_draft(
        job["id"],
        {
            "title": "Test",
            "language": language,
            "turns": [
                {"speaker": "host", "text": text, "citations": [citation]},
                {"speaker": "guest", "text": text, "citations": [citation]},
            ],
        },
    )
    with pytest.raises(ValueError, match=message):
        service.render(workspace, job["id"], model=spec["id"], start_worker=False)
    assert len(workspace.jobs()) == 1
