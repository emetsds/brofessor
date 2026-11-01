"""Local WAV voice samples and transcripts; immutable files, editable preferences."""

import copy
import hashlib
import io
import wave
import tempfile
from pathlib import Path

from . import preferences


def list_references(language: str) -> dict:
    if language not in ("ru", "en"):
        raise ValueError("Choose ru or en")
    return copy.deepcopy(preferences.read().get("speech_references", {}).get(language, {}))


def save(role: str, language: str, audio: bytes, text: str) -> dict:
    if role not in ("host", "guest") or language not in ("ru", "en"):
        raise ValueError("Choose host/guest and ru/en")
    if not text.strip() or len(text) > 2000 or len(audio) > 10 * 1024 * 1024:
        raise ValueError("Provide a transcript (1–2000 characters) and WAV up to 10 MiB")
    try:
        with wave.open(io.BytesIO(audio), "rb") as stream:
            duration = stream.getnframes() / stream.getframerate()
            if (
                stream.getsampwidth() != 2
                or stream.getnchannels() not in (1, 2)
                or not 2 <= duration <= 20
            ):
                raise ValueError("Voice samples must be PCM16 WAV, mono/stereo, 2–20 seconds")
            frames = stream.readframes(stream.getnframes())
            if len(frames) != stream.getnframes() * stream.getnchannels() * 2:
                raise ValueError("Voice sample is truncated")
            if not any(frames):
                raise ValueError("Voice samples must contain audible speech")
    except (wave.Error, EOFError) as error:
        raise ValueError("Provide a valid PCM16 WAV voice sample") from error
    digest = hashlib.sha256(audio).hexdigest()
    directory = preferences.data_directory() / "voices"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (digest + ".wav")
    # Content-addressed bytes are never replaced when a voice profile changes.
    with tempfile.NamedTemporaryFile(dir=directory, delete=False) as output:
        temporary = Path(output.name)
        try:
            output.write(audio)
            output.flush()
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    result = {
        "path": str(path),
        "sha256": digest,
        "text": text.strip(),
        "duration_seconds": duration,
    }
    with preferences.edit() as values:
        values.setdefault("speech_references", {}).setdefault(language, {})[role] = result
    return result


def selected(language: str) -> dict:
    refs = list_references(language)
    for role in ("host", "guest"):
        if role not in refs:
            raise ValueError(f"Set a {language} WAV voice sample and transcript for {role} first")
        item = refs[role]
        path = Path(item["path"])
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
            raise ValueError(f"Voice sample for {role} is missing or damaged")
    return refs


def freeze(project: Path, refs: dict) -> dict:
    """Keep the exact samples with the project so closed projects remain portable."""
    result = copy.deepcopy(refs)
    directory = project / "voice-samples"
    directory.mkdir(parents=True, exist_ok=True)
    for item in result.values():
        audio = Path(item["path"]).read_bytes()
        if hashlib.sha256(audio).hexdigest() != item["sha256"]:
            raise ValueError("Voice sample changed while preparing the audio job")
        output_path = directory / (item["sha256"] + ".wav")
        with tempfile.NamedTemporaryFile(dir=directory, delete=False) as stream:
            temporary = Path(stream.name)
            try:
                stream.write(audio)
                stream.flush()
                temporary.replace(output_path)
            finally:
                temporary.unlink(missing_ok=True)
        item["path"] = str(output_path.relative_to(project))
    return result


def resolve(project: Path, refs: dict) -> dict:
    result = copy.deepcopy(refs)
    for item in result.values():
        path = (project / item["path"]).resolve()
        if not path.is_relative_to(project):
            raise ValueError("Saved voice sample is outside the project")
        item["path"] = str(path)
    return result
