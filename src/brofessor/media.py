"""Shared local rendering services. No frontend or provider-runner dependencies."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import wave
from collections.abc import Callable
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE, PP_ALIGN
from pptx.oxml.xmlchemy import OxmlElement
from pptx.util import Inches, Pt

from . import speech
from .speech import SpeechCancelled as RenderCancelled, SpeechError as MediaError

DEFAULT_TTS_MODEL = "mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-4bit"
DEFAULT_TTS_REVISION = "08c72cad5e2fd0f41730c8bd1f28149585e46361"
VOICES = {"host": "Ryan", "guest": "Vivian"}
LANGUAGES = {"ru": "Russian", "en": "English"}
SPEECH_SETTINGS = {"temperature": 0.7, "max_tokens": 1500, "seed": 42}
RENDERER_VERSION = "1"


def _check_cancelled(cancelled: Callable[[], bool] | None) -> None:
    if cancelled and cancelled():
        raise RenderCancelled("Rendering cancelled; completed segments are preserved")


def _atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _strings(value: object, label: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{label} must be a list of strings")
    return value


def _slide_text(slide, text: str, bounds: tuple, size: int, color: str, *, bold=False):
    frame = slide.shapes.add_textbox(*(Inches(value) for value in bounds)).text_frame
    frame.word_wrap = True
    frame.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
    frame.margin_left = frame.margin_right = frame.margin_top = frame.margin_bottom = 0
    frame.text = text
    for paragraph in frame.paragraphs:
        paragraph.font.name = "Arial"
        paragraph.font.size = Pt(size)
        paragraph.font.bold = bold
        paragraph.font.color.rgb = RGBColor.from_string(color)
    return frame


def _slide_deck(plan: dict):
    deck = Presentation()
    deck.slide_width, deck.slide_height = Inches(13.333333), Inches(7.5)
    deck.core_properties.author = "brofessor"
    deck.core_properties.title = plan.get("title") or "brofessor"
    deck.core_properties.subject = "Source-grounded editable presentation"
    deck.core_properties.language = "ru-RU" if plan.get("language") == "ru" else "en-US"
    ink, accent, muted = "142B39", "008773", "526772"
    for number, item in enumerate(plan["slides"], 1):
        slide = deck.slides.add_slide(deck.slide_layouts[6])
        slide.background.fill.solid()
        slide.background.fill.fore_color.rgb = RGBColor.from_string("F8FAFA")
        stripe = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, Inches(0.17), Inches(7.5))
        stripe.fill.solid()
        stripe.fill.fore_color.rgb = RGBColor.from_string(accent)
        stripe.line.fill.background()
        title_size = 24 if len(item["title"]) > 90 else 29
        title = _slide_text(slide, item["title"], (0.6, 0.48, 12, 1), title_size, ink, bold=True)
        title.vertical_anchor = MSO_ANCHOR.MIDDLE
        table = item.get("table")
        bullets = item.get("bullets", [])
        if bullets:
            body = _slide_text(
                slide, "\n".join(bullets), (0.7, 1.72, 11.9, 1.7 if table else 4.42), 23, ink
            )
            for paragraph in body.paragraphs:
                paragraph.space_after = Pt(18)
                # Native list markers need OOXML; python-pptx has no public bullet setter.
                properties = paragraph._p.get_or_add_pPr()
                properties.set("marL", str(Inches(0.25)))
                properties.set("indent", str(-Inches(0.25)))
                marker = OxmlElement("a:buChar")
                marker.set("char", "•")
                properties.insert_element_before(marker, "a:tabLst", "a:defRPr", "a:extLst")
        if table:
            rows = [table["headers"], *table["rows"]]
            shape = slide.shapes.add_table(
                len(rows),
                len(rows[0]),
                Inches(0.7),
                Inches(3.6 if bullets else 1.85),
                Inches(11.9),
                Inches(2.45 if bullets else 4.2),
            )
            for row_index, values in enumerate(rows):
                for column_index, value in enumerate(values):
                    cell = shape.table.cell(row_index, column_index)
                    cell.text = value
                    cell.fill.solid()
                    cell.fill.fore_color.rgb = RGBColor.from_string(
                        "E5F0EE" if row_index == 0 else "FFFFFF"
                    )
                    cell.margin_left = cell.margin_right = Inches(0.12)
                    cell.margin_top = cell.margin_bottom = Inches(0.08)
                    cell.vertical_anchor = MSO_ANCHOR.MIDDLE
                    cell.text_frame.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
                    for paragraph in cell.text_frame.paragraphs:
                        paragraph.font.name = "Arial"
                        paragraph.font.size = Pt(14 if len(rows) > 4 or len(rows[0]) > 3 else 18)
                        paragraph.font.bold = row_index == 0
                        paragraph.font.color.rgb = RGBColor.from_string(ink)
        citations = item.get("citations", [])
        _slide_text(slide, "  ·  ".join(citations) or "brofessor", (0.7, 6.7, 11.1, 0.4), 10, muted)
        page = _slide_text(slide, f"{number:02}", (12, 6.7, 0.6, 0.4), 12, accent)
        page.paragraphs[0].alignment = PP_ALIGN.RIGHT
        notes = [item.get("notes", "")]
        if citations:
            notes.append("Sources: " + "; ".join(citations))
        slide.notes_slide.notes_text_frame.text = "\n\n".join(part for part in notes if part)
    return deck


def render_slides(plan: dict, output: Path) -> Path:
    """Create native editable text/table objects and speaker notes in a PPTX."""
    slides = plan.get("slides")
    if not isinstance(slides, list) or not slides:
        raise ValueError("slides must contain at least one slide")
    for slide in slides:
        if not isinstance(slide, dict) or not isinstance(slide.get("title"), str):
            raise TypeError("Each slide needs a title")
        bullets = _strings(slide.get("bullets", []), "bullets")
        citations = _strings(slide.get("citations", []), "citations")
        if len(citations) > 6 or sum(map(len, citations)) > 600:
            raise ValueError("Keep slide citations concise and put details in speaker notes")
        if len(bullets) > 8 or sum(map(len, bullets)) > 1400 or len(slide["title"]) > 160:
            raise ValueError("Slide is too dense; split it into smaller slides")
        if table := slide.get("table"):
            headers = _strings(table.get("headers"), "table.headers")
            rows = table.get("rows")
            if not headers or not isinstance(rows, list) or len(rows) > 6:
                raise ValueError("Tables require headers and at most six rows")
            if len(headers) > 5 or (bullets and len(bullets) > 2):
                raise ValueError("Split dense table slides before rendering")
            for row in rows:
                if len(_strings(row, "table row")) != len(headers):
                    raise ValueError("Every table row must match its headers")
            cell_limit = 100 if len(headers) <= 3 else 55
            if any(len(cell) > cell_limit for row in [headers, *rows] for cell in row):
                raise ValueError("Table cells are too dense; shorten or split the table")
            if bullets and (len(rows) > 3 or sum(map(len, bullets)) > 280):
                raise ValueError("Split table and commentary across slides")
    output = Path(output).resolve()
    if output.suffix.lower() != ".pptx":
        raise ValueError("Slide output must have a .pptx suffix")
    output.parent.mkdir(parents=True, exist_ok=True)
    deck = _slide_deck(plan)
    fd, name = tempfile.mkstemp(prefix=f".{output.stem}.", suffix=".pptx", dir=output.parent)
    os.close(fd)
    temporary = Path(name)
    try:
        deck.save(temporary)
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    return output


def _model_identity(model: str | dict | None) -> dict:
    from .speech_models import get

    model = model or DEFAULT_TTS_MODEL
    try:
        item = get(model)
        if "repo" in item:
            return {"repo": item["repo"], "revision": item["revision"]}
        return {"id": item["id"], "revision": item["revision"]}
    except ValueError:
        pass
    if model == DEFAULT_TTS_MODEL:
        return {"repo": model, "revision": DEFAULT_TTS_REVISION}
    if "@" in model:
        repo, revision = model.rsplit("@", 1)
        if not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise ValueError("Use a complete 40-character model revision after @")
        return {"repo": repo, "revision": revision}
    local = Path(model).expanduser()
    if local.is_dir() and (local / "config.json").is_file():
        files = sorted(local.rglob("*"))
        fingerprint = [
            (str(p.relative_to(local)), p.stat().st_size, p.stat().st_mtime_ns)
            for p in files
            if p.is_file()
        ]
        return {"path": str(local.resolve()), "files": fingerprint}
    raise ValueError("Use the default model, repo@commit-sha, or a local model directory")


def _load_speech_model(spec: dict):
    from .speech_models import cache_directory, installed_path, snapshot

    try:
        if "download_bytes" in spec:
            location = installed_path(spec)
            if location is None:
                raise MediaError(
                    f"Download this voice model first: brofessor tts download {spec['id']} --wait"
                )
        else:
            # Older jobs and the explicit repo@revision/local-directory API remain usable.
            location = Path(spec["path"]) if "path" in spec else snapshot(spec)
            if not (location / "config.json").is_file():
                from huggingface_hub import snapshot_download

                location = Path(
                    snapshot_download(
                        spec["repo"],
                        revision=spec["revision"],
                        token=False,
                        cache_dir=cache_directory(),
                        allow_patterns=["*.json", "*.txt", "*.safetensors", "speech_tokenizer/*"],
                    )
                )
        return speech.load(spec, location)
    except MediaError:
        raise
    except Exception as error:
        raise MediaError(f"Cannot load local speech model: {error}") from error


def _synthesize(model, text, voice, language, output, cancelled) -> None:
    import numpy as np
    import soundfile as sf

    audio, sample_rate = model.synthesize(text, voice, language, cancelled)
    audio = np.asarray(audio, dtype=np.float32).reshape(-1)
    if not len(audio) or not np.isfinite(audio).all() or np.max(np.abs(audio)) < 1e-5:
        raise MediaError("Speech model returned empty, non-finite or silent audio")
    peak = float(np.max(np.abs(audio)))
    if peak > 0.98:
        audio *= 0.98 / peak
    sf.write(str(output), audio, sample_rate, format="WAV", subtype="PCM_16")


def _wav_info(path: Path) -> dict:
    with wave.open(str(path), "rb") as stream:
        if stream.getnframes() == 0 or stream.getsampwidth() != 2:
            raise MediaError(f"Invalid PCM16 segment: {path.name}")
        return {
            "sample_rate": stream.getframerate(),
            "channels": stream.getnchannels(),
            "frames": stream.getnframes(),
            "duration_seconds": stream.getnframes() / stream.getframerate(),
        }


def _segment_valid(path: Path, metadata: Path, key: str) -> bool:
    try:
        saved = json.loads(metadata.read_text(encoding="utf-8"))
        return (
            saved["key"] == key
            and saved["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
            and _wav_info(path)["frames"] > 0
        )
    except (OSError, ValueError, TypeError, KeyError, wave.Error, MediaError, EOFError):
        return False


def _ffmpeg() -> str | None:
    executable = shutil.which("ffmpeg")
    if executable:
        return executable
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError):
        return None


def render_audio(
    plan: dict,
    output: Path,
    *,
    segment_dir: Path,
    model: str | None = None,
    model_spec: dict | None = None,
    cancelled: Callable[[], bool] | None = None,
    progress: Callable[[dict], None] | None = None,
) -> dict:
    """Render a RU/EN dialogue with stock voices and content-addressed checkpoints.

    The first uncached invocation downloads the explicitly selected model from Hugging
    Face. Inference is local. No reference recordings or voice cloning are used.
    Output is always accompanied by WAV. MP3 is created when FFmpeg is available.
    """
    from .speech_models import get

    try:
        spec = get(model_spec or model or DEFAULT_TTS_MODEL)
    except ValueError:
        spec = _model_identity(model)
    spec.setdefault("engine", "qwen3-mlx")
    spec.setdefault("settings", dict(SPEECH_SETTINGS))
    spec.setdefault("voices", dict(VOICES))
    spec.setdefault("languages", list(LANGUAGES))
    voices = spec["voices"]
    language = plan.get("language", "ru")
    if language not in LANGUAGES:
        raise ValueError("Speech language must be ru or en")
    if language not in spec["languages"]:
        raise ValueError(f"Selected speech model does not support {language}")
    turns = plan.get("turns")
    if not isinstance(turns, list) or not turns:
        raise ValueError("Podcast requires at least one turn")
    for turn in turns:
        if not isinstance(turn, dict) or turn.get("speaker") not in voices:
            raise ValueError("Each turn needs a host or guest speaker")
        if not isinstance(turn.get("text"), str) or not turn["text"].strip():
            raise ValueError("Each turn needs nonempty text")
        if len(turn["text"]) > 1000:
            raise ValueError("Split speech turns longer than 1000 characters before rendering")
        speech.validate_text(spec, turn["text"])
    output = Path(output).resolve()
    if output.suffix.lower() not in {".wav", ".mp3"}:
        raise ValueError("Audio output must have a .wav or .mp3 suffix")
    identity = _model_identity(spec) if "id" in spec else _model_identity(model)
    segment_dir = Path(segment_dir).resolve()
    segment_dir.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    runtime = speech.runtime(spec)
    started = time.monotonic()
    loaded_model = None
    segments = []
    for index, turn in enumerate(turns):
        _check_cancelled(cancelled)
        settings = {
            "text": turn["text"],
            "voice": voices[turn["speaker"]],
            "language": language,
            "model": identity,
            "settings": spec["settings"],
            "renderer": RENDERER_VERSION,
            "runtime": runtime,
        }
        key = hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()
        target, metadata = segment_dir / f"{key}.wav", segment_dir / f"{key}.json"
        reused = _segment_valid(target, metadata, key)
        if not reused:
            if progress:
                progress(
                    {
                        "stage": "speech",
                        "completed": index,
                        "total": len(turns),
                        "speaker": turn["speaker"],
                        "reused": False,
                    }
                )
            if loaded_model is None:
                loaded_model = _load_speech_model(spec)
            temporary = target.with_suffix(".tmp.wav")
            try:
                try:
                    _synthesize(
                        loaded_model,
                        turn["text"],
                        settings["voice"],
                        language,
                        temporary,
                        cancelled,
                    )
                except RenderCancelled:
                    raise
                except MediaError as exc:
                    raise MediaError(
                        f"Speech turn {index + 1}/{len(turns)} "
                        f"(index {index}, {turn['speaker']}): {exc}"
                    ) from exc
                _check_cancelled(cancelled)
                info = _wav_info(temporary)
                temporary.replace(target)
                _atomic_json(
                    metadata,
                    {
                        "key": key,
                        **settings,
                        **info,
                        "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                    },
                )
            finally:
                temporary.unlink(missing_ok=True)
        segments.append(
            {
                "index": index,
                "path": str(target),
                "key": key,
                "speaker": turn["speaker"],
                "voice": settings["voice"],
                "reused": reused,
                **_wav_info(target),
            }
        )
        if progress:
            progress(
                {"stage": "speech", "completed": index + 1, "total": len(turns), "reused": reused}
            )
    _check_cancelled(cancelled)
    wav_path = output.with_suffix(".wav")
    temporary = wav_path.with_name(f".{wav_path.stem}.{os.getpid()}.tmp.wav")
    try:
        with wave.open(str(temporary), "wb") as dest:
            first = segments[0]
            dest.setparams((first["channels"], 2, first["sample_rate"], 0, "NONE", "none"))
            silence = bytes(int(first["sample_rate"] * 0.25) * first["channels"] * 2)
            for index, segment in enumerate(segments):
                _check_cancelled(cancelled)
                if (segment["sample_rate"], segment["channels"]) != (
                    first["sample_rate"],
                    first["channels"],
                ):
                    raise MediaError("Audio segments have incompatible sample rates or channels")
                if index:
                    dest.writeframes(silence)
                with wave.open(segment["path"], "rb") as source:
                    while frames := source.readframes(65536):
                        dest.writeframes(frames)
        temporary.replace(wav_path)
    finally:
        temporary.unlink(missing_ok=True)
    mp3_path = output.with_suffix(".mp3")
    ffmpeg = _ffmpeg()
    warning = None
    if ffmpeg:
        _check_cancelled(cancelled)
        with tempfile.TemporaryDirectory(prefix="brofessor-mp3-", dir=output.parent) as directory:
            encoded = Path(directory) / "audio.mp3"
            process = subprocess.run(
                [
                    ffmpeg,
                    "-nostdin",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-i",
                    str(wav_path),
                    "-codec:a",
                    "libmp3lame",
                    "-b:a",
                    "160k",
                    str(encoded),
                ],
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
            )
            if process.returncode:
                raise MediaError(f"MP3 encoding failed: {process.stderr[-1000:]}")
            _check_cancelled(cancelled)
            encoded.replace(mp3_path)
    else:
        warning = "FFmpeg unavailable: WAV created, MP3 unavailable"
    result = {
        "path": str(mp3_path if ffmpeg and output.suffix.lower() == ".mp3" else wav_path),
        "wav_path": str(wav_path),
        "mp3_path": str(mp3_path) if ffmpeg else None,
        **_wav_info(wav_path),
        "segments": segments,
        "model": identity,
        "voices": voices,
        "engine": spec["engine"],
        "runtime": runtime,
        "warning": warning,
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }
    _atomic_json(output.with_suffix(".audio.json"), result)
    return result
