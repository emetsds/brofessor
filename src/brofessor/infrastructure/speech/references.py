"""Local WAV voice samples and transcripts; immutable files, editable preferences."""

import copy
import hashlib
import io
import tempfile
import wave
from pathlib import Path
from typing import Final

from brofessor.contracts.content import ContentLanguage, Speaker
from brofessor.infrastructure.formats.contracts import AudioExtension
from brofessor.infrastructure.speech.contracts import SpeechModelSpec, VoiceReference
from brofessor.infrastructure.storage import preferences

VOICE_SAMPLES_DIRECTORY: Final = "voice-samples"


def list_references(language: str) -> dict[str, VoiceReference]:
    if language not in (ContentLanguage.RU, ContentLanguage.EN):
        raise ValueError("Choose ru or en")
    return copy.deepcopy(preferences.read().get("speech_references", {}).get(language, {}))


def save(role: str, language: str, audio: bytes, text: str) -> VoiceReference:
    if role not in (Speaker.HOST, Speaker.GUEST) or language not in (
        ContentLanguage.RU,
        ContentLanguage.EN,
    ):
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
    path = directory / (digest + AudioExtension.WAV)
    # Content-addressed bytes are never replaced when a voice profile changes.
    with tempfile.NamedTemporaryFile(dir=directory, delete=False) as output:
        temporary = Path(output.name)
        try:
            output.write(audio)
            output.flush()
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    result: VoiceReference = {
        "path": str(path),
        "sha256": digest,
        "text": text.strip(),
        "duration_seconds": duration,
    }
    with preferences.edit() as values:
        values.setdefault("speech_references", {}).setdefault(language, {})[role] = result
    return result


def selected(language: str) -> dict[str, VoiceReference]:
    refs = list_references(language)
    for role in (Speaker.HOST, Speaker.GUEST):
        if role not in refs:
            raise ValueError(f"Set a {language} WAV voice sample and transcript for {role} first")
        item = refs[role]
        path = Path(item["path"])
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
            raise ValueError(f"Voice sample for {role} is missing or damaged")
    return refs


class MissingVoicePack(ValueError):
    """The catalog's preset recordings have not been installed."""

    revision: int | None = None


def _project_sample(item):
    return Path(VOICE_SAMPLES_DIRECTORY) / (item["sha256"] + AudioExtension.WAV)


def preset_snapshot(spec: SpeechModelSpec, language: str, *, portable=False) -> SpeechModelSpec:
    """Describe bundled voices in the pack or at their frozen project paths."""
    from brofessor.infrastructure.speech.catalogue import installed_path, total_bytes

    result = copy.deepcopy(spec)
    pack_id = result.pop("voice_pack")
    pack = next(item for item in result["dependencies"] if item["id"] == pack_id)
    directory = None if portable else installed_path(pack)
    if not portable and directory is None:
        raise MissingVoicePack(
            f"First use requires {spec['name']} and its voice samples "
            f"({total_bytes(spec) / 1e9:.2f} GB)."
        )
    refs = result.pop("preset_references")[language]
    for item in refs.values():
        filename = item.pop("file")
        if portable:
            item["path"] = str(_project_sample(item))
        else:
            assert directory is not None  # Missing installed packs were rejected above.
            item["path"] = str(directory / filename)
        item["source"] = f"{pack['repo']}@{pack['revision']}"
    result["references"] = refs
    # Frozen project copies carry these samples. Only inference dependencies remain.
    result["dependencies"] = [d for d in result["dependencies"] if d["id"] != pack_id]
    return result


def freeze(project: Path, refs: dict[str, VoiceReference]) -> dict[str, VoiceReference]:
    """Keep the exact samples with the project so closed projects remain portable."""
    result = copy.deepcopy(refs)
    directory = project / VOICE_SAMPLES_DIRECTORY
    directory.mkdir(parents=True, exist_ok=True)
    for item in result.values():
        audio = Path(item["path"]).read_bytes()
        if hashlib.sha256(audio).hexdigest() != item["sha256"]:
            raise ValueError("Voice sample changed while preparing the audio job")
        output_path = project / _project_sample(item)
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


def resolve(project: Path, refs: dict[str, VoiceReference]) -> dict[str, VoiceReference]:
    result = copy.deepcopy(refs)
    for item in result.values():
        path = (project / item["path"]).resolve()
        if not path.is_relative_to(project):
            raise ValueError("Saved voice sample is outside the project")
        item["path"] = str(path)
    return result
