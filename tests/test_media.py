"""Offline renderer contract tests; fake speech is never a model-quality check."""

import shutil
import wave
import zipfile
from pathlib import Path

import pytest

from brofessor import media


def plan(language="en"):
    return {
        "title": "Evidence",
        "language": language,
        "turns": [
            {"speaker": "host", "text": "What does the source say?", "citations": ["u1"]},
            {"speaker": "guest", "text": "Keep facts separate from guesses.", "citations": ["u2"]},
        ],
    }


@pytest.fixture
def speech(monkeypatch):
    calls = []
    monkeypatch.setattr(media, "_load_speech_model", lambda identity: object())
    monkeypatch.setattr(media, "_ffmpeg", lambda: None)

    def synth(model, text, voice, language, output, cancelled):
        calls.append((text, voice, language))
        with wave.open(str(output), "wb") as stream:
            stream.setparams((1, 2, 24000, 0, "NONE", "none"))
            stream.writeframes(b"\x01\x00" * 24000)

    monkeypatch.setattr(media, "_synthesize", synth)
    return calls


def test_segments_resume_validate_and_measure_duration(tmp_path, speech, monkeypatch):
    directory = tmp_path / "segments"
    result = media.render_audio(plan(), tmp_path / "out.mp3", segment_dir=directory)
    assert result["duration_seconds"] == 2.25  # two actual WAV seconds plus a 250ms pause
    assert result["path"].endswith(".wav")
    assert result["mp3_path"] is None and result["warning"]
    assert [call[1] for call in speech] == ["Ryan", "Vivian"]
    assert all(not segment["reused"] for segment in result["segments"])
    monkeypatch.setattr(media, "_load_speech_model", lambda identity: pytest.fail("must reuse"))
    repeated = media.render_audio(plan(), tmp_path / "out.wav", segment_dir=directory)
    assert all(segment["reused"] for segment in repeated["segments"])
    assert len(speech) == 2


def test_changed_text_and_language_invalidate_cache(tmp_path, speech):
    directory = tmp_path / "segments"
    media.render_audio(plan(), tmp_path / "a.wav", segment_dir=directory)
    edited = plan()
    edited["turns"][1]["text"] += " Check the original."
    result = media.render_audio(edited, tmp_path / "b.wav", segment_dir=directory)
    assert [segment["reused"] for segment in result["segments"]] == [True, False]
    result = media.render_audio(plan("ru"), tmp_path / "c.wav", segment_dir=directory)
    assert all(not segment["reused"] for segment in result["segments"])
    assert len(speech) == 5


@pytest.mark.parametrize("component", ["wav", "json"])
def test_corrupt_segment_is_rendered_again(tmp_path, speech, component):
    directory = tmp_path / "segments"
    result = media.render_audio(plan(), tmp_path / "a.wav", segment_dir=directory)
    Path(result["segments"][0]["path"]).with_suffix(f".{component}").write_bytes(
        b"not audio" if component == "wav" else b"[]"
    )
    recovered = media.render_audio(plan(), tmp_path / "b.wav", segment_dir=directory)
    assert [segment["reused"] for segment in recovered["segments"]] == [False, True]
    assert len(speech) == 3


def test_model_and_voice_changes_invalidate_cache(tmp_path, speech, monkeypatch):
    directory = tmp_path / "segments"
    media.render_audio(plan(), tmp_path / "a.wav", segment_dir=directory)
    revision = "mlx-community/another-CustomVoice@" + "a" * 40
    result = media.render_audio(plan(), tmp_path / "b.wav", segment_dir=directory, model=revision)
    assert all(not item["reused"] for item in result["segments"])
    monkeypatch.setattr(media, "VOICES", {"host": "Aiden", "guest": "Vivian"})
    result = media.render_audio(plan(), tmp_path / "c.wav", segment_dir=directory)
    assert [item["reused"] for item in result["segments"]] == [False, True]


def test_partial_generation_never_becomes_checkpoint(tmp_path, speech, monkeypatch):
    directory = tmp_path / "segments"

    def interrupted(model, text, voice, language, output, cancelled):
        output.write_bytes(b"partial")
        raise media.RenderCancelled("interrupted")

    monkeypatch.setattr(media, "_synthesize", interrupted)
    with pytest.raises(media.RenderCancelled):
        media.render_audio(plan(), tmp_path / "a.wav", segment_dir=directory)
    assert not list(directory.iterdir())
    assert not (tmp_path / "a.wav").exists()


def test_generation_limit_identifies_turn_and_preserves_checkpoints(tmp_path, speech, monkeypatch):
    directory = tmp_path / "segments"
    original_synthesize = media._synthesize

    def limited(model, text, voice, language, output, cancelled):
        if voice == "Vivian":
            output.write_bytes(b"partial speech")
            raise media.MediaError("Speech hit the generation limit; split or revise this turn")
        original_synthesize(model, text, voice, language, output, cancelled)

    monkeypatch.setattr(media, "_synthesize", limited)
    with pytest.raises(media.MediaError, match=r"turn 2/2 \(index 1, guest\).*generation limit"):
        media.render_audio(plan(), tmp_path / "a.wav", segment_dir=directory)
    assert len(list(directory.glob("*.wav"))) == 1
    assert len(list(directory.glob("*.json"))) == 1
    assert not list(directory.glob("*.tmp.*"))
    assert not (tmp_path / "a.wav").exists()
    monkeypatch.setattr(media, "_synthesize", original_synthesize)
    result = media.render_audio(plan(), tmp_path / "b.wav", segment_dir=directory)
    assert [item["reused"] for item in result["segments"]] == [True, False]


def test_cancel_preserves_completed_segment(tmp_path, speech):
    directory = tmp_path / "segments"
    events = []
    with pytest.raises(media.RenderCancelled):
        media.render_audio(
            plan(),
            tmp_path / "cancelled.wav",
            segment_dir=directory,
            progress=events.append,
            cancelled=lambda: any(e["completed"] == 1 for e in events),
        )
    assert len(list(directory.glob("*.wav"))) == 1
    assert not (tmp_path / "cancelled.wav").exists()
    result = media.render_audio(plan(), tmp_path / "resumed.wav", segment_dir=directory)
    assert [segment["reused"] for segment in result["segments"]] == [True, False]


def test_rejects_unpinned_model_and_bad_plans(tmp_path, speech):
    with pytest.raises(ValueError, match="repo@commit"):
        media.render_audio(plan(), tmp_path / "a.wav", segment_dir=tmp_path, model="some/model")
    with pytest.raises(ValueError, match="language"):
        media.render_audio(plan("unknown"), tmp_path / "a.wav", segment_dir=tmp_path)
    with pytest.raises(ValueError, match="at least"):
        media.render_audio({"turns": []}, tmp_path / "a.wav", segment_dir=tmp_path)


def test_real_pptx_has_editable_text_table_notes_and_citations(tmp_path):
    checkout = Path(__file__).parents[1]
    if not shutil.which("node") or not (checkout / "node_modules/pptxgenjs").is_dir():
        pytest.skip("Run npm ci to exercise the real PPTX renderer")
    output = media.render_slides(
        {
            "title": "Editable evidence",
            "language": "ru",
            "slides": [
                {
                    "title": "Проверяемый вывод",
                    "bullets": ["Сохранить источник"],
                    "notes": "Проверить первоисточник перед выступлением",
                    "citations": ["source:p2"],
                    "table": {
                        "headers": ["Факт", "Основание"],
                        "rows": [["Контракт", "Исходный текст"]],
                    },
                },
            ],
        },
        tmp_path / "deck.pptx",
    )
    with zipfile.ZipFile(output) as archive:
        slide = archive.read("ppt/slides/slide1.xml").decode()
        notes = archive.read("ppt/notesSlides/notesSlide1.xml").decode()
        assert "Проверяемый вывод" in slide and "<a:tbl>" in slide
        assert "source:p2" in slide and "Проверить первоисточник" in notes
        assert "<p:pic>" not in slide  # text/table is not a screenshot


def test_rejects_dense_slides(tmp_path):
    with pytest.raises(ValueError, match="dense"):
        media.render_slides(
            {"slides": [{"title": "Too much", "bullets": ["x"] * 9}]}, tmp_path / "deck.pptx"
        )
