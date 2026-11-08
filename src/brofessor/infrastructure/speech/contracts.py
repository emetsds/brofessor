"""Speech adapter values and catalog records; model IDs remain open catalog data."""

from enum import StrEnum
from typing import Final, NotRequired, TypedDict


class SpeechEngine(StrEnum):
    QWEN_BASE = "qwen3-base-mlx"


MODEL_CATALOGUE_FILENAME: Final = "speech_models.json"
QWEN_ENGINE_PREFIX: Final = "qwen3"
QWEN_SPEECH_LOCK_FILENAME: Final = "qwen-speech.lock"


class VoiceReference(TypedDict):
    path: str
    text: str
    sha256: str
    duration_seconds: NotRequired[float]
    source: NotRequired[str]


class SpeechModelSpec(TypedDict, total=False):
    id: str
    name: str
    repo: str
    revision: str
    engine: str
    files: dict[str, int]
    download_bytes: int
    languages: list[str]
    voices: dict[str, str]
    available_voices: list[str]
    settings: dict
    references: dict[str, VoiceReference]
    preset_references: dict
    voice_pack: str
    dependencies: list[dict]
