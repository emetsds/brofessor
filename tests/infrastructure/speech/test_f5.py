"""Pinned component downloads and reference-based rendering, without real models."""

import copy
import io
import wave
from pathlib import Path

import pytest
from typer.testing import CliRunner

from brofessor.application import service
from brofessor.contracts.content import ContentLanguage
from brofessor.contracts.jobs import JobKind
from brofessor.infrastructure.formats import audio as media
from brofessor.infrastructure.speech import catalogue as speech_models
from brofessor.infrastructure.speech import references as speech_references
from brofessor.infrastructure.storage.workspace import Workspace
from brofessor.interfaces.cli.app import app


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
    job = service.submit(
        workspace, JobKind.PODCAST, language=ContentLanguage.EN, start_worker=False
    )
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
    key = "explicit-render-retry"
    job = service.render(
        workspace, draft["id"], model="f5-tts", request_key=key, start_worker=False
    )
    original = job["params"]["model_spec"]["references"]["host"]
    speech_references.save("host", "en", wav(2), "Another sample.")
    assert (workspace.path / original["path"]).read_bytes() == wav()
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


def test_render_identity_uses_the_same_frozen_voice_inputs_as_execution(tmp_path, monkeypatch):
    for role in ("host", "guest"):
        speech_references.save(role, "en", wav(), "Reference A.")
    workspace, draft = setup_draft(tmp_path)
    freeze = speech_references.freeze

    def another_client_changes_voice(folder, refs):
        snapshot = freeze(folder, refs)
        speech_references.save("host", "en", wav(2), "Reference B.")
        return snapshot

    monkeypatch.setattr(speech_references, "freeze", another_client_changes_voice)
    original = service.render(workspace, draft["id"], model="f5-tts", start_worker=False)
    original_refs = original["params"]["model_spec"]["references"]
    assert (workspace.path / original_refs["host"]["path"]).read_bytes() == wav()
    monkeypatch.setattr(speech_references, "freeze", freeze)
    changed = service.render(workspace, draft["id"], model="f5-tts", start_worker=False)
    assert changed["id"] != original["id"]
    assert changed["params"]["model_spec"]["references"]["host"]["text"] == "Reference B."
    speech_references.save("host", "en", wav(), "Reference A.")
    repeated = service.render(workspace, draft["id"], model="f5-tts", start_worker=False)
    assert repeated["id"] == original["id"] and repeated["params"] == original["params"]
    speech_references.save("host", "en", wav(), "Different exact transcript, same audio.")
    transcript_changed = service.render(workspace, draft["id"], model="f5-tts", start_worker=False)
    assert transcript_changed["id"] not in {original["id"], changed["id"]}


def test_concurrent_explicit_render_retries_share_the_first_snapshot(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier, Event

    for role in ("host", "guest"):
        speech_references.save(role, "en", wav(), "Reference A.")
    workspace, draft = setup_draft(tmp_path)
    frozen_a, release_a, submit_together = Event(), Event(), Barrier(2)
    freeze, submit = speech_references.freeze, workspace.submit

    def freeze_during_another_client_edit(folder, refs):
        snapshot = freeze(folder, refs)
        if refs["host"]["text"] == "Reference A.":
            frozen_a.set()
            assert release_a.wait(5)
        else:
            release_a.set()
        return snapshot

    def enqueue_together(*args):
        submit_together.wait(timeout=5)
        return submit(*args)

    monkeypatch.setattr(speech_references, "freeze", freeze_during_another_client_edit)
    monkeypatch.setattr(workspace, "submit", enqueue_together)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            service.render,
            workspace,
            draft["id"],
            model="f5-tts",
            request_key="same-click",
            start_worker=False,
        )
        assert frozen_a.wait(5)
        speech_references.save("host", "en", wav(2), "Reference B.")
        second = pool.submit(
            service.render,
            workspace,
            draft["id"],
            model="f5-tts",
            request_key="same-click",
            start_worker=False,
        )
        one, two = first.result(timeout=8), second.result(timeout=8)
    assert one["id"] == two["id"] and one["params"] == two["params"]
    assert len([j for j in workspace.jobs() if j["kind"] == "render_podcast"]) == 1
    # A retry is independent of mutable preferences and the original upload.
    current = speech_references.selected("en")["host"]
    Path(current["path"]).unlink()
    monkeypatch.setattr(workspace, "submit", submit)
    retry = service.render(
        workspace, draft["id"], model="f5-tts", request_key="same-click", start_worker=False
    )
    assert retry["id"] == one["id"] and retry["params"] == one["params"]


def test_render_reuses_same_audio_inputs_but_not_changed_speech_settings(tmp_path, monkeypatch):
    for role in ("host", "guest"):
        speech_references.save(role, "en", wav(), "Reference speech.")
    workspace, draft = setup_draft(tmp_path)
    original = service.render(workspace, draft["id"], model="f5-tts", start_worker=False)
    catalog = copy.deepcopy(speech_models.CATALOG)
    item = next(item for item in catalog if item["id"] == "f5-tts")
    monkeypatch.setattr(speech_models, "CATALOG", catalog)
    item["notes"] = "A different explanation of the same model."
    repeated = service.render(workspace, draft["id"], model="f5-tts", start_worker=False)
    assert repeated["id"] == original["id"] and repeated["params"] == original["params"]
    item["settings"]["speed"] = 0.8
    changed = service.render(workspace, draft["id"], model="f5-tts", start_worker=False)
    assert changed["id"] != original["id"]
    assert changed["params"]["model_spec"]["settings"]["speed"] == 0.8


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
    models = [
        copy.deepcopy(speech_models.get(name))
        for name in ("f5-tts", "f5-tts-russian", "espeech-rl-v2")
    ]
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


def test_russian_f5_uses_russian_references_and_rejects_english_draft(tmp_path):
    w, draft = setup_draft(tmp_path)
    with pytest.raises(ValueError, match="does not support en"):
        service.render(w, draft["id"], model="f5-tts-russian", start_worker=False)
    data = w.draft(draft["id"])["data"]
    data["language"] = "ru"
    service.edit_draft(w, draft["id"], data, 1)
    for role in ("host", "guest"):
        speech_references.save(role, "ru", wav(), "Образец русской речи.")
    job = service.render(w, draft["id"], model="f5-tts-russian", start_worker=False)
    spec = job["params"]["model_spec"]
    assert spec["engine"] == "f5" and spec["languages"] == ["ru"]
    assert set(spec["references"]) == {"host", "guest"}
    assert all((w.path / ref["path"]).is_file() for ref in spec["references"].values())


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


def test_f5_adapter_uses_frozen_local_references_without_asr(tmp_path, monkeypatch):
    import socket
    import sys
    from types import ModuleType, SimpleNamespace

    import numpy as np

    from brofessor.infrastructure.speech.engines import _F5

    for role, value in (("host", 8192), ("guest", -8192)):
        speech_references.save(role, "en", wav(value), f"Exact {role} transcript.")
    project = tmp_path / "project"
    frozen = speech_references.freeze(project, speech_references.selected("en"))
    spec = speech_models.get("f5-tts")
    spec["settings"].update(nfe_step=12, speed=0.85)
    spec["model_config"]["dim"] = 512
    spec["references"] = speech_references.resolve(project, frozen)
    speech_references.save("host", "en", wav(16384), "Later preference, not this job.")
    location, vocos = tmp_path / "pinned-model", tmp_path / "pinned-vocos"
    loads, reads, inference = {}, [], []
    model, vocoder, dit = object(), object(), object()

    def local_vocoder(component):
        assert component == spec["dependencies"][0]
        return vocos

    def load_model(architecture, config, checkpoint, **options):
        loads["model"] = (architecture, config, checkpoint, options)
        return model

    def load_vocoder(**options):
        loads["vocoder"] = options
        return vocoder

    def read_audio(path, **options):
        reads.append(path)
        assert options == {"dtype": "float32", "always_2d": True}
        with wave.open(path, "rb") as stream:
            samples = np.frombuffer(stream.readframes(stream.getnframes()), dtype="<i2")
            return samples.astype(np.float32).reshape(
                -1, stream.getnchannels()
            ) / 32768, stream.getframerate()

    def infer(reference, transcript, batches, loaded_model, loaded_vocoder, **options):
        assert loaded_model is model and loaded_vocoder is vocoder
        inference.append((reference, transcript, batches, options))
        yield np.full(4, float(reference[0].mean()), dtype=np.float32), 24000

    def forbidden(*args, **kwargs):
        pytest.fail("Frozen references and transcripts must not invoke ASR or network")

    upstream = ModuleType("f5_tts.infer.utils_infer")
    upstream.load_model, upstream.load_vocoder = load_model, load_vocoder
    upstream.infer_batch_process = infer
    upstream.preprocess_ref_audio_text = forbidden
    upstream.load_asr_model = forbidden
    modules = {
        "f5_tts": ModuleType("f5_tts"),
        "f5_tts.infer": ModuleType("f5_tts.infer"),
        "f5_tts.infer.utils_infer": upstream,
        "f5_tts.model": SimpleNamespace(DiT=dit),
        "torch": SimpleNamespace(
            backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda: True)),
            from_numpy=lambda audio: SimpleNamespace(
                unsqueeze=lambda axis: np.expand_dims(audio, axis)
            ),
            manual_seed=lambda seed: None,
        ),
        "soundfile": SimpleNamespace(read=read_audio),
    }
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setattr(speech_models, "installed_path", local_vocoder)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    engine = _F5(spec, location)
    requests = [
        ("host", "First explanation."),
        ("guest", "A qualified answer."),
        ("host", "A follow-up."),
    ]
    for role, text in requests:
        audio, rate = engine.synthesize(text, role, "en", None)
        assert rate == 24000
        np.testing.assert_allclose(audio, 0.25 if role == "host" else -0.25)
    assert loads["model"] == (
        dit,
        spec["model_config"],
        str(location / spec["checkpoint"]),
        {"vocab_file": str(location / spec["vocab"]), "device": "mps"},
    )
    assert loads["vocoder"] == {"is_local": True, "local_path": str(vocos), "device": "mps"}
    assert set(reads) == {spec["references"][role]["path"] for role in ("host", "guest")}
    for (reference, transcript, batches, options), (role, text) in zip(
        inference, requests, strict=True
    ):
        assert transcript == f"Exact {role} transcript."
        assert reference[1] == 24000 and " ".join(batches) == text
        assert options["device"] == "mps" and options["streaming"] is True
        assert options["nfe_step"] == spec["settings"]["nfe_step"]
        assert options["speed"] == spec["settings"]["speed"]


def test_legacy_voice_cli_remains_callable_but_is_hidden_from_regular_help(tmp_path):
    help_result = CliRunner().invoke(app, ["tts", "--help"])
    assert help_result.exit_code == 0 and "voice" not in help_result.output
    reference = tmp_path / "reference.wav"
    reference.write_bytes(wav())
    result = CliRunner().invoke(
        app,
        [
            "tts",
            "voice",
            "set",
            "host",
            "--language",
            "en",
            "--audio",
            str(reference),
            "--text",
            "Recorded reference.",
        ],
    )
    assert result.exit_code == 0, result.output
    assert speech_references.list_references("en")["host"]["text"] == "Recorded reference."
