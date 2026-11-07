"""Provider selection shared by preferences, jobs, adapters, and clients."""

from enum import StrEnum
from typing import Final, NotRequired, TypedDict


class TextProvider(StrEnum):
    CODEX = "codex"
    CLAUDE = "claude"
    OLLAMA = "ollama"


class MessageRole(StrEnum):
    SYSTEM = "system"
    USER = "user"


TEXT_PROVIDERS: Final = tuple(TextProvider)
DEFAULT_OLLAMA_PORT: Final = 11434
DEFAULT_OLLAMA_ADDRESS: Final = "127.0.0.1:11434"


class TextConnection(TypedDict):
    provider: str | None
    model: str | None
    ollama_address: NotRequired[str]
    ollama_port: NotRequired[int]


class SettingsSnapshot(TextConnection):
    language: str
    speech_model: str


class RunnerMessage(TypedDict):
    role: str
    content: str
