"""Shared local rendering services. No frontend or provider-runner dependencies."""

from __future__ import annotations

import hashlib
import importlib.metadata
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

DEFAULT_TTS_MODEL = "mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-4bit"
DEFAULT_TTS_REVISION = "08c72cad5e2fd0f41730c8bd1f28149585e46361"
VOICES = {"host": "Ryan", "guest": "Vivian"}
LANGUAGES = {"ru": "Russian", "en": "English"}
SPEECH_SETTINGS = {"temperature": 0.7, "max_tokens": 1500, "seed": 42}
RENDERER_VERSION = "1"


class MediaError(RuntimeError):
    """An unavailable renderer or unusable artifact, never synthetic success."""


class RenderCancelled(MediaError):
    """Rendering stopped, preserving only complete reusable segments."""


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
    node = shutil.which("node")
    renderer = Path(__file__).parent / "renderer" / "slides.mjs"
    if not renderer.is_file():
        renderer = Path(__file__).resolve().parents[2] / "renderer" / "slides.mjs"
    if not node or not renderer.is_file():
        raise MediaError("Install Node.js 20+ and run npm ci in the brofessor checkout")
    output = Path(output).resolve()
    if output.suffix.lower() != ".pptx":
        raise ValueError("Slide output must have a .pptx suffix")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.stem}.{os.getpid()}.tmp.pptx")
    try:
        result = subprocess.run(
            [node, str(renderer), str(temporary)],
            input=json.dumps(plan, ensure_ascii=False),
            text=True,
            capture_output=True,
            timeout=120,
            check=False,
        )
        if result.returncode:
            raise MediaError(f"PPTX rendering failed (run npm ci): {result.stderr[-2000:]}")
        if not temporary.is_file() or temporary.stat().st_size < 100:
            raise MediaError("PPTX renderer did not create an artifact")
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    return output


def _model_identity(model: str | None) -> dict:
    model = model or DEFAULT_TTS_MODEL
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


def _load_speech_model(identity: dict):
    try:
        from huggingface_hub import snapshot_download
        from mlx_audio.tts.utils import load_model
    except ImportError as exc:
        raise MediaError(
            f"Local speech requires Apple Silicon, Metal and uv sync --extra speech: {exc}"
        ) from exc
    try:
        location = identity.get("path") or snapshot_download(
            identity["repo"],
            revision=identity["revision"],
            token=False,
            allow_patterns=["*.json", "*.txt", "*.safetensors", "speech_tokenizer/*"],
        )
        model = load_model(location)
        if not callable(getattr(model, "generate_custom_voice", None)):
            raise MediaError("Speech model must support Qwen3 CustomVoice preset voices")
        return model
    except MediaError:
        raise
    except Exception as exc:
        raise MediaError(f"Cannot load local Qwen3-TTS model: {exc}") from exc


def _synthesize(
    model, text: str, voice: str, language: str, output: Path, cancelled: Callable[[], bool] | None
) -> None:
    import mlx.core as mx
    import numpy as np
    import soundfile as sf

    mx.random.seed(SPEECH_SETTINGS["seed"])
    chunks = []
    tokens = 0
    for result in model.generate_custom_voice(
        text=text,
        speaker=voice,
        language=language,
        stream=True,
        streaming_interval=1.0,
        temperature=SPEECH_SETTINGS["temperature"],
        max_tokens=SPEECH_SETTINGS["max_tokens"],
    ):
        _check_cancelled(cancelled)
        tokens += result.token_count
        chunks.append(np.asarray(result.audio, dtype=np.float32).reshape(-1))
    if tokens >= SPEECH_SETTINGS["max_tokens"]:
        raise MediaError("Speech hit the generation limit; split or revise this turn")
    if not chunks:
        raise MediaError("Speech model returned no audio")
    audio = np.concatenate(chunks)
    if not len(audio) or not np.isfinite(audio).all() or np.max(np.abs(audio)) < 1e-5:
        raise MediaError("Speech model returned empty, non-finite or silent audio")
    # Only peak protection, never stretching audio to claim a target duration.
    peak = float(np.max(np.abs(audio)))
    if peak > 0.98:
        audio *= 0.98 / peak
    sf.write(str(output), audio, model.sample_rate, format="WAV", subtype="PCM_16")


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
    cancelled: Callable[[], bool] | None = None,
    progress: Callable[[dict], None] | None = None,
) -> dict:
    """Render a RU/EN dialogue with stock voices and content-addressed checkpoints.

    The first uncached invocation downloads the explicitly selected model from Hugging
    Face. Inference is local. No reference recordings or voice cloning are used.
    Output is always accompanied by WAV. MP3 is created when FFmpeg is available.
    """
    language = plan.get("language", "ru")
    if language not in LANGUAGES:
        raise ValueError("Speech language must be ru or en")
    turns = plan.get("turns")
    if not isinstance(turns, list) or not turns:
        raise ValueError("Podcast requires at least one turn")
    for turn in turns:
        if not isinstance(turn, dict) or turn.get("speaker") not in VOICES:
            raise ValueError("Each turn needs a host or guest speaker")
        if not isinstance(turn.get("text"), str) or not turn["text"].strip():
            raise ValueError("Each turn needs nonempty text")
        if len(turn["text"]) > 1000:
            raise ValueError("Split speech turns longer than 1000 characters before rendering")
    output = Path(output).resolve()
    if output.suffix.lower() not in {".wav", ".mp3"}:
        raise ValueError("Audio output must have a .wav or .mp3 suffix")
    identity = _model_identity(model)
    segment_dir = Path(segment_dir).resolve()
    segment_dir.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        runtime = importlib.metadata.version("mlx-audio")
    except importlib.metadata.PackageNotFoundError:
        runtime = "unavailable"
    started = time.monotonic()
    loaded_model = None
    segments = []
    for index, turn in enumerate(turns):
        _check_cancelled(cancelled)
        settings = {
            "text": turn["text"],
            "voice": VOICES[turn["speaker"]],
            "language": language,
            "model": identity,
            "settings": SPEECH_SETTINGS,
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
                loaded_model = _load_speech_model(identity)
            temporary = target.with_suffix(".tmp.wav")
            try:
                try:
                    _synthesize(
                        loaded_model,
                        turn["text"],
                        settings["voice"],
                        LANGUAGES[language],
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
        "voices": VOICES,
        "runtime": runtime,
        "warning": warning,
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }
    _atomic_json(output.with_suffix(".audio.json"), result)
    return result
