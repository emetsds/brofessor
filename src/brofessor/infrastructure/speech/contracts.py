"""Speech adapter values and catalog records; model IDs remain open catalog data."""

from enum import StrEnum
from typing import Final, NotRequired, TypedDict


class SpeechEngine(StrEnum):
    QWEN_CUSTOM = "qwen3-mlx"
    QWEN_BASE = "qwen3-base-mlx"
    SILERO = "silero"
    F5 = "f5"
    KOKORO_RU = "kokoro-ru-onnx"


MODEL_CATALOGUE_FILENAME: Final = "speech_models.json"
DOWNLOAD_LOCK_FILENAME: Final = ".download.lock"
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
    requires_reference: bool
    dependencies: list[dict]
    local_code: list[str]
    sha256: str
    url: str
    legacy: bool
