"""Offline renderer contract tests; fake speech is never a model-quality check."""

import wave
from pathlib import Path

import pytest

from brofessor.infrastructure.formats import audio as media


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
    # These cache/recovery cases also retain coverage of historical preset jobs.
    monkeypatch.setattr(
        media, "DEFAULT_TTS_MODEL", "mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-4bit"
    )
    monkeypatch.setattr(media, "_load_speech_model", lambda identity: object())
    monkeypatch.setattr(media, "_ffmpeg", lambda: None)

    def synth(model, text, voice, language, output, cancelled):
        calls.append((text, voice, language))
        with wave.open(str(output), "wb") as stream:
            stream.setparams((1, 2, 24000, 0, "NONE", "none"))
            stream.writeframes(b"\x01\x00" * 24000)

    monkeypatch.setattr(media, "_synthesize", synth)
    return calls


@pytest.fixture(autouse=True)
def isolate_render_lock(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "user-data"))


def test_cross_project_qwen_wait_skips_cpu_and_cache_hits_and_can_be_cancelled(tmp_path, speech):
    import subprocess
    import sys

    warm = tmp_path / "warm"
    media.render_audio(plan(), warm / "out.wav", segment_dir=warm / "segments")
    # A separate project process exits inside model loading, without running Python cleanup.
    holder = """
import os, select, sys
from pathlib import Path
from brofessor.infrastructure.formats import audio as media
def loading(spec):
    print("loading", flush=True)
    ready, _, _ = select.select([sys.stdin], [], [], 12)
    os._exit(0 if ready else 1)
media._load_speech_model = loading
root = Path(sys.argv[1])
media.render_audio({"turns": [{"speaker": "host", "text": "Первый"}]},
                   root / "audio.wav", segment_dir=root / "segments", model="qwen3-1.7b")
"""
    with subprocess.Popen(
        [sys.executable, "-c", holder, str(tmp_path / "first")],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    ) as process:
        try:
            assert process.stdout.readline().strip() == "loading"

            def must_not_wait(event):
                assert event["stage"] != "waiting_for_speech"

            cached = media.render_audio(
                plan(), warm / "again.wav", segment_dir=warm / "segments", progress=must_not_wait
            )
            assert all(segment["reused"] for segment in cached["segments"])
            media.render_audio(
                {"language": "ru", "turns": [{"speaker": "host", "text": "Факт."}]},
                tmp_path / "cpu.wav",
                segment_dir=tmp_path / "cpu",
                model="silero-cis-base",
                progress=must_not_wait,
            )
            before = list(speech)
            second = tmp_path / "second"
            events = []
            with pytest.raises(media.RenderCancelled):
                media.render_audio(
                    plan(),
                    second / "out.wav",
                    segment_dir=second / "segments",
                    progress=events.append,
                    cancelled=lambda: bool(events and events[-1]["stage"] == "waiting_for_speech"),
                )
            assert speech == before and not list((second / "segments").iterdir())

            def release_on_wait(event):
                if event["stage"] == "waiting_for_speech":
                    process.stdin.close()

            resumed = media.render_audio(
                plan(),
                second / "out.wav",
                segment_dir=second / "segments",
                progress=release_on_wait,
            )
            assert process.wait(timeout=3) == 0
            assert len(speech) == len(before) + 2 and Path(resumed["path"]).is_file()
        finally:
            process.stdin.close()


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


def test_stalled_speech_preserves_accepted_segments_and_previous_output(tmp_path, monkeypatch):
    monkeypatch.setattr(
        media, "DEFAULT_TTS_MODEL", "mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-4bit"
    )
    np = pytest.importorskip("numpy")
    original_synthesize = media._synthesize
    stalled = True
    calls = []

    class StalledModel:
        def synthesize(self, *args):
            # Nonzero background noise must not hide a stalled sentence.
            return np.r_[np.full(1000, 0.1), np.full(37000, 1e-4), np.full(1000, 0.1)], 1000

    def synthesize(model, text, voice, language, output, cancelled):
        calls.append(voice)
        if voice == "Vivian" and stalled:
            return original_synthesize(model, text, voice, language, output, cancelled)
        with wave.open(str(output), "wb") as stream:
            stream.setparams((1, 2, 24000, 0, "NONE", "none"))
            stream.writeframes(b"\x01\x00" * 24000)

    monkeypatch.setattr(media, "_load_speech_model", lambda spec: StalledModel())
    monkeypatch.setattr(media, "_synthesize", synthesize)
    monkeypatch.setattr(media, "_ffmpeg", lambda: None)
    output = tmp_path / "podcast.wav"
    output.write_bytes(b"previous accepted artifact")
    directory = tmp_path / "segments"
    with pytest.raises(media.MediaError, match=r"turn 2/2.*near-silence.*split"):
        media.render_audio(plan(), output, segment_dir=directory)
    assert output.read_bytes() == b"previous accepted artifact"
    assert not list(directory.glob("*.tmp.wav"))
    assert not output.with_suffix(".audio.json").exists()

    stalled = False
    result = media.render_audio(plan(), output, segment_dir=directory)
    assert [segment["reused"] for segment in result["segments"]] == [True, False]
    assert calls == ["Ryan", "Vivian", "Vivian"]


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


def test_editorial_removal_and_reordering_reuse_matching_segments(tmp_path, speech, monkeypatch):
    original = plan()
    original["turns"].append(
        {"speaker": "host", "text": "Keep the qualification.", "citations": ["u2"]}
    )
    directory = tmp_path / "segments"
    media.render_audio(original, tmp_path / "original.wav", segment_dir=directory)
    edited = {**original, "turns": [original["turns"][2], original["turns"][1]]}
    monkeypatch.setattr(media, "_load_speech_model", lambda *a: pytest.fail("Must reuse audio"))
    result = media.render_audio(edited, tmp_path / "edited.wav", segment_dir=directory)
    assert all(segment["reused"] for segment in result["segments"])
    assert result["duration_seconds"] == 2.25
    assert [segment["speaker"] for segment in result["segments"]] == ["host", "guest"]
    assert len(speech) == 3


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
    from brofessor.infrastructure.speech import catalogue as speech_models

    directory = tmp_path / "segments"
    media.render_audio(plan(), tmp_path / "a.wav", segment_dir=directory)
    revision = "mlx-community/another-CustomVoice@" + "a" * 40
    result = media.render_audio(plan(), tmp_path / "b.wav", segment_dir=directory, model=revision)
    assert all(not item["reused"] for item in result["segments"])
    models = [dict(item) for item in speech_models.CATALOG]
    models[0]["voices"] = {"host": "Aiden", "guest": "Vivian"}
    monkeypatch.setattr(speech_models, "CATALOG", models)
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


@pytest.mark.parametrize("failure", ["nonzero", "timeout", "cancel"])
def test_failed_mp3_publication_preserves_existing_file_and_reuses_completed_audio(
    tmp_path, speech, monkeypatch, failure
):
    import subprocess
    from types import SimpleNamespace

    output = tmp_path / "podcast.mp3"
    output.write_bytes(b"previous complete MP3")
    cancelled = False
    temporary_files = []
    monkeypatch.setattr(media, "_ffmpeg", lambda: "fake-ffmpeg")

    def encode(args, **kwargs):
        nonlocal cancelled
        target = Path(args[-1])
        temporary_files.append(target)
        target.write_bytes(b"partial new MP3")
        if failure == "timeout":
            raise subprocess.TimeoutExpired(args, kwargs["timeout"])
        if failure == "cancel":
            cancelled = True
        return SimpleNamespace(
            returncode=1 if failure == "nonzero" else 0, stderr="encoding failed"
        )

    monkeypatch.setattr(media.subprocess, "run", encode)
    error = {
        "nonzero": media.MediaError,
        "timeout": subprocess.TimeoutExpired,
        "cancel": media.RenderCancelled,
    }[failure]
    with pytest.raises(error):
        media.render_audio(
            plan(), output, segment_dir=tmp_path / "segments", cancelled=lambda: cancelled
        )
    assert output.read_bytes() == b"previous complete MP3"
    assert temporary_files and all(not path.exists() for path in temporary_files)
    assert not output.with_suffix(".audio.json").exists()
    completed_calls = list(speech)

    def successful_encode(args, **kwargs):
        Path(args[-1]).write_bytes(b"complete replacement MP3")
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(media.subprocess, "run", successful_encode)
    result = media.render_audio(plan(), output, segment_dir=tmp_path / "segments")
    assert output.read_bytes() == b"complete replacement MP3"
    assert all(segment["reused"] for segment in result["segments"])
    assert speech == completed_calls
    assert Path(result["path"]) == output and output.with_suffix(".audio.json").is_file()


def test_rejects_unpinned_model_and_bad_plans(tmp_path, speech):
    with pytest.raises(ValueError, match="repo@commit"):
        media.render_audio(plan(), tmp_path / "a.wav", segment_dir=tmp_path, model="some/model")
    with pytest.raises(ValueError, match="language"):
        media.render_audio(plan("unknown"), tmp_path / "a.wav", segment_dir=tmp_path)
    with pytest.raises(ValueError, match="at least"):
        media.render_audio({"turns": []}, tmp_path / "a.wav", segment_dir=tmp_path)


def test_slide_order_unicode_and_original_notes_are_preserved(tmp_path):
    from pptx import Presentation

    output = media.render_slides(
        {
            "title": "Пример & evidence",
            "language": "en",
            "slides": [
                {
                    "title": "First <result>",
                    "bullets": ["A & B", "Русский текст"],
                    "notes": "Paragraph one.\n\nВторой абзац.",
                    "citations": ["source:1", "source:2"],
                },
                {
                    "title": "Second",
                    "bullets": [],
                    "notes": "No bullet points",
                    "citations": ["source:2"],
                },
            ],
        },
        tmp_path / "ordered.pptx",
    )
    deck = Presentation(output)
    assert len(deck.slides) == 2
    texts = [[s.text for s in slide.shapes if s.has_text_frame] for slide in deck.slides]
    assert "First <result>" in texts[0] and "Second" in texts[1]
    assert any("A & B" in text and "Русский текст" in text for text in texts[0])
    notes = deck.slides[0].notes_slide.notes_text_frame.text
    assert "Paragraph one.\n\nВторой абзац." in notes
    assert "source:1" in notes and "source:2" in notes


def test_failed_save_preserves_existing_deck_and_removes_temporary_file(tmp_path, monkeypatch):
    from pptx.presentation import Presentation

    output = tmp_path / "deck.pptx"
    output.write_bytes(b"existing user artifact")

    def fail_save(self, target):
        Path(target).write_bytes(b"incomplete output")
        raise OSError("Synthetic disk error")

    monkeypatch.setattr(Presentation, "save", fail_save)
    with pytest.raises(OSError, match="Synthetic disk error"):
        media.render_slides(
            {
                "title": "Deck",
                "language": "en",
                "slides": [{"title": "A title", "bullets": [], "notes": "", "citations": ["u:1"]}],
            },
            output,
        )
    assert output.read_bytes() == b"existing user artifact"
    assert list(tmp_path.iterdir()) == [output]


def test_rejects_dense_slides(tmp_path):
    with pytest.raises(ValueError, match="dense"):
        media.render_slides(
            {
                "title": "Deck",
                "language": "en",
                "slides": [
                    {
                        "title": "Too much",
                        "bullets": ["A detailed explanation. " * 40] * 6,
                        "notes": "",
                        "citations": ["u:1"],
                    }
                ],
            },
            tmp_path / "deck.pptx",
        )
