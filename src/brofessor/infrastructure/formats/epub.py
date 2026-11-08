"""Reflowable EPUB 2/3 text projection and lossless resource reconstruction.

The shared translation workflow and its P1 probe use this module. Model
output supplies text only. ZIP paths, XML elements, attributes, links, CSS, code,
mathematics and illustrations remain under local control. Nothing is fetched or
executed. Coverage of this projection is not a semantic translation-quality score.
"""

import hashlib
import os
import re
import tempfile
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit
from zipfile import ZIP_DEFLATED, ZIP_STORED, BadZipFile, ZipFile

from pydantic import Field

from brofessor import prompts
from brofessor.contracts.content import ContentLanguage
from brofessor.infrastructure.formats.contracts import EPUB_MIMETYPE_FILENAME, NCX_MIME, XHTML_MIME
from brofessor.infrastructure.formats.epub_xml import (
    DC,
    NCX,
    OPF,
    OPS,
    XHTML,
    XML_LANG,
    publication_xml,
    serialize_publication,
)
from brofessor.infrastructure.formats.ingestion import (
    MAX_SOURCE_BYTES,
    _elements,
    _href_path,
    _read_entry,
    _validate_archive,
    _xml,
)
from brofessor.models import Output
from brofessor.prompts import ids as prompt_ids

MARKER = re.compile(r"⟦[^⟦⟧]*⟧")
_PLAIN_MATH = re.compile(r"(\b(?:square|cube)(?:_root)?\([^()]*\))")
_BLOCKS = set(
    "html head body title section article div nav aside ol ul dl li dt dd table thead tbody "
    "tfoot tr td th caption figure figcaption blockquote hgroup details summary p "
    "h1 h2 h3 h4 h5 h6 address header footer main".split()
)
_FROZEN = set("pre code kbd samp style script math svg img br hr wbr".split())
_ATTRIBUTES = ("alt", "title", "aria-label")


class TranslatedBlock(Output):
    id: str = Field(min_length=1)
    text: str = Field(min_length=1)


class TranslationBatch(Output):
    blocks: list[TranslatedBlock] = Field(min_length=1)


@dataclass(frozen=True)
class TextBlock:
    id: str
    document: str
    locator: str
    text: str
    protected: dict[str, str]

    def as_dict(self):
        return vars(self)

    def plain_text(self, text=None):
        """Readable original context, including immutable mathematical/code text."""
        return MARKER.sub(
            lambda m: self.protected.get(m[0], ""), self.text if text is None else text
        )


@dataclass
class _Slot:
    element: ET.Element
    field: str
    attribute: bool = False

    def read(self):
        return (
            self.element.get(self.field, "")
            if self.attribute
            else getattr(self.element, self.field) or ""
        )

    def write(self, text):
        if self.attribute:
            self.element.set(self.field, text)
        else:
            setattr(self.element, self.field, text)


@dataclass
class _PartSlot:
    """An editable span around an immutable plain-text mathematical expression."""

    origin: _Slot
    parts: list[str]
    index: int

    def write(self, text):
        self.parts[self.index] = text
        self.origin.write("".join(self.parts))


def _local(element):
    return element.tag.rsplit("}", 1)[-1]


def _preserved_notice(element):
    return (
        "copyright-page" in element.get("{" + OPS + "}type", "").split()
        or element.get("id") in {"pg-header", "pg-footer"}
        and "pg-boilerplate" in element.get("class", "").split()
    )


def _frozen(element):
    return (
        not element.tag.startswith("{" + XHTML + "}")
        or _local(element) in _FROZEN
        or element.get("translate") == "no"
        or _preserved_notice(element)
        or "noteref" in element.get("{" + OPS + "}type", "").split()
    )


def _numbers(text):
    text = MARKER.sub("", text)
    values = []
    for value in re.findall(r"[-−+]?(?:\d+(?:[.,]\d+)*|[.,]\d+)", text):
        value = value.replace(",", ".").replace("−", "-")
        sign = value[0] if value.startswith(("-", "+")) else ""
        magnitude = value[len(sign) :]
        if magnitude.startswith("."):
            magnitude = "0" + magnitude
        values.append(sign + magnitude)
    return Counter(values)


def validate_batch(value, blocks):
    """Require exactly the requested blocks and unchanged inline boundaries/numbers."""
    value = TranslationBatch.model_validate(value).model_dump()
    expected = {block.id: block for block in blocks}
    result = {item["id"]: item["text"] for item in value["blocks"]}
    if len(result) != len(value["blocks"]) or set(result) != set(expected):
        raise ValueError("Translation must cover every requested block exactly once")
    for identifier, text in result.items():
        original = expected[identifier].text
        if not text.strip():
            raise ValueError(f"Blank translated block: {identifier}")
        if MARKER.findall(text) != MARKER.findall(original):
            raise ValueError(f"Changed inline markers: {identifier}")
        if "⟦" in MARKER.sub("", text) or "⟧" in MARKER.sub("", text):
            raise ValueError(f"Malformed inline marker: {identifier}")
        if _numbers(text) != _numbers(original):
            raise ValueError(f"Changed numeric values: {identifier}")
        # Emptying an emphasized phrase or link is also a content loss.
        if any(
            before.strip() and not after.strip()
            for before, after in zip(MARKER.split(original), MARKER.split(text), strict=True)
        ):
            raise ValueError(f"Removed inline text: {identifier}")
    return result


def translation_prompt(blocks, language, glossary=None):
    import json

    return prompts.render(
        prompt_ids.BOOKS_TRANSLATE,
        language=language,
        payload=json.dumps(
            {"glossary": glossary or [], "blocks": [block.as_dict() for block in blocks]},
            ensure_ascii=False,
        ),
    )


def _project(roots, package_path):
    blocks, bindings = [], {}

    def add(document, path, text, slots, protected=None):
        if not MARKER.sub("", text).strip():
            return
        identifier = f"{document}#{path}"
        block = TextBlock(identifier, document, identifier, text, protected or {})
        blocks.append(block)
        bindings[identifier] = slots

    def attributes(element, document, path):
        if element.get("translate") == "no":
            return
        for name in _ATTRIBUTES:
            if element.get(name, "").strip():
                add(document, path + "@" + name, element.get(name), [_Slot(element, name, True)])

    def walk(element, document, path):
        if _frozen(element):
            return
        attributes(element, document, path)
        slots, parts, protected = [], [], {}
        serial, run = 0, 0

        def slot(node, field):
            nonlocal serial
            binding = _Slot(node, field)
            text = binding.read()
            fragments = _PLAIN_MATH.split(text)
            if len(fragments) == 1:
                slots.append(binding)
                parts.append(text)
                return
            for index, fragment in enumerate(fragments):
                if index % 2 == 0:
                    slots.append(_PartSlot(binding, fragments, index))
                    parts.append(fragment)
                else:
                    serial += 1
                    token = f"⟦keep:{serial}⟧"
                    parts.append(token)
                    protected[token] = fragment

        def inline(child, child_path):
            nonlocal serial
            serial += 1
            number = serial
            if _local(child) == "img" or not _frozen(child):
                attributes(child, document, child_path)
            if _frozen(child):
                token = f"⟦keep:{number}⟧"
                parts.append(token)
                protected[token] = "".join(child.itertext())
            else:
                parts.append(f"⟦open:{number}⟧")
                slot(child, "text")
                for index, descendant in enumerate(child):
                    inline(descendant, f"{child_path}/{index}")
                    slot(descendant, "tail")
                parts.append(f"⟦close:{number}⟧")

        def flush():
            nonlocal slots, parts, protected, run
            add(document, f"{path}/run:{run}", "".join(parts), slots, protected)
            slots, parts, protected = [], [], {}
            run += 1

        slot(element, "text")
        for index, child in enumerate(element):
            child_path = f"{path}/{index}"
            # Older books sometimes encode whole chapters in <big> with <br>
            # paragraphs. Project those paragraphs separately without flattening
            # or rewriting their original inline container.
            break_flow = sum(_local(c) == "br" for c in child) >= 2
            if (_local(child) in _BLOCKS or break_flow) and not _frozen(child):
                flush()
                walk(child, document, child_path)
            else:
                if (
                    _local(child) == "br"
                    and index > 0
                    and _local(element[index - 1]) == "br"
                    and not (element[index - 1].tail or "").strip()
                ):
                    flush()
                    slot(child, "tail")
                    continue
                inline(child, child_path)
            slot(child, "tail")
        flush()

    for document, root in roots.items():
        if document == package_path:
            for index, element in enumerate(root.iter()):
                if element.tag in {
                    f"{{{DC}}}{name}" for name in ("title", "description", "subject")
                }:
                    add(document, f"metadata:{index}", element.text or "", [_Slot(element, "text")])
                elif element.tag == f"{{{OPF}}}reference" and element.get("title"):
                    add(
                        document,
                        f"guide:{index}@title",
                        element.get("title"),
                        [_Slot(element, "title", True)],
                    )
        elif root.tag == f"{{{NCX}}}ncx":
            for index, element in enumerate(root.iter()):
                if element.tag in {f"{{{NCX}}}navLabel", f"{{{NCX}}}docTitle"}:
                    for child_index, child in enumerate(element):
                        if child.tag == f"{{{NCX}}}text":
                            add(
                                document,
                                f"navigation:{index}/{child_index}",
                                child.text or "",
                                [_Slot(child, "text")],
                            )
        else:
            walk(root, document, "0")
    return blocks, bindings


class EpubBook:
    """Snapshot a supported reflowable EPUB; rebuilding never modifies the original."""

    projection_version = 3

    def __init__(self, source):
        self.source = Path(source).resolve()
        if self.source.stat().st_size > MAX_SOURCE_BYTES:
            raise ValueError("EPUB exceeds the source size limit")
        data = self.source.read_bytes()
        if len(data) > MAX_SOURCE_BYTES:
            raise ValueError("EPUB exceeds the source size limit")
        self.source_hash = hashlib.sha256(data).hexdigest()
        try:
            with ZipFile(BytesIO(data)) as archive:
                _validate_archive(archive)
                self.entries = {
                    entry.filename: _read_entry(archive, entry.filename)
                    for entry in archive.infolist()
                    if not entry.is_dir()
                }
        except (BadZipFile, OSError, RuntimeError) as error:
            raise ValueError("Cannot read EPUB archive") from error
        if self.entries.get(EPUB_MIMETYPE_FILENAME) != b"application/epub+zip":
            raise ValueError("Missing or invalid EPUB mimetype")
        if {"META-INF/encryption.xml", "META-INF/signatures.xml"} & self.entries.keys():
            raise ValueError("Encrypted, obfuscated or signed EPUB is not supported by this probe")
        container = _xml(self.entries.get("META-INF/container.xml", b""))
        rootfiles = _elements(container, "rootfile")
        if len(rootfiles) != 1:
            raise ValueError("The probe requires one EPUB package")
        self.package_path = _href_path(rootfiles[0].get("full-path", ""))
        package = publication_xml(self._entry(self.package_path))
        self.title = next((element.text or "" for element in package.iter(f"{{{DC}}}title")), "")
        self.version = package.get("version", "")
        if self.version != "2.0" and not self.version.startswith("3."):
            raise ValueError("Supported EPUB package versions are 2.0 and 3.x")
        if any(
            element.get("property") == "rendition:layout" and element.text == "pre-paginated"
            for element in _elements(package, "meta")
        ):
            raise ValueError("Fixed-layout EPUB is not supported by this probe")
        base = str(PurePosixPath(self.package_path).parent)
        manifest, documents, navigation = {}, {}, {}
        for item in _elements(package, "item"):
            identifier = item.get("id")
            if not identifier or identifier in manifest:
                raise ValueError("Missing or duplicate EPUB manifest ID")
            path = _href_path(item.get("href", ""), base)
            self._entry(path)
            manifest[identifier] = item
            if item.get("media-overlay") or "scripted" in item.get("properties", "").split():
                raise ValueError("Scripted or media-overlay EPUB is not supported by this probe")
            if item.get("media-type") == XHTML_MIME:
                documents[path] = publication_xml(self._entry(path))
            elif item.get("media-type") == NCX_MIME:
                root = publication_xml(self._entry(path))
                if root.tag != f"{{{NCX}}}ncx" or root.find(f"{{{NCX}}}navMap") is None:
                    raise ValueError("Invalid NCX navigation")
                navigation[path] = root
        spine_element = package.find(f"{{{OPF}}}spine")
        toc = spine_element.get("toc") if spine_element is not None else None
        if toc or self.version == "2.0":
            if toc not in manifest or manifest[toc].get("media-type") != NCX_MIME:
                raise ValueError("EPUB spine must reference its NCX navigation")
        spine = _elements(package, "itemref")
        if not spine:
            raise ValueError("EPUB has no reading-order spine")
        order = []
        for reference in spine:
            item = manifest.get(reference.get("idref"))
            if item is None or item.get("media-type") != XHTML_MIME:
                raise ValueError("EPUB spine must reference XHTML documents")
            if reference.get("properties", "").find("pre-paginated") >= 0:
                raise ValueError("Fixed-layout spine item is not supported by this probe")
            order.append(_href_path(item.get("href"), base))
        self.document_paths = list(dict.fromkeys([*order, *documents]))
        self.navigation_paths = list(navigation)
        self.language = next(iter(package.iter(f"{{{DC}}}language")), None)
        if self.language is None or not (self.language.text or "").strip():
            raise ValueError("EPUB requires a source language")
        self.language = self.language.text.strip()
        for root in documents.values():
            if root.tag != f"{{{XHTML}}}html":
                raise ValueError("EPUB content must be namespace-qualified XHTML")
            for element in root.iter():
                if _local(element) == "script" or any(
                    name.rsplit("}", 1)[-1].lower().startswith("on")
                    or (
                        name.rsplit("}", 1)[-1].lower()
                        in {"href", "src", "action", "formaction", "data"}
                        and urlsplit(value).scheme.lower() in {"javascript", "vbscript"}
                    )
                    for name, value in element.attrib.items()
                ):
                    raise ValueError("Scripted EPUB content is not supported by this probe")
                if any(
                    "⟦" in text or "⟧" in text
                    for text in (element.text or "", element.tail or "", *element.attrib.values())
                ):
                    raise ValueError("Source text collides with translation markers")
        roots = self._roots()
        self.preserved_notices = [
            {
                "document": path,
                "id": element.get("id"),
                "reason": "original copyright/license notice",
            }
            for path in self.document_paths
            for element in roots[path].iter()
            if _preserved_notice(element)
        ]
        self.blocks, _ = _project(roots, self.package_path)
        if not self.blocks:
            raise ValueError("EPUB has no translatable text")

    def _entry(self, path):
        try:
            return self.entries[path]
        except KeyError:
            raise ValueError(f"Missing EPUB entry: {path}") from None

    def _roots(self):
        return {
            path: publication_xml(self._entry(path))
            for path in [self.package_path, *self.document_paths, *self.navigation_paths]
        }

    def render(self, value, output, language):
        """Validate the complete projection before atomically publishing a new EPUB."""
        if language not in {ContentLanguage.RU, ContentLanguage.EN}:
            raise ValueError("The translation probe supports ru/en output")
        output = Path(output)
        if output.resolve() == self.source or (output.exists() and output.samefile(self.source)):
            raise ValueError("Translation must not overwrite the original EPUB")
        translations = validate_batch(value, self.blocks)
        roots = self._roots()
        _, bindings = _project(roots, self.package_path)
        for identifier, text in translations.items():
            for slot, part in zip(bindings[identifier], MARKER.split(text), strict=True):
                slot.write(part)
        package = roots[self.package_path]
        for element in package.iter(f"{{{DC}}}language"):
            element.text = language
        identifier = next(
            (
                element
                for element in package.iter(f"{{{DC}}}identifier")
                if element.get("id") == package.get("unique-identifier")
            ),
            None,
        )
        if identifier is None or not identifier.text:
            raise ValueError("Missing EPUB unique identifier")
        original_id = identifier.text
        identifier.text += f":brofessor:{language}:{self.source_hash[:12]}"
        metadata = package.find(f"{{{OPF}}}metadata")
        if metadata is None:
            raise ValueError("Missing EPUB metadata")
        ET.SubElement(metadata, f"{{{DC}}}source").text = original_id
        for element in _elements(package, "meta"):
            if element.get("property") == "dcterms:modified":
                element.text = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        for path in self.document_paths:
            root = roots[path]

            def update_language(element):
                if _preserved_notice(element):
                    if not element.get(XML_LANG) and not element.get("lang"):
                        element.set(XML_LANG, self.language)
                    return
                if element.get("translate") == "no" or _local(element) in {
                    "pre",
                    "code",
                    "kbd",
                    "samp",
                    "math",
                    "svg",
                    "style",
                    "script",
                }:
                    return
                for key in ("lang", XML_LANG):
                    if element.get(key) == self.language:
                        element.set(key, language)
                for child in element:
                    update_language(child)

            update_language(root)
            if self.version != "2.0":
                root.set("lang", language)
            elif root.get("lang") is not None:
                root.attrib.pop("lang")
            root.set(XML_LANG, language)
        for path in self.navigation_paths:
            root = roots[path]
            root.set(XML_LANG, language)
            for element in root.iter(f"{{{NCX}}}meta"):
                if element.get("name") == "dtb:uid":
                    element.set("content", identifier.text)
        entries = dict(self.entries)
        entries.update(
            {path: serialize_publication(self._entry(path), root) for path, root in roots.items()}
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".epub-", dir=output.parent)
        try:
            with os.fdopen(fd, "w+b") as handle:
                with ZipFile(handle, "w", compression=ZIP_DEFLATED) as archive:
                    archive.writestr(
                        EPUB_MIMETYPE_FILENAME,
                        entries[EPUB_MIMETYPE_FILENAME],
                        compress_type=ZIP_STORED,
                    )
                    for path, content in entries.items():
                        if path != EPUB_MIMETYPE_FILENAME:
                            archive.writestr(path, content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, output)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return output
