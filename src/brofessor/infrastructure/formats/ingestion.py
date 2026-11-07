"""Bounded, local source extraction and lexical retrieval.

Documents are data. This module never follows external links, executes document
instructions, or unpacks an archive onto the filesystem. Limits reject the whole
import rather than silently dropping the rest of a source.
"""

import math
import re
import stat
import xml.etree.ElementTree as ET
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import cast
from urllib.parse import unquote, urlsplit
from zipfile import ZipFile

from pypdf import PdfReader

from brofessor.contracts.content import ExtractedUnit, UnitStatus
from brofessor.infrastructure.formats.contracts import (
    HTML_MIME,
    TEXT_SOURCE_EXTENSIONS,
    XHTML_MIME,
    DocumentExtension,
)

MAX_SOURCE_BYTES = 100 * 1024 * 1024
MAX_EPUB_UNCOMPRESSED_BYTES = 256 * 1024 * 1024
MAX_EPUB_ENTRY_BYTES = 32 * 1024 * 1024
MAX_EPUB_ENTRIES = 5000
MAX_EXTRACTED_CHARS = 32 * 1024 * 1024
MAX_COMPRESSION_RATIO = 1000
TEXT_LINES_PER_UNIT = 100


def extract_source(path: Path) -> list[ExtractedUnit]:
    """Extract every text range, PDF page, or EPUB spine item with a locator.

    PDF page numbers refer to the original file, not printed page labels. Blank
    units stay visible for coverage. A wholly empty, damaged, or unsupported
    source raises ValueError, as does any configured size limit.
    """
    path = Path(path)
    try:
        if not path.is_file():
            raise ValueError(f"Source is not a readable file: {path.name}")
        if path.stat().st_size > MAX_SOURCE_BYTES:
            raise ValueError(f"Source exceeds the {MAX_SOURCE_BYTES}-byte size limit")
        extension = path.suffix.lower()
        if extension in TEXT_SOURCE_EXTENSIONS:
            units = _extract_text(path)
        elif extension == DocumentExtension.PDF:
            units = _extract_pdf(path)
        elif extension == DocumentExtension.EPUB:
            units = _extract_epub(path)
        else:
            raise ValueError(f"Unsupported source format: {extension or '(no extension)'}")
    except OSError as error:
        raise ValueError(f"Cannot read source file {path.name}: {error.strerror}") from error
    if not any(unit["status"] == UnitStatus.READY for unit in units):
        detail = (
            " Scanned/image-only PDFs need OCR, which is not supported yet."
            if (extension == DocumentExtension.PDF)
            else ""
        )
        raise ValueError(f"No text could be extracted from {path.name}.{detail}")
    if sum(len(unit["text"]) for unit in units) > MAX_EXTRACTED_CHARS:
        raise ValueError("Extracted text exceeds the character limit")
    return units


def _unit(locator: str, text: str) -> ExtractedUnit:
    unit: ExtractedUnit = {
        "locator": locator,
        "text": text,
        "status": UnitStatus.READY if text.strip() else UnitStatus.EMPTY,
    }
    if unit["status"] == UnitStatus.EMPTY:
        unit["error"] = "No text in this unit (blank or image-only content)"
    return unit


def _extract_text(path: Path) -> list[ExtractedUnit]:
    try:
        text = path.read_bytes().decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("Markdown and TXT sources must be UTF-8 encoded") from error
    if "\x00" in text:
        raise ValueError("Text source contains NUL bytes and may be a binary file")
    lines = text.splitlines(keepends=True)
    return [
        _unit(
            f"lines {start + 1}-{min(start + TEXT_LINES_PER_UNIT, len(lines))}",
            "".join(lines[start : start + TEXT_LINES_PER_UNIT]),
        )
        for start in range(0, len(lines), TEXT_LINES_PER_UNIT)
    ]


def _extract_pdf(path: Path) -> list[ExtractedUnit]:
    try:
        with path.open("rb") as handle:
            reader = PdfReader(handle)
            if reader.is_encrypted:
                raise ValueError("Cannot import an encrypted PDF. Supply an unencrypted copy")
            units = []
            total_chars = 0
            for index, page in enumerate(reader.pages, 1):
                text = page.extract_text() or ""
                total_chars += len(text)
                if total_chars > MAX_EXTRACTED_CHARS:
                    raise ValueError("Extracted PDF text exceeds the character limit")
                units.append(_unit(f"page {index}", text))
            return units
    except ValueError:
        raise
    except Exception as error:
        raise ValueError(f"Cannot extract PDF: {type(error).__name__}: {error}") from error


def _safe_path(name: str, base: str = "") -> str:
    """Resolve an archive URI relative to base without escaping the archive."""
    if not name or "\\" in name or any(ord(char) < 32 for char in name):
        raise ValueError("Unsafe or empty EPUB path")
    if name.startswith("/") or re.match(r"^[a-zA-Z]:", name):
        raise ValueError("Absolute EPUB path is not allowed")
    parts = list(PurePosixPath(base).parts) if base else []
    for part in name.split("/"):
        if part in {"", "."}:
            continue
        if part == "..":
            if not parts:
                raise ValueError("EPUB path escapes the archive")
            parts.pop()
        else:
            parts.append(part)
    if not parts:
        raise ValueError("Empty EPUB path")
    return "/".join(parts)


def _href_path(href: str, base: str = "") -> str:
    uri = urlsplit(href)
    if uri.scheme or uri.netloc or uri.query:
        raise ValueError("External or unsupported EPUB path")
    return _safe_path(unquote(uri.path), base)


def _validate_archive(archive: ZipFile) -> None:
    entries = archive.infolist()
    if len(entries) > MAX_EPUB_ENTRIES:
        raise ValueError("EPUB exceeds the archive entry limit")
    total_bytes = 0
    names = set()
    for entry in entries:
        # Even unused assets must be safe, bounded, and unambiguous.
        name = entry.filename.rstrip("/")
        if _safe_path(name) != name or ".." in name.split("/"):
            raise ValueError("Unsafe or non-canonical EPUB archive path")
        if name in names:
            raise ValueError("Duplicate EPUB archive path")
        names.add(name)
        if stat.S_ISLNK(entry.external_attr >> 16):
            raise ValueError("EPUB symlink entries are not supported")
        if entry.flag_bits & 1:
            raise ValueError("Encrypted EPUB entries are not supported")
        if entry.file_size > MAX_EPUB_ENTRY_BYTES:
            raise ValueError("EPUB entry exceeds the uncompressed size limit")
        total_bytes += entry.file_size
        if total_bytes > MAX_EPUB_UNCOMPRESSED_BYTES:
            raise ValueError("EPUB exceeds the total uncompressed size limit")
        if entry.file_size > 1024 * 1024 and (
            entry.file_size / max(1, entry.compress_size) > MAX_COMPRESSION_RATIO
        ):
            raise ValueError("EPUB entry has an excessive compression ratio")


def _read_entry(archive: ZipFile, name: str) -> bytes:
    try:
        with archive.open(name) as entry:
            data = entry.read(MAX_EPUB_ENTRY_BYTES + 1)
    except KeyError as error:
        raise ValueError(f"Missing EPUB entry: {name}") from error
    if len(data) > MAX_EPUB_ENTRY_BYTES:
        raise ValueError("EPUB entry exceeds the uncompressed size limit")
    return data


def _xml(data: bytes) -> ET.Element:
    # ElementTree does not fetch external entities. Reject internal DTDs too,
    # including UTF-16 XML, to avoid document-supplied entity expansion.
    declaration = data.replace(b"\x00", b"").upper()
    if b"<!DOCTYPE" in declaration or b"<!ENTITY" in declaration:
        raise ValueError("EPUB metadata DTD/entity declarations are not supported")
    try:
        return ET.fromstring(data)
    except ET.ParseError as error:
        raise ValueError(f"Invalid EPUB metadata XML: {error}") from error


def _elements(root: ET.Element, local_name: str) -> list[ET.Element]:
    return [element for element in root.iter() if element.tag.split("}")[-1] == local_name]


class _ChapterText(HTMLParser):
    """Read visible text without fetching resources or evaluating markup."""

    BLOCKS = frozenset(
        {
            "p",
            "div",
            "section",
            "article",
            "aside",
            "blockquote",
            "li",
            "tr",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "br",
            "hr",
            "pre",
            "dt",
            "dd",
        }
    )
    HIDDEN = frozenset({"head", "script", "style", "template"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden: list[str] = []

    def handle_starttag(self, tag, attrs):
        if self.hidden:
            if tag in self.HIDDEN:
                self.hidden.append(tag)
            return
        if tag in self.HIDDEN:
            self.hidden.append(tag)
        elif tag in self.BLOCKS:
            self.parts.append("\n")
        elif tag in {"td", "th"}:
            self.parts.append("\t")

    def handle_endtag(self, tag):
        if self.hidden:
            if tag == self.hidden[-1]:
                self.hidden.pop()
        elif tag in self.BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)

    def text(self) -> str:
        lines = [
            re.sub(r"[\t \r\f\v]+", " ", line).strip() for line in "".join(self.parts).split("\n")
        ]
        return "\n".join(line for line in lines if line)


def _extract_epub(path: Path) -> list[ExtractedUnit]:
    try:
        with ZipFile(path) as archive:
            _validate_archive(archive)
            container = _xml(_read_entry(archive, "META-INF/container.xml"))
            rootfiles = _elements(container, "rootfile")
            if not rootfiles:
                raise ValueError("EPUB container has no package rootfile")
            package_path = _href_path(rootfiles[0].get("full-path", ""))
            package = _xml(_read_entry(archive, package_path))
            manifest = {}
            for item in _elements(package, "item"):
                identifier = item.get("id")
                if not identifier or identifier in manifest:
                    raise ValueError("EPUB manifest has missing or duplicate item IDs")
                manifest[identifier] = item
            spine = _elements(package, "itemref")
            if not spine:
                raise ValueError("EPUB has no reading-order spine")
            units = []
            total_chars = 0
            for index, reference in enumerate(spine, 1):
                chapter_item = manifest.get(reference.get("idref", ""))
                if chapter_item is None:
                    raise ValueError("EPUB spine references a missing manifest item")
                if chapter_item.get("media-type") not in {XHTML_MIME, HTML_MIME}:
                    raise ValueError("EPUB spine contains an unsupported non-HTML chapter")
                chapter_path = _href_path(
                    chapter_item.get("href", ""), str(PurePosixPath(package_path).parent)
                )
                content = _read_entry(archive, chapter_path)
                try:
                    html = content.decode("utf-8-sig")
                except UnicodeDecodeError:
                    # EPUB XML may also use UTF-16 (with its required BOM).
                    if content.startswith((b"\xff\xfe", b"\xfe\xff")):
                        html = content.decode("utf-16")
                    else:
                        raise ValueError("EPUB chapters must be UTF-8 or UTF-16 encoded") from None
                parser = _ChapterText()
                parser.feed(html)
                parser.close()
                text = parser.text()
                total_chars += len(text)
                if total_chars > MAX_EXTRACTED_CHARS:
                    raise ValueError("Extracted EPUB text exceeds the character limit")
                units.append(_unit(f"chapter {index} ({chapter_path})", text))
            return units
    except ValueError:
        raise
    except Exception as error:
        # ZIP compression codecs expose different exception classes. Keep the
        # importer boundary consistent for damaged archives and chapter bytes.
        raise ValueError(f"Cannot extract EPUB: {type(error).__name__}: {error}") from error


def chunks(units: list[ExtractedUnit], max_chars: int = 6000) -> list[ExtractedUnit]:
    """Bound units without losing characters or provenance.

    Oversized units receive 1-based inclusive character offsets relative to the
    extracted original unit. Short units and empty coverage entries retain their
    locators. All extra metadata is copied and inputs are never mutated.
    """
    if max_chars < 1:
        raise ValueError("max_chars must be positive")
    result: list[ExtractedUnit] = []
    for unit in units:
        text = unit["text"]
        if len(text) <= max_chars:
            result.append(cast(ExtractedUnit, dict(unit)))
            continue
        start = 0
        while start < len(text):
            end = min(start + max_chars, len(text))
            if end < len(text):
                # Prefer paragraph/word boundaries, without tiny trailing chunks.
                boundary = max(
                    text.rfind("\n", start + max_chars // 2, end),
                    text.rfind(" ", start + max_chars // 2, end),
                )
                if boundary != -1:
                    end = boundary + 1
            result.append(
                {
                    **unit,
                    "text": text[start:end],
                    "locator": f"{unit['locator']}, chars {start + 1}-{end}",
                }
            )
            start = end
    return result


_STOPWORDS = frozenset(
    [
        "a",
        "an",
        "the",
        "and",
        "or",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "to",
        "of",
        "in",
        "on",
        "at",
        "for",
        "from",
        "with",
        "it",
        "its",
        "as",
        "by",
        "this",
        "that",
        "these",
        "those",
        "what",
        "which",
        "who",
        "how",
        "where",
        "when",
        "does",
        "do",
        "did",
        "и",
        "или",
        "в",
        "во",
        "на",
        "по",
        "из",
        "к",
        "с",
        "со",
        "о",
        "об",
        "у",
        "от",
        "до",
        "за",
        "для",
        "это",
        "как",
        "что",
        "кто",
        "где",
        "когда",
        "какой",
        "какая",
        "какие",
        "какое",
        "ли",
        "не",
        "а",
        "но",
        "же",
        "бы",
        "был",
        "была",
        "были",
        "быть",
    ]
)


def _tokens(text: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[^\W_]+", text.casefold().replace("ё", "е"))
        if token not in _STOPWORDS
    ]


def search_units(units: list[dict], query: str, limit: int = 8) -> list[dict]:
    """Return matching ready units using deterministic BM25 lexical ranking.

    No-match queries return an empty list, never an arbitrary source excerpt.
    Cross-language expansion belongs to the caller. This function retains full
    records, including IDs/source revisions assigned by the application.
    """
    terms = sorted(set(_tokens(query)))
    if not terms or limit <= 0:
        return []
    documents = [
        (index, unit, Counter(_tokens(unit["text"])))
        for index, unit in enumerate(units)
        if unit.get("status") == UnitStatus.READY
    ]
    if not documents:
        return []
    frequencies = Counter(term for _, _, words in documents for term in terms if term in words)
    average_length = sum(sum(words.values()) for _, _, words in documents) / len(documents) or 1
    ranked = []
    for index, unit, words in documents:
        length = sum(words.values())
        score = 0.0
        for term in terms:
            count = words[term]
            if count:
                inverse_frequency = math.log(
                    1 + (len(documents) - frequencies[term] + 0.5) / (frequencies[term] + 0.5)
                )
                score += (
                    inverse_frequency
                    * count
                    * 2.2
                    / (count + 1.2 * (0.25 + 0.75 * length / average_length))
                )
        if score > 0:
            ranked.append((score, index, unit))
    ranked.sort(key=lambda result: (-result[0], result[1]))
    return [unit for _, _, unit in ranked[:limit]]
