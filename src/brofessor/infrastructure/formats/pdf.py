"""Text-layer PDF projection and local, measured reconstruction.

PDFium decodes objects; pypdf edits text streams while preserving resources.
ReportLab writes embedded Unicode text.
Original graphics are never rasterized or covered with white rectangles. Layout
that cannot be handled without losing text is rejected before publication.
"""

import ctypes
import hashlib
import math
import os
import re
import tempfile
from collections import Counter
from contextlib import closing
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import as_file, files
from io import BytesIO
from pathlib import Path
from threading import RLock
from xml.sax.saxutils import escape

import pypdfium2 as pdfium
from pypdf import PdfReader
from pypdfium2 import raw
from reportlab.lib.colors import Color
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Paragraph

from brofessor.contracts.content import ContentLanguage
from brofessor.infrastructure.formats.contracts import DocumentExtension, DocumentFormat
from brofessor.infrastructure.formats.epub import TextBlock, validate_batch
from brofessor.infrastructure.formats.ingestion import MAX_SOURCE_BYTES

# PDFium is not thread-safe, including calls on different documents. UI sessions
# may preflight concurrently; workers are separate OS processes.
_PDF_LOCK = RLock()
_MATH_FONT = re.compile(r"symbol|math|cmsy|cmmi|cmex|stix", re.I)
_CODE_FONT = re.compile(r"courier|mono|consolas", re.I)
_FORMULA = re.compile(r"^[\d\sA-Za-z_.,+−*/=()^<>≤≥±%\-]+$")


def _union(boxes):
    boxes = list(boxes)
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )


def _overlap(a, b):
    return min(a[1], b[1]) - max(a[0], b[0])


def _font_names():
    result = {}
    for style, suffix in (
        ("regular", ""),
        ("bold", "-Bold"),
        ("italic", "-Oblique"),
        ("bolditalic", "-BoldOblique"),
    ):
        name = "brofessor-DejaVu-" + style
        if name not in pdfmetrics.getRegisteredFontNames():
            resource = files(__package__).joinpath("fonts", f"DejaVuSans{suffix}.ttf")
            with as_file(resource) as font:
                pdfmetrics.registerFont(TTFont(name, str(font)))
        result[style] = name
    return result


@dataclass(frozen=True)
class _Span:
    index: int
    text: str
    bbox: tuple
    size: float
    style: str
    color: tuple
    frozen: str | None
    baseline: float = 0
    raw_text: str = ""
    mono: bool = False
    script: bool = False
    form: bool = False


def _segments(obj):
    """Straight path boundaries cap cells/columns without interpreting tables."""
    fill, stroke = ctypes.c_int(), ctypes.c_int()
    raw.FPDFPath_GetDrawMode(obj, fill, stroke)
    left, bottom, right, top = obj.get_bounds()
    if not stroke.value and min(right - left, top - bottom) > 2:
        return []
    matrix = obj.get_matrix()
    previous = start = None
    result = []
    for index in range(raw.FPDFPath_CountSegments(obj)):
        segment = raw.FPDFPath_GetPathSegment(obj, index)
        x, y = ctypes.c_float(), ctypes.c_float()
        if not raw.FPDFPathSegment_GetPoint(segment, x, y):
            continue
        point = matrix.on_point(x.value, y.value)
        kind = raw.FPDFPathSegment_GetType(segment)
        if kind == raw.FPDF_SEGMENT_MOVETO:
            start = point
        elif kind == raw.FPDF_SEGMENT_LINETO and previous is not None:
            result.append((*previous, *point))
        previous = point
        if raw.FPDFPathSegment_GetClose(segment) and start is not None:
            result.append((*point, *start))
    return result


def _frozen(text, font):
    if _MATH_FONT.search(font) or (
        "=" in text
        and _FORMULA.fullmatch(text)
        and all(len(word) <= 3 for word in re.findall(r"[A-Za-z]+", text))
    ):
        return "formula"
    if _CODE_FONT.search(font) and re.search(
        r"[{};]|\w+\([^)]*\)|\w+\s*(?:=|:=)|^\s*(?:>>>|#|//|def |class |return )|^\w+_\w+$", text
    ):
        return "code"
    if not any(c.isalpha() for c in text):
        return "numeric/symbol"
    return None


def _available(region, regions, boundaries, obstacles, width, height, *, tolerance=0.5):
    left, bottom, original_right, top = region.bbox
    # Only extend into demonstrably empty space. Cells, neighbouring columns,
    # protected text, images and the next paragraph all constrain the result.
    right = width - min(36, left)
    low = min(36, bottom)
    top = min(height, top + 1)
    centered_container = None
    if tolerance > 0.5:
        containers = [
            box
            for box in obstacles
            if box[0] <= left and box[1] <= bottom and box[2] >= original_right and box[3] >= top
        ]
        if containers:
            container = min(containers, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))
            if (
                all(s.form for s in region.spans)
                and original_right - left < (container[2] - container[0]) * 0.8
                and abs((left + original_right - container[0] - container[2]) / 2)
                < (container[2] - container[0]) * 0.15
            ):
                centered_container = container
            right = min(right, container[2] - 2)
            low = max(low, container[1] + 2)
            obstacles = [box for box in obstacles if box not in containers]
    for other in regions:
        if other is region:
            continue
        x0, y0, x1, y1 = other.bbox
        if _overlap((bottom, top), (y0, y1)) > 0.5 and x0 >= original_right - 0.2:
            right = min(right, x0 - 5)
    for x0, y0, x1, y1 in boundaries:
        if abs(x0 - x1) < 0.2 and x0 >= original_right - 0.2:
            if _overlap((bottom, top), (min(y0, y1), max(y0, y1))) > 0:
                right = min(right, x0 - 2)
    for x0, y0, x1, y1 in obstacles:
        if _overlap((bottom, top), (y0, y1)) > 0 and x0 >= original_right:
            right = min(right, x0 - 3)
    for other in [r.bbox for r in regions if r is not region] + obstacles:
        x0, y0, x1, y1 = other
        if _overlap((left, right), (x0, x1)) > 0.5:
            if y1 <= bottom + 0.2:
                low = max(low, y1 + 3)
            elif _overlap((bottom, top), (y0, y1)) > 0.5:
                # Overlapping source text/illustrations cannot be safely reflowed.
                if (
                    _overlap((left, original_right), (x0, x1)) > tolerance
                    and _overlap((bottom, region.bbox[3]), (y0, y1)) > tolerance
                ):
                    raise ValueError(f"PDF page {region.page}: overlapping text/graphics")
    for x0, y0, x1, y1 in boundaries:
        if abs(y0 - y1) < 0.2 and y0 <= bottom + 0.2:
            if _overlap((left, right), (min(x0, x1), max(x0, x1))) > 0:
                low = max(low, y0 + 2)
    if centered_container is not None:
        center = (centered_container[0] + centered_container[2]) / 2
        # Image bounds include the outline and often a soft shadow. Reserve
        # interior space so a wrapped label cannot cover an incoming arrow.
        padding = min(
            max(s.size for s in region.spans) * 1.2,
            (centered_container[2] - centered_container[0]) * 0.2,
        )
        half = min(right - center, center - centered_container[0] - padding)
        left, right = center - half, center + half
        region.centered = True
    return left, low, right, top


def _sizes(source, minimum):
    size = source
    while size >= minimum - 0.01:
        yield size
        size = round(size - 0.25, 4)


@lru_cache(maxsize=1)
def _russian_hyphenator():
    import pyphen

    return pyphen.Pyphen(lang="ru_RU")


def _hyphenated(markup, language, width, font, size):
    # ReportLab's automatic hyphenation accepts Latin letters only. Explicit
    # soft hyphens use the same dictionary without breaking source code/URLs.
    if language == ContentLanguage.RU:
        return re.sub(
            r"[А-Яа-яЁё]{5,}",
            lambda m: (
                _russian_hyphenator().inserted(m[0], "\u00ad")
                if pdfmetrics.stringWidth(m[0], font, size) > width
                else m[0]
            ),
            markup,
        )
    return markup


class PdfBook:
    format = DocumentFormat.PDF
    projection_version = 2

    def __init__(self, source, *, check=lambda: None):
        self.source = Path(source).resolve()
        if self.source.stat().st_size > MAX_SOURCE_BYTES:
            raise ValueError("PDF exceeds source size limit")
        self._data = self.source.read_bytes()
        self.source_hash = hashlib.sha256(self._data).hexdigest()
        reader = PdfReader(BytesIO(self._data))
        if reader.is_encrypted:
            raise ValueError("Encrypted PDF translation is unsupported")
        self.language = str(reader.trailer["/Root"].get("/Lang", "und"))
        if reader.trailer["/Root"].get("/AcroForm"):
            raise ValueError("PDF forms/signatures are unsupported for translation")
        if not 1 <= len(reader.pages) <= 2000:
            raise ValueError("PDF page count is outside the supported range")
        for number, page in enumerate(reader.pages, 1):
            if (
                page.rotation
                or page.user_unit != 1
                or tuple(page.mediabox) != tuple(page.cropbox)
                or float(page.mediabox.left) != 0
                or float(page.mediabox.bottom) != 0
            ):
                raise ValueError(f"PDF page {number}: rotated/cropped/nonstandard coordinates")
        self.title = self.source.stem
        from brofessor.infrastructure.formats import pdf_layout

        self._aliases = [pdf_layout.font_aliases(p) for p in reader.pages]
        from brofessor.infrastructure.formats.pdf_background import text_keys

        seen_forms = set()
        self._text_keys = [text_keys(p, reader, seen_forms, check=check) for p in reader.pages]
        self.blocks, self._regions, self._pages, self.preserved = [], {}, [], []
        self._moving_numbers = {}
        self._moving_code = {}
        with _PDF_LOCK, pdfium.PdfDocument(self._data) as document:
            for page_number in range(len(document)):
                check()
                self._read_page(document, page_number)
        if not self.blocks:
            raise ValueError("PDF has no translatable text layer")

    def _read_page(self, document, page_number):
        number = page_number + 1
        with closing(document[page_number]) as page, closing(page.get_textpage()) as textpage:
            width, height = page.get_size()
            objects = list(page.get_objects(max_depth=15, textpage=textpage))
            if len(objects) > 100000:
                raise ValueError(f"PDF page {number}: too many objects")
            spans, boundaries, obstacles = [], [], []
            for index, obj in enumerate(objects):
                bbox = obj.get_bounds()
                if not all(math.isfinite(v) for v in bbox):
                    raise ValueError(f"PDF page {number}: invalid object bounds")
                if obj.type == raw.FPDF_PAGEOBJ_FORM:
                    if any(
                        abs(a - b) > 0.001
                        for a, b in zip(obj.get_matrix().get(), (1, 0, 0, 1, 0, 0))
                    ):
                        raise ValueError(
                            f"PDF page {number}: transformed Form XObject is unsupported"
                        )
                    continue
                elif obj.type == raw.FPDF_PAGEOBJ_IMAGE:
                    shadow = False
                    bitmap = obj.get_bitmap(render=True)
                    try:
                        pixels = bitmap.to_pil()
                        extrema = pixels.getextrema()
                        shadow = (
                            pixels.mode == "RGBA"
                            and all(v[1] == 0 for v in extrema[:3])
                            and extrema[3][1] <= 160
                        )
                    finally:
                        del bitmap  # Borrowed image bitmaps are owned by the page.
                    if not shadow:
                        obstacles.append(bbox)
                elif obj.type == raw.FPDF_PAGEOBJ_PATH:
                    boundaries.extend(_segments(obj))
                elif obj.type == raw.FPDF_PAGEOBJ_TEXT:
                    extracted = obj.extract()
                    text = extracted.strip()
                    if not text:
                        continue
                    original_text = extracted
                    font = obj.get_font().get_base_name()
                    from brofessor.infrastructure.formats.pdf_layout import decode

                    text = decode(original_text, self._aliases[page_number].get(font, {}))
                    if any(ord(c) < 32 or c == "\ufffd" for c in text):
                        raise ValueError(f"PDF page {number}: text cannot be decoded reliably")
                    matrix = obj.get_matrix()
                    angle_tolerance = max(abs(matrix.a), abs(matrix.d)) * 0.002
                    if (
                        abs(matrix.b) > angle_tolerance
                        or abs(matrix.c) > angle_tolerance
                        or matrix.a <= 0
                        or matrix.d <= 0
                    ):
                        raise ValueError(f"PDF page {number}: rotated/skewed text is unsupported")
                    if raw.FPDFTextObj_GetTextRenderMode(obj) != raw.FPDF_TEXTRENDERMODE_FILL:
                        raise ValueError(f"PDF page {number}: invisible/stroked/clipped text")
                    clip = raw.FPDFPageObj_GetClipPath(obj)
                    if clip and raw.FPDFClipPath_CountPaths(clip) > 0:
                        raise ValueError(f"PDF page {number}: clipped text is unsupported")
                    if (
                        bbox[0] < -0.5
                        or bbox[1] < -0.5
                        or bbox[2] > width + 0.5
                        or bbox[3] > height + 0.5
                    ):
                        raise ValueError(f"PDF page {number}: text outside page bounds")
                    channels = [ctypes.c_uint() for _ in range(4)]
                    if not raw.FPDFPageObj_GetFillColor(obj, *channels) or channels[3].value != 255:
                        raise ValueError(f"PDF page {number}: unsupported text opacity/color")
                    style = "bold" if re.search("bold|black|heavy|Smbd", font, re.I) else ""
                    style += (
                        "italic" if re.search(r"italic|oblique|-It$|SmbdIt$", font, re.I) else ""
                    )
                    size = obj.get_font_size() * matrix.d
                    if not math.isfinite(size) or size <= 0:
                        raise ValueError(f"PDF page {number}: invalid text size")
                    spans.append(
                        _Span(
                            index,
                            text,
                            bbox,
                            size,
                            style or "regular",
                            tuple(c.value / 255 for c in channels[:3]),
                            _frozen(text, font),
                            matrix.f,
                            original_text,
                            bool(_CODE_FONT.search(font)),
                            False,
                            obj.level > 0,
                        )
                    )

            # A missing object mapping must fail before a translation can be called complete.
            def covered(text):
                return "".join(text.replace("\x02", "").replace("\ufffe", "").split())

            if Counter(covered(textpage.get_text_range())) != Counter(
                covered("".join(s.raw_text for s in spans))
            ):
                raise ValueError(f"PDF page {number}: incomplete text-object coverage")
            if not spans and obstacles:
                raise ValueError(f"PDF page {number}: image-only page; OCR is not supported")
            from brofessor.infrastructure.formats.pdf_layout import regions as project_regions

            regions = project_regions(spans, number, boundaries, width, height)
            self._pages.append({"width": width, "height": height})
            text_objects = [i for i, o in enumerate(objects) if o.type == raw.FPDF_PAGEOBJ_TEXT]
            if len(text_objects) != len(self._text_keys[page_number]):
                raise ValueError(f"PDF page {number}: ambiguous text-show mapping")
            ordinal = {index: n for n, index in enumerate(text_objects)}
            for region in regions:
                region.text_ordinals = [ordinal[s.index] for s in region.spans]
                for number_region in getattr(region, "numbers", []):
                    key = f"pdf:p{number}:o{number_region.spans[0].index}"
                    self._moving_numbers[key] = number_region
                for code_region in getattr(region, "following_code", []):
                    key = f"pdf:p{number}:o{code_region.spans[0].index}"
                    self._moving_code[key] = code_region
            for region in regions:
                identifier = f"pdf:p{number}:o{region.spans[0].index}"
                frozen = region.frozen
                if frozen:
                    self.preserved.append(
                        {
                            "id": identifier,
                            "page": number,
                            "bbox": region.bbox,
                            "text": region.text,
                            "reason": frozen,
                            "raw_text": "".join(s.raw_text for s in region.spans),
                        }
                    )
                    continue
                flowing_regions = [
                    r for r in regions if r not in getattr(region, "following_code", [])
                ]
                region.box = _available(
                    region,
                    flowing_regions,
                    boundaries,
                    obstacles,
                    width,
                    height,
                    tolerance=4,
                )
                region.limit_box = _available(
                    region,
                    [region] + [r for r in flowing_regions if r.frozen],
                    boundaries,
                    obstacles,
                    width,
                    height,
                    tolerance=4,
                )
                locator = f"page {number}, box " + ",".join(f"{v:.2f}" for v in region.bbox)
                self.blocks.append(
                    TextBlock(
                        identifier,
                        f"page:{number}",
                        locator,
                        region.text,
                        region.protected,
                    )
                )
                self._regions[identifier] = region

    def _contents_layout(self, block, region, markup, font, language):
        left, bottom, right, _ = region.box
        source_rows = region.row_baselines
        spacing = min(a - b for a, b in zip(source_rows, source_rows[1:]))
        size = region.spans[0].size
        while size >= min(region.spans[0].size, 9) - 0.01:
            rows = []
            baseline = source_rows[0]
            style = ParagraphStyle(
                "contents-row",
                fontName=font,
                fontSize=size,
                leading=size * 1.15,
                textColor=Color(*region.spans[0].color),
                splitLongWords=False,
                hyphenationLang="ru_RU" if language == ContentLanguage.RU else "en_US",
            )
            for index, text in enumerate(markup.split("<br/>")):
                paragraph = Paragraph(_hyphenated(text, language, right - left, font, size), style)
                _, height = paragraph.wrap(right - left, 1000)
                original = region.numbers[index]
                rows.append(
                    {
                        "bbox": (left, baseline + size - height, right, baseline + size),
                        "baseline": baseline,
                        "source_baseline": source_rows[index],
                        "number_id": f"pdf:p{region.page}:o{original.spans[0].index}",
                        "number_x": original.bbox[0],
                        "number": original.text,
                        "paragraph": paragraph,
                    }
                )
                baseline -= max(spacing, height + 2)
            if min(row["bbox"][1] for row in rows) >= bottom and all(
                max(row["paragraph"].getActualLineWidths0(), default=0) <= right - left + 0.01
                for row in rows
            ):
                return {
                    "id": block.id,
                    "page": region.page,
                    "bbox": _union(row["bbox"] for row in rows),
                    "source_bbox": region.bbox,
                    "font_size": size,
                    "rows": rows,
                }
            size = round(size - 0.25, 4)
        raise ValueError(f"PDF {block.locator}: contents rows overflow at readable font size")

    def _layout(self, texts, check, language):
        fonts = _font_names()
        layout = []
        for block in self.blocks:
            check()
            region = self._regions[block.id]
            span = region.spans[0]
            font = fonts[span.style]
            plain = texts[block.id]
            from brofessor.infrastructure.formats.epub import MARKER

            plain = MARKER.sub(lambda m: block.protected.get(m[0], ""), plain)
            if any(
                ord(c) not in pdfmetrics.getFont(font).face.charToGlyph
                for c in plain
                if not c.isspace()
            ):
                raise ValueError(f"PDF {block.locator}: unsupported output glyph")
            left, bottom, right, top = region.box
            if getattr(region, "row_baselines", []):
                from brofessor.infrastructure.formats.epub import MARKER

                markup = escape(texts[block.id])

                def row_marker(match):
                    marker = match[0]
                    if marker.startswith("⟦close:"):
                        return "</font>"
                    run = region.runs[marker]
                    if run["style"] == "break":
                        return "<br/>"
                    face = "Courier" if run["style"] == "code" else fonts[run["style"]]
                    start = f'<font name="{face}">'
                    return (
                        start + escape(block.protected[marker]) + "</font>"
                        if marker in block.protected
                        else start
                    )

                markup = MARKER.sub(row_marker, markup)
                layout.append(self._contents_layout(block, region, markup, font, language))
                continue
            source_size = max(s.size for s in region.spans)
            extra_bottom = max(region.limit_box[1], bottom - source_size)
            for accepted in layout:
                if (
                    accepted["page"] == region.page
                    and accepted["source_bbox"][3] > region.bbox[3]
                    and _overlap((left, right), (accepted["bbox"][0], accepted["bbox"][2])) > 0.5
                ):
                    top = min(top, accepted["bbox"][1] - 3)
            minimum = min(source_size, max(9, source_size * 0.8))
            rows = getattr(region, "row_baselines", [])
            if rows:
                minimum = min(span.size, 9)
            size = source_size
            # First fit within the paragraph's own space. Taking the next
            # paragraph's space greedily can make an otherwise feasible page
            # overflow later. Borrow a little only after readable sizes fail.
            candidates = [
                (candidate, bottom, ratio)
                for ratio in (1.15, 1.05)
                for candidate in _sizes(source_size, minimum)
            ]
            if extra_bottom < bottom:
                candidates.extend(
                    (candidate, extra_bottom, ratio)
                    for ratio in (1.15, 1.05)
                    for candidate in _sizes(source_size, minimum)
                )
            for size, available_bottom, ratio in candidates:
                markup = escape(texts[block.id])

                def inline(match):
                    marker = match[0]
                    if marker.startswith("⟦close:"):
                        return "</font>"
                    run = region.runs[marker]
                    if run["style"] == "break":
                        return "<br/>"
                    if run["style"] == "sup":
                        return "<super>" + escape(block.protected[marker]) + "</super>"
                    face = "Courier" if run["style"] == "code" else fonts[run["style"]]
                    color = Color(*run["color"]).hexval()
                    start = f'<font name="{face}" color="{color}">'
                    return (
                        start + escape(block.protected[marker]) + "</font>"
                        if marker in block.protected
                        else start
                    )

                markup = MARKER.sub(inline, markup)
                leading = (
                    min(a - b for a, b in zip(rows, rows[1:])) if len(rows) > 1 else size * ratio
                )
                if rows:
                    top = rows[0] + size
                style = ParagraphStyle(
                    "translation",
                    fontName=font,
                    fontSize=size,
                    leading=leading,
                    textColor=Color(*span.color),
                    splitLongWords=False,
                    hyphenationLang=""
                    if getattr(region, "centered", False)
                    else "ru_RU"
                    if language == ContentLanguage.RU
                    else "en_US",
                    spaceShrinkage=0,
                    alignment=1 if getattr(region, "centered", False) else 0,
                )
                paragraph = Paragraph(
                    _hyphenated(
                        markup,
                        None if getattr(region, "centered", False) else language,
                        right - left,
                        font,
                        size,
                    )
                    + "".join(
                        '<br/><font name="Courier" size="'
                        + str(code.spans[0].size)
                        + '">'
                        + escape(code.text)
                        + "</font>"
                        for code in getattr(region, "following_code", [])
                    ),
                    style,
                )
                width, height = paragraph.wrap(max(1, right - left), max(1, top - available_bottom))
                if (
                    max(paragraph.getActualLineWidths0(), default=0) <= right - left + 0.01
                    and height <= top - available_bottom
                    and width > 0
                    and right > left
                    and (
                        not rows
                        or all(
                            Paragraph(row, style).wrap(right - left, 1000)[1] <= leading + 0.01
                            for row in markup.split("<br/>")
                        )
                    )
                ):
                    break
            else:
                raise ValueError(
                    f"PDF {block.locator}: translated text overflows at readable font size"
                )
            if getattr(region, "centered", False):
                top = (region.bbox[1] + region.bbox[3] + height) / 2
            box = (left, top - height, left + width, top)
            for accepted in layout:
                if accepted["page"] == region.page and (
                    _overlap((box[0], box[2]), (accepted["bbox"][0], accepted["bbox"][2])) > 0.5
                    and _overlap((box[1], box[3]), (accepted["bbox"][1], accepted["bbox"][3])) > 0.5
                ):
                    raise ValueError(f"PDF {block.locator}: translated regions overlap")
            layout.append(
                {
                    "id": block.id,
                    "page": region.page,
                    "bbox": box,
                    "source_bbox": region.bbox,
                    "font_size": size,
                    "leading": leading,
                    "paragraph": paragraph,
                    "centered": getattr(region, "centered", False),
                    **(
                        {
                            "suffix": "\n".join(code.text for code in region.following_code),
                            "code_ids": [
                                f"pdf:p{region.page}:o{code.spans[0].index}"
                                for code in region.following_code
                            ],
                        }
                        if getattr(region, "following_code", [])
                        else {}
                    ),
                }
            )
        return layout

    def render(self, value, output, language, *, check=lambda: None):
        if language not in (ContentLanguage.RU, ContentLanguage.EN):
            raise ValueError("Choose ru or en")
        texts = validate_batch(value, self.blocks)
        output = Path(output).resolve()
        if output == self.source or (output.exists() and os.path.samefile(output, self.source)):
            raise ValueError("PDF output must not overwrite the original")
        with _PDF_LOCK:
            layout = self._layout(texts, check, language)
            from brofessor.infrastructure.formats.pdf_background import remove_text

            writer = remove_text(
                BytesIO(self._data),
                self._text_keys,
                {**self._regions, **self._moving_numbers, **self._moving_code},
                check=check,
            )
            for number, dimensions in enumerate(self._pages, 1):
                check()
                overlay = BytesIO()
                canvas = Canvas(overlay, pagesize=(dimensions["width"], dimensions["height"]))
                for item in layout:
                    if item["page"] == number:
                        if "rows" in item:
                            for row in item["rows"]:
                                row["paragraph"].drawOn(canvas, row["bbox"][0], row["bbox"][1])
                                canvas.setFont(_font_names()["regular"], item["font_size"])
                                canvas.drawString(row["number_x"], row["baseline"], row["number"])
                        else:
                            item["paragraph"].drawOn(canvas, item["bbox"][0], item["bbox"][1])
                canvas.showPage()
                canvas.save()
                writer.pages[number - 1].merge_page(PdfReader(overlay).pages[0])
                # A wrapped contents row moves its clickable area with the label;
                # the original destination/action remains untouched.
                from pypdf.generic import NameObject, RectangleObject

                for annotation in writer.pages[number - 1].get("/Annots", []):
                    annotation = annotation.get_object()
                    if annotation.get("/Subtype") != "/Link" or "/Rect" not in annotation:
                        continue
                    rect = tuple(float(v) for v in annotation["/Rect"])
                    for item in layout:
                        if item["page"] != number or "rows" not in item:
                            continue
                        source_size = max(s.size for s in self._regions[item["id"]].spans)
                        row = min(
                            item["rows"],
                            key=lambda r: abs(
                                (rect[1] + rect[3]) / 2 - r["source_baseline"] - source_size / 3
                            ),
                        )
                        if (
                            row["source_baseline"] - 2
                            <= (rect[1] + rect[3]) / 2
                            <= row["source_baseline"] + source_size
                            and _overlap(
                                (rect[0], rect[2]), (item["source_bbox"][0], item["source_bbox"][2])
                            )
                            > 0
                        ):
                            annotation[NameObject("/Rect")] = RectangleObject(
                                (rect[0], row["bbox"][1] - 2, rect[2], row["bbox"][3] + 1)
                            )
            from pypdf.generic import NameObject, TextStringObject

            writer.root_object[NameObject("/Lang")] = TextStringObject(language)
            writer.add_metadata(
                {
                    "/Producer": f"brofessor PDF translation v{self.projection_version}",
                    "/Title": texts[self.blocks[0].id],
                    "/Subject": f"Translated to {language} by brofessor. Original SHA-256: "
                    + self.source_hash,
                }
            )
            output.parent.mkdir(parents=True, exist_ok=True)
            handle, path = tempfile.mkstemp(
                prefix=".translation-", suffix=DocumentExtension.PDF, dir=output.parent
            )
            try:
                with os.fdopen(handle, "wb") as stream:
                    writer.write(stream)
                # Reopen before atomic publication; visual QA remains a separate check.
                if len(PdfReader(path).pages) != len(self._pages):
                    raise ValueError("PDF reconstruction lost pages")
                check()
                os.replace(path, output)
            finally:
                Path(path).unlink(missing_ok=True)
        from importlib.metadata import version

        preserved = [dict(item) for item in self.preserved]
        for item in layout:
            for offset, identifier in enumerate(reversed(item.get("code_ids", []))):
                record = next(p for p in preserved if p["id"] == identifier)
                code = self._moving_code[identifier]
                size = code.spans[0].size
                width = pdfmetrics.stringWidth(code.text, "Courier", size)
                baseline = item["bbox"][1] + item["leading"] * (1 + offset) - item["font_size"]
                left = item["bbox"][0]
                if item.get("centered"):
                    left += (item["bbox"][2] - left - width) / 2
                record["source_bbox"] = record["bbox"]
                record["bbox"] = (left, baseline - size * 0.25, left + width, baseline + size)
            for row in item.get("rows", []):
                record = next(p for p in preserved if p["id"] == row["number_id"])
                size = item["font_size"]
                record["source_bbox"] = record["bbox"]
                record["bbox"] = (
                    row["number_x"],
                    row["baseline"] - size * 0.25,
                    row["number_x"]
                    + pdfmetrics.stringWidth(row["number"], _font_names()["regular"], size),
                    row["baseline"] + size,
                )

        def manifest(item):
            value = {k: v for k, v in item.items() if k not in ("paragraph", "rows")}
            if "rows" in item:
                value["rows"] = [manifest(row) for row in item["rows"]]
            return value

        return {
            "pages": len(self._pages),
            "source_sha256": self.source_hash,
            "blocks": [manifest(item) for item in layout],
            "preserved": preserved,
            "renderer": {
                "pypdfium2": version("pypdfium2"),
                "pdfium": str(pdfium.PDFIUM_INFO),
                "reportlab": version("reportlab"),
                "pypdf": version("pypdf"),
                "background": "content-stream",
                "font": "DejaVu Sans 2.37",
            },
        }
