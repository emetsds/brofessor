"""Bundled voice recordings and immutable project copies."""

import copy
import hashlib
import tempfile
from pathlib import Path
from typing import Final

from brofessor.infrastructure.formats.contracts import AudioExtension
from brofessor.infrastructure.speech.contracts import SpeechModelSpec, VoiceReference

VOICE_SAMPLES_DIRECTORY: Final = "voice-samples"


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
