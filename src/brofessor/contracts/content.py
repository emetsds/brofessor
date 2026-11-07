"""Common content values; Literal aliases preserve the existing JSON schemas."""

from enum import StrEnum
from typing import Literal, NotRequired, TypedDict


class ContentLanguage(StrEnum):
    RU = "ru"
    EN = "en"


ContentLanguageValue = Literal[ContentLanguage.RU, ContentLanguage.EN]


class InterfaceLanguage(StrEnum):
    RU = "ru"
    EN = "en"


class Speaker(StrEnum):
    HOST = "host"
    GUEST = "guest"


SpeakerValue = Literal[Speaker.HOST, Speaker.GUEST]


class EvidenceStatus(StrEnum):
    SUPPORTED = "supported"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    CONFLICTING_EVIDENCE = "conflicting_evidence"


EvidenceStatusValue = Literal[
    EvidenceStatus.SUPPORTED,
    EvidenceStatus.INSUFFICIENT_EVIDENCE,
    EvidenceStatus.CONFLICTING_EVIDENCE,
]
StudyEvidenceStatusValue = Literal[EvidenceStatus.SUPPORTED, EvidenceStatus.INSUFFICIENT_EVIDENCE]


class UnitStatus(StrEnum):
    READY = "ready"
    EMPTY = "empty"


class ArtifactKind(StrEnum):
    JSON = "json"
    MARKDOWN = "markdown"
    PPTX = "pptx"
    AUDIO = "audio"
    AUDIOBOOK = "audiobook"
    EPUB = "epub"
    PDF = "pdf"


class SourceRecord(TypedDict):
    id: str
    name: str
    hash: str
    original: str
    created: float
    hidden: int


class SourceUnit(TypedDict):
    id: str
    source_id: str
    locator: str
    text: str
    status: str


class ExtractedUnit(TypedDict):
    locator: str
    text: str
    status: str
    reason: NotRequired[str]
    error: NotRequired[str]


class ArtifactRecord(TypedDict):
    job_id: str
    path: str
    kind: str
    metadata: dict
