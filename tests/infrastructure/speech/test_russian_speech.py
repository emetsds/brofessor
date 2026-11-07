"""Russian pronunciation boundaries; no weights or network in this suite."""

import copy
import json
import sys
import wave
from types import SimpleNamespace

import pytest

from brofessor.infrastructure.formats import audio as media
from brofessor.infrastructure.speech import catalogue as speech_models
from brofessor.infrastructure.speech import engines as speech
from brofessor.infrastructure.speech.russian import KokoroRU, _TokenizerInputs, preserve_text


def test_download_materializes_pinned_helper_code_beside_its_data(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    spec = {
        "id": "local-helper",
        "repo": "test/helper",
        "revision": "a" * 40,
        "files": {"code/helper.py": 4, "code/data.json": 2},
        "download_bytes": 6,
        "local_code": ["code/helper.py"],
    }
    target = speech_models.snapshot(spec)
    (target / "code").mkdir(parents=True)
    blob = tmp_path / "blob"
    blob.write_bytes(b"pass")
    (target / "code/helper.py").symlink_to(blob)
    (target / "code/data.json").write_text("{}")
    assert speech_models.installed_path(spec) is None
    monkeypatch.setattr(
        speech_models, "_snapshot_download", lambda **kw: pytest.fail("Already downloaded")
    )
    speech_models.download(spec)
    assert speech_models.installed_path(spec) == target
    code = (target / "code/helper.py").resolve()
    assert code.read_bytes() == b"pass"
    assert (code.parent / "data.json").read_text() == "{}"


def test_automatic_stress_keeps_manual_marks_case_and_punctuation():
    source = "«Догов+ор» — ёлка; з+амок и замок. Катало́г!"
    prepared = preserve_text(source, "д+оговор елка з+амок и зам+ок катал+ог")
    assert prepared == "«Догов+ор» — ёлка; з+амок и зам+ок. Катал+ог!"
    assert preserve_text("Все ушли, всё готово.", "Вс+е ушл+и всё гот+ово.") == (
        "Вс+е ушл+и, всё гот+ово."
    )


@pytest.mark.parametrize("changed", ["Пропало слово.", "Заменили важное слово."])
def test_accentuator_cannot_drop_or_replace_words(changed):
    with pytest.raises(speech.SpeechError, match="changed words"):
        preserve_text("Здесь важное слово.", changed)


def test_ruaccent_onnx_token_types_survive_transformers_v5():
    np = pytest.importorskip("numpy")

    def tokenizer(*args, **kwargs):
        return {"input_ids": np.array([[1, 2]])}

    session = SimpleNamespace(get_inputs=lambda: [SimpleNamespace(name="token_type_ids")])
    result = _TokenizerInputs(tokenizer, session)("текст", return_tensors="np")
    assert result["token_type_ids"].tolist() == [[0, 0]]
    assert result["token_type_ids"].dtype == result["input_ids"].dtype


def test_prepared_text_is_auditable_and_reused_without_loading_models(tmp_path, monkeypatch):
    spec = speech_models.get("kokoro-ru")
    plan = {"language": "ru", "turns": [{"speaker": "host", "text": "Здесь замок."}]}
    original = copy.deepcopy(plan)
    calls = []

    def prepare(text, language, cancelled):
        return "Здесь з+амок."

    model = SimpleNamespace(prepare_text=prepare)
    monkeypatch.setattr(media, "_load_speech_model", lambda spec: model)
    monkeypatch.setattr(media, "_ffmpeg", lambda: None)

    def synthesize(model, text, voice, language, output, cancelled):
        calls.append(text)
        with wave.open(str(output), "wb") as stream:
            stream.setparams((1, 2, 24000, 0, "NONE", "none"))
            stream.writeframes(b"\x01\x00" * 24000)

    monkeypatch.setattr(media, "_synthesize", synthesize)

    def render():
        return media.render_audio(
            plan, tmp_path / "out.wav", segment_dir=tmp_path / "cache", model_spec=spec
        )

    first = render()
    assert calls == ["Здесь з+амок."] and plan == original
    assert first["segments"][0]["synthesis_text"] == "Здесь з+амок."
    metadata = json.loads(next((tmp_path / "cache").glob("*.json")).read_text())
    assert metadata["text"] == "Здесь замок."
    assert metadata["synthesis_text"] == "Здесь з+амок."
    assert metadata["text_preparation"] == spec["text_preparation"]
    monkeypatch.setattr(media, "_load_speech_model", lambda spec: pytest.fail("Must reuse"))
    assert render()["segments"][0]["reused"]
    assert len(calls) == 1
    monkeypatch.setattr(media, "_load_speech_model", lambda spec: model)
    spec["text_preparation"]["version"] = "next"
    assert not render()["segments"][0]["reused"]
    spec["dependencies"][0]["revision"] = "f" * 40
    changed = render()["segments"][0]
    assert not changed["reused"]
    # An otherwise intact WAV cannot stand in for lost pronunciation provenance.
    from pathlib import Path

    damaged = Path(changed["path"]).with_suffix(".json")
    data = json.loads(damaged.read_text())
    del data["synthesis_text"]
    damaged.write_text(json.dumps(data))
    assert not render()["segments"][0]["reused"]


@pytest.mark.parametrize("cancel", [True, False])
def test_preparation_failure_never_publishes_checkpoint_or_replaces_audio(
    tmp_path, monkeypatch, cancel
):
    spec = speech_models.get("kokoro-ru")
    output = tmp_path / "out.wav"
    output.write_bytes(b"previous audio")

    def prepare(*args):
        if cancel:
            raise speech.SpeechCancelled("cancelled")
        raise speech.SpeechError("RUAccent changed words")

    monkeypatch.setattr(
        media, "_load_speech_model", lambda spec: SimpleNamespace(prepare_text=prepare)
    )
    monkeypatch.setattr(media, "_synthesize", lambda *a: pytest.fail("Preparation failed"))
    with pytest.raises(speech.SpeechError, match="cancelled" if cancel else "turn 1/1"):
        media.render_audio(
            {"language": "ru", "turns": [{"speaker": "host", "text": "Замок."}]},
            output,
            segment_dir=tmp_path / "cache",
            model_spec=spec,
        )
    assert output.read_bytes() == b"previous audio"
    assert not list((tmp_path / "cache").iterdir())


def test_kokoro_passes_every_phoneme_and_rejects_unsupported_or_overlong_input(monkeypatch):
    np = pytest.importorskip("numpy")
    monkeypatch.setitem(sys.modules, "onnxruntime", SimpleNamespace())
    calls = []

    def run(outputs, inputs):
        calls.append(inputs)
        return [np.ones(100, dtype=np.float32)]

    engine = KokoroRU.__new__(KokoroRU)
    engine.spec = speech_models.get("kokoro-ru")
    engine.vocab = {"a": 1, "b": 2, " ": 3}
    engine.styles = {"dima": np.zeros((510, 256), dtype=np.float32)}
    engine.sessions = {"model_dima.onnx": SimpleNamespace(run=run)}
    engine.g2p = SimpleNamespace(phonemize=lambda text: "a b")
    audio, rate = engine.synthesize("Текст.", "dima", "ru", None)
    assert rate == 24000 and len(audio) == 100
    assert calls[0]["input_ids"].tolist() == [[0, 1, 3, 2, 0]]
    assert calls[0]["style"].shape == (1, 256)
    for ipa, message in [("a?", "cannot pronounce"), ("a" * 511, "510 phonemes")]:
        engine.g2p.phonemize = lambda text: ipa
        with pytest.raises(speech.SpeechError, match=message):
            engine.synthesize("Текст.", "dima", "ru", None)
    assert len(calls) == 1  # Never silently filter or truncate phonemes.


def test_native_silero_flags_are_frozen_without_changing_legacy_cis(monkeypatch, tmp_path):
    import contextlib

    calls = []
    model = SimpleNamespace(
        speakers=["aidar", "xenia", "ru_roman", "ru_zhadyra"],
        to=lambda device: None,
        apply_tts=lambda **kw: (
            calls.append(kw) or SimpleNamespace(cpu=lambda: SimpleNamespace(numpy=lambda: [0.1]))
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "torch",
        SimpleNamespace(
            set_num_threads=lambda n: None,
            device=lambda name: name,
            inference_mode=contextlib.nullcontext,
            package=SimpleNamespace(
                PackageImporter=lambda p: SimpleNamespace(load_pickle=lambda *a: model)
            ),
        ),
    )
    for name in ("silero-ru", "silero-cis-base"):
        spec = speech_models.get(name)
        engine = speech.load(spec, tmp_path)
        engine.synthesize("Догов+ор.", spec["voices"]["host"], "ru", None)
    assert calls[0] == {
        "text": "Догов+ор.",
        "speaker": "aidar",
        "sample_rate": 48000,
        "put_accent": True,
        "put_stress_homo": True,
        "put_yo": True,
        "put_yo_homo": True,
        "stress_single_vowel": True,
    }
    assert calls[1] == {"text": "Догов+ор.", "speaker": "ru_roman", "sample_rate": 48000}
