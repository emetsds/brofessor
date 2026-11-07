"""Shared local rendering services. No frontend or provider-runner dependencies."""

from __future__ import annotations

import fcntl
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
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Final

from brofessor.contracts.content import ContentLanguage, Speaker
from brofessor.contracts.jobs import StageId
from brofessor.infrastructure.formats.contracts import AudioExtension
from brofessor.infrastructure.speech import engines as speech
from brofessor.infrastructure.speech.catalogue import DEFAULT_ID
from brofessor.infrastructure.speech.contracts import QWEN_SPEECH_LOCK_FILENAME, SpeechEngine
from brofessor.infrastructure.speech.engines import SpeechCancelled as RenderCancelled
from brofessor.infrastructure.speech.engines import SpeechError as MediaError

AUDIO_METADATA_SUFFIX: Final = ".audio.json"
TEMPORARY_WAV_SUFFIX: Final = ".tmp.wav"

DEFAULT_TTS_MODEL = DEFAULT_ID
# Fallbacks for historical CustomVoice jobs without a full model snapshot.
VOICES = {Speaker.HOST: "Ryan", Speaker.GUEST: "Vivian"}
LANGUAGES = {ContentLanguage.RU: "Russian", ContentLanguage.EN: "English"}
SPEECH_SETTINGS = {"temperature": 0.7, "max_tokens": 1500, "seed": 42}
RENDERER_VERSION = "1"


def _check_cancelled(cancelled: Callable[[], bool] | None) -> None:
    if cancelled and cancelled():
        raise RenderCancelled("Rendering cancelled; completed segments are preserved")


def _atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def render_slides(plan: dict, output: Path, *, source_labels=None) -> Path:
    """Shared entry point; slide layout is independent of speech rendering."""
    from brofessor.infrastructure.formats.slides import render

    return render(plan, output, source_labels=source_labels)


def _model_identity(model: str | dict | None) -> dict:
    from brofessor.infrastructure.speech.catalogue import get

    model = model or DEFAULT_TTS_MODEL
    try:
        item = get(model)
        if "repo" in item:
            identity = {"repo": item["repo"], "revision": item["revision"]}
            if item.get("model_config"):
                identity["config"] = item["model_config"]
            if item.get("dependencies"):
                identity["dependencies"] = [
                    {"repo": d["repo"], "revision": d["revision"]} for d in item["dependencies"]
                ]
            return identity
        return {"id": item["id"], "revision": item["revision"]}
    except ValueError:
        pass
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
    from brofessor.infrastructure.speech.catalogue import cache_directory, installed_path, snapshot

    try:
        if "download_bytes" in spec:
            location = installed_path(spec)
            if location is None:
                raise MediaError(
                    f"Download this voice model first: brofessor tts download {spec['id']} --wait"
                )
        else:
            # Compatibility for saved jobs without a catalog snapshot.
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

    audio, sample_rate = model.synthesize(text, voice, language, cancelled)
    audio = np.asarray(audio, dtype=np.float32).reshape(-1)
    if not len(audio) or not np.isfinite(audio).all() or np.max(np.abs(audio)) < 1e-5:
        raise MediaError("Speech model returned empty, non-finite or silent audio")
    # A Qwen segment contained 36 seconds of near-silence inside a spoken sentence.
    # Reject a stalled turn before it becomes an accepted checkpoint; do not trim it.
    frame_size = max(1, round(sample_rate * 0.02))
    frames = audio[: len(audio) // frame_size * frame_size].reshape(-1, frame_size)
    quiet = np.mean(frames * frames, axis=1) < 1e-6  # -60 dBFS, 20 ms windows
    edges = np.flatnonzero(np.diff(np.r_[False, quiet, False]))
    if np.any((edges[1::2] - edges[::2]) * frame_size / sample_rate >= 10):
        raise MediaError(
            "Speech contains at least 10 seconds of near-silence; split or revise this turn"
        )
    peak = float(np.max(np.abs(audio)))
    if peak > 0.98:
        audio *= 0.98 / peak
    import soundfile as sf

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


def _segment_valid(path: Path, metadata: Path, key: str, *, prepared=False) -> bool:
    try:
        saved = json.loads(metadata.read_text(encoding="utf-8"))
        return (
            saved["key"] == key
            and (
                not prepared
                or (isinstance(saved.get("synthesis_text"), str) and bool(saved["synthesis_text"]))
            )
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


@contextmanager
def _qwen_lock(cancelled, progress, completed, total):
    """Share Metal memory between project workers only during Qwen synthesis."""
    from brofessor.infrastructure.storage.preferences import data_directory

    directory = data_directory()
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / QWEN_SPEECH_LOCK_FILENAME).open("a") as handle:
        waiting = False
        while True:
            _check_cancelled(cancelled)
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if progress and not waiting:
                    progress(
                        {
                            "stage": StageId.WAITING_FOR_SPEECH,
                            "completed": completed,
                            "total": total,
                        }
                    )
                    waiting = True
                time.sleep(0.25)
        # Closing the descriptor releases the lock, including after an exception.
        yield


def _render_segments(
    turns, segment_dir, spec, language, identity, runtime, cancelled, progress, resources
):
    loaded_model = None
    needs_lock = spec["engine"] in (SpeechEngine.QWEN_BASE, SpeechEngine.QWEN_CUSTOM)
    needs_model_guard = True
    segments = []
    for index, turn in enumerate(turns):
        _check_cancelled(cancelled)
        settings = {
            "text": turn["text"],
            "voice": spec["voices"][turn["speaker"]],
            "language": language,
            "model": identity,
            "settings": spec["settings"],
            "renderer": RENDERER_VERSION,
            "runtime": runtime,
        }
        if spec.get("references"):
            ref = spec["references"][turn["speaker"]]
            settings["reference"] = {key: ref[key] for key in ("sha256", "text")}
        if spec.get("text_preparation"):
            settings["text_preparation"] = spec["text_preparation"]
        key = hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()
        target, metadata = segment_dir / f"{key}.wav", segment_dir / f"{key}.json"
        prepared = bool(spec.get("text_preparation"))
        reused = _segment_valid(target, metadata, key, prepared=prepared)
        if not reused and needs_model_guard:
            from brofessor.infrastructure.storage.locks import models_lock

            resources.enter_context(models_lock(check=lambda: _check_cancelled(cancelled)))
            needs_model_guard = False
        if not reused and needs_lock:
            resources.enter_context(_qwen_lock(cancelled, progress, index, len(turns)))
            needs_lock = False
            # The holder may just have finished this segment while we waited.
            reused = _segment_valid(target, metadata, key, prepared=prepared)
        if not reused:
            if progress:
                progress(
                    {
                        "stage": StageId.SPEECH,
                        "completed": index,
                        "total": len(turns),
                        "speaker": turn["speaker"],
                        "reused": False,
                    }
                )
            if loaded_model is None:
                loaded_model = _load_speech_model(spec)
            temporary = target.with_suffix(TEMPORARY_WAV_SUFFIX)
            try:
                try:
                    synthesis_text = turn["text"]
                    if spec.get("text_preparation"):
                        synthesis_text = loaded_model.prepare_text(
                            synthesis_text, language, cancelled
                        )
                        _check_cancelled(cancelled)
                    _synthesize(
                        loaded_model,
                        synthesis_text,
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
                        **(
                            {"synthesis_text": synthesis_text}
                            if spec.get("text_preparation")
                            else {}
                        ),
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
                **(
                    {"synthesis_text": json.loads(metadata.read_text())["synthesis_text"]}
                    if spec.get("text_preparation")
                    else {}
                ),
                **_wav_info(target),
            }
        )
        if progress:
            progress(
                {
                    "stage": StageId.SPEECH,
                    "completed": index + 1,
                    "total": len(turns),
                    "reused": reused,
                }
            )
    return segments


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
    """Protect cached segment reads through final packaging from concurrent cleanup."""
    from brofessor.infrastructure.storage.locks import audio_cache_lock

    directory = Path(segment_dir).resolve().parent
    directory.mkdir(parents=True, exist_ok=True)
    with audio_cache_lock(directory, check=lambda: _check_cancelled(cancelled)):
        return _render_audio(
            plan,
            output,
            segment_dir=segment_dir,
            model=model,
            model_spec=model_spec,
            cancelled=cancelled,
            progress=progress,
        )


def _render_audio(
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

    Catalog weights must be installed explicitly. Reference-based engines use the
    voice samples saved in the job snapshot; inference remains local.
    Output is always accompanied by WAV. MP3 is created when FFmpeg is available.
    """
    from brofessor.infrastructure.speech.catalogue import get

    try:
        spec = get(model_spec or model or DEFAULT_TTS_MODEL)
    except ValueError:
        spec = _model_identity(model)
    spec.setdefault("engine", SpeechEngine.QWEN_CUSTOM)
    spec.setdefault("settings", dict(SPEECH_SETTINGS))
    spec.setdefault("voices", dict(VOICES))
    spec.setdefault("languages", list(LANGUAGES))
    voices = spec["voices"]
    if spec.get("requires_reference") and not spec.get("references"):
        raise ValueError("Provide saved voice samples and transcripts before rendering")
    language = plan.get("language", ContentLanguage.RU)
    if language not in LANGUAGES:
        raise ValueError("Speech language must be ru or en")
    if language not in spec["languages"]:
        raise ValueError(f"Selected speech model does not support {language}")
    if spec.get("preset_references"):
        from brofessor.infrastructure.speech.references import preset_snapshot

        spec = preset_snapshot(spec, language)
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
    if output.suffix.lower() not in {AudioExtension.WAV, AudioExtension.MP3}:
        raise ValueError("Audio output must have a .wav or .mp3 suffix")
    identity = _model_identity(spec) if "id" in spec else _model_identity(model)
    segment_dir = Path(segment_dir).resolve()
    segment_dir.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    runtime = speech.runtime(spec)
    started = time.monotonic()
    with ExitStack() as resources:
        segments = _render_segments(
            turns, segment_dir, spec, language, identity, runtime, cancelled, progress, resources
        )
    _check_cancelled(cancelled)
    if progress:
        progress({"stage": StageId.AUDIO_PACKAGING})
    wav_path = output.with_suffix(AudioExtension.WAV)
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
    mp3_path = output.with_suffix(AudioExtension.MP3)
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
        "path": str(
            mp3_path if ffmpeg and output.suffix.lower() == AudioExtension.MP3 else wav_path
        ),
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
    _atomic_json(output.with_suffix(AUDIO_METADATA_SUFFIX), result)
    return result
