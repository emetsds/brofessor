"""Offline renderer contract tests; fake speech is never a model-quality check."""

import wave
import xml.etree.ElementTree as ET
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
    from brofessor import speech_models

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


def test_rejects_unpinned_model_and_bad_plans(tmp_path, speech):
    with pytest.raises(ValueError, match="repo@commit"):
        media.render_audio(plan(), tmp_path / "a.wav", segment_dir=tmp_path, model="some/model")
    with pytest.raises(ValueError, match="language"):
        media.render_audio(plan("unknown"), tmp_path / "a.wav", segment_dir=tmp_path)
    with pytest.raises(ValueError, match="at least"):
        media.render_audio({"turns": []}, tmp_path / "a.wav", segment_dir=tmp_path)


def test_real_pptx_has_editable_text_table_notes_and_citations_without_external_tools(
    tmp_path, monkeypatch
):
    from pptx import Presentation

    monkeypatch.setenv("PATH", "")
    monkeypatch.setattr(
        media.subprocess, "run", lambda *a, **k: pytest.fail("PPTX must render in Python")
    )
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
        namespace = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
        paragraph_properties = next(
            p
            for p in ET.fromstring(slide).iter(f"{namespace}pPr")
            if p.find(f"{namespace}buChar") is not None
        )
        children = [element.tag for element in paragraph_properties]
        assert children.index(f"{namespace}buChar") < children.index(f"{namespace}defRPr")
    deck = Presentation(output)
    assert len(deck.slides) == 1
    assert deck.core_properties.title == "Editable evidence"
    table = next(shape.table for shape in deck.slides[0].shapes if shape.has_table)
    assert table.cell(1, 0).text == "Контракт"
    table.cell(1, 0).text = "Правка таблицы"
    deck.slides[0].notes_slide.notes_text_frame.text = "Правка заметки"
    edited = tmp_path / "edited.pptx"
    deck.save(edited)
    reopened = Presentation(edited)
    assert (
        next(s.table for s in reopened.slides[0].shapes if s.has_table).cell(1, 0).text
        == "Правка таблицы"
    )
    assert reopened.slides[0].notes_slide.notes_text_frame.text == "Правка заметки"


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
                {"title": "Second", "bullets": [], "notes": "No bullet points", "citations": []},
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
        media.render_slides({"slides": [{"title": "A title", "bullets": []}]}, output)
    assert output.read_bytes() == b"existing user artifact"
    assert list(tmp_path.iterdir()) == [output]


def test_rejects_dense_slides(tmp_path):
    with pytest.raises(ValueError, match="dense"):
        media.render_slides(
            {"slides": [{"title": "Too much", "bullets": ["x"] * 9}]}, tmp_path / "deck.pptx"
        )
