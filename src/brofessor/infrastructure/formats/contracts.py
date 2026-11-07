"""File formats and suffixes, distinct from task kinds and artifact roles."""

from enum import StrEnum
from typing import Final


class DocumentFormat(StrEnum):
    EPUB = "epub"
    PDF = "pdf"


class DocumentExtension(StrEnum):
    MARKDOWN = ".md"
    TEXT = ".txt"
    PDF = ".pdf"
    EPUB = ".epub"


class AudioExtension(StrEnum):
    WAV = ".wav"
    MP3 = ".mp3"
    M4B = ".m4b"


PPTX_EXTENSION: Final = ".pptx"
SOURCE_EXTENSIONS: Final = frozenset(DocumentExtension)
TEXT_SOURCE_EXTENSIONS: Final = frozenset({DocumentExtension.MARKDOWN, DocumentExtension.TEXT})

EPUB_MIMETYPE_FILENAME: Final = "mimetype"
XHTML_MIME: Final = "application/xhtml+xml"
NCX_MIME: Final = "application/x-dtbncx+xml"
HTML_MIME: Final = "text/html"
