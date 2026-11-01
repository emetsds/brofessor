"""Native editable PPTX layouts with measured text and readable font floors."""

import os
import tempfile
from functools import lru_cache
from pathlib import Path

from PIL import ImageFont
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE, PP_ALIGN
from pptx.oxml.xmlchemy import OxmlElement
from pptx.util import Inches, Pt

from .models import Slides

INK, ACCENT, MUTED = "142B39", "008773", "526772"


@lru_cache(maxsize=1)
def _font_files():
    for regular, bold in (
        ("Arial.ttf", "Arial Bold.ttf"),
        ("LiberationSans-Regular.ttf", "LiberationSans-Bold.ttf"),
        ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf"),
    ):
        try:
            plain = ImageFont.truetype(regular, 72)
            heavy = ImageFont.truetype(bold, 72)
            return plain.getname()[0], plain.path, heavy.path
        except OSError:
            continue
    raise ValueError(
        "PPTX needs Arial, Liberation Sans or DejaVu Sans (regular and bold) installed"
    )


@lru_cache(maxsize=64)
def _font(size, bold=False):
    return ImageFont.truetype(_font_files()[2 if bold else 1], size * 4)


def _height(text, width, size, bold=False):
    """Conservative word wrapping in points; keep explicit paragraph boundaries."""
    font = _font(size, bold)
    available = width * 72 * 4 * 0.93
    count = 0
    for paragraph in text.split("\n"):
        line = ""
        count += 1
        for word in paragraph.split():
            if font.getlength(word) > available:
                return float("inf")
            candidate = f"{line} {word}" if line else word
            if line and font.getlength(candidate) > available:
                count += 1
                line = word
            else:
                line = candidate
    return count * size * 1.25


def _fit(texts, width, height, maximum, minimum, *, gap=0, bold=False):
    for size in range(maximum, minimum - 1, -1):
        paragraphs = sum(text.count("\n") + 1 for text in texts)
        total = sum(_height(text, width, size, bold) for text in texts)
        if total + max(0, paragraphs - 1) * gap <= height * 72:
            return size
    raise ValueError(f"Text is too dense at {minimum} pt; shorten it or split the slide")


def _style(frame, size, color=INK, *, bold=False, gap=0):
    frame.word_wrap = True
    frame.auto_size = MSO_AUTO_SIZE.NONE
    for paragraph in frame.paragraphs:
        paragraph.font.name = _font_files()[0]
        paragraph.font.size = Pt(size)
        paragraph.font.bold = bold
        paragraph.font.color.rgb = RGBColor.from_string(color)
        paragraph.line_spacing = Pt(size * 1.25)
        paragraph.space_before = Pt(0)
        paragraph.space_after = Pt(gap)


def _text(slide, text, bounds, size, color=INK, *, bold=False, gap=0):
    frame = slide.shapes.add_textbox(*(Inches(v) for v in bounds)).text_frame
    frame.margin_left = frame.margin_right = frame.margin_top = frame.margin_bottom = 0
    frame.text = text
    _style(frame, size, color, bold=bold, gap=gap)
    return frame


def _bullets(slide, bullets, top, height):
    size = _fit(bullets, 11.6, height, 23, 20, gap=12)
    frame = _text(slide, "\n".join(bullets), (0.7, top, 11.9, height), size, gap=12)
    for paragraph in frame.paragraphs:
        properties = paragraph._p.get_or_add_pPr()
        properties.set("marL", str(Inches(0.25)))
        properties.set("indent", str(-Inches(0.25)))
        marker = OxmlElement("a:buChar")
        marker.set("char", "•")
        properties.insert_element_before(marker, "a:tabLst", "a:defRPr", "a:extLst")
    return (sum(_height(text, 11.6, size) for text in bullets) + 12 * (len(bullets) - 1)) / 72


def _table(slide, table, top, height):
    rows = [table["headers"], *table["rows"]]
    columns = len(rows[0])
    width = 11.9 / columns
    for size in range(21, 17, -1):
        heights = [
            max(_height(cell, width - 0.24, size, index == 0) for cell in row) + 11.52
            for index, row in enumerate(rows)
        ]
        if sum(heights) <= height * 72:
            break
    else:
        raise ValueError("Table is too dense at 18 pt; shorten cells or split the table")
    shape = slide.shapes.add_table(
        len(rows), columns, Inches(0.7), Inches(top), Inches(11.9), Pt(sum(heights))
    )
    for i, row in enumerate(rows):
        shape.table.rows[i].height = Pt(heights[i])
        for j, value in enumerate(row):
            cell = shape.table.cell(i, j)
            cell.text = value
            cell.fill.solid()
            cell.fill.fore_color.rgb = RGBColor.from_string("E5F0EE" if i == 0 else "FFFFFF")
            cell.margin_left = cell.margin_right = Inches(0.12)
            cell.margin_top = cell.margin_bottom = Inches(0.08)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            _style(cell.text_frame, size, bold=i == 0)


def _flat(shape):
    shape._element.spPr.append(OxmlElement("a:effectLst"))
    for effect in shape._element.xpath("./p:style/a:effectRef"):
        effect.set("idx", "0")


def _steps(slide, steps, top):
    gap, padding = 0.38, 0.15
    width = (11.9 - gap * (len(steps) - 1)) / len(steps)
    height = 2.25
    try:
        size = min(
            _fit([text], width - 2 * padding, height - 2 * padding, 23, 18) for text in steps
        )
        top = max(top, 2.35)
        positions = [(0.7 + i * (width + gap), top) for i in range(len(steps))]
        horizontal = True
    except ValueError:
        horizontal = False
        gap, padding, width = 0.18, 0.1, 11.9
        height = (6.3 - top - gap * (len(steps) - 1)) / len(steps)
        size = min(
            _fit([text], width - 2 * padding, height - 2 * padding, 23, 18) for text in steps
        )
        positions = [(0.7, top + i * (height + gap)) for i in range(len(steps))]
    for i, (text, (left, y)) in enumerate(zip(steps, positions)):
        shape = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE, Inches(left), Inches(y), Inches(width), Inches(height)
        )
        shape.fill.solid()
        shape.fill.fore_color.rgb = RGBColor.from_string("E5F0EE")
        shape.line.color.rgb = RGBColor.from_string(ACCENT)
        _flat(shape)
        frame = shape.text_frame
        frame.margin_left = frame.margin_right = Inches(padding)
        frame.margin_top = frame.margin_bottom = Inches(padding)
        frame.vertical_anchor = MSO_ANCHOR.MIDDLE
        frame.text = text
        _style(frame, size)
        for paragraph in frame.paragraphs:
            paragraph.alignment = PP_ALIGN.CENTER
        if i < len(steps) - 1:
            if horizontal:
                kind = MSO_SHAPE.CHEVRON
                bounds = (left + width + 0.08, y + 0.94, gap - 0.16, 0.35)
            else:
                kind = MSO_SHAPE.DOWN_ARROW
                bounds = (left + width / 2 - 0.14, y + height + 0.02, 0.28, gap - 0.04)
            arrow = slide.shapes.add_shape(kind, *(Inches(value) for value in bounds))
            arrow.fill.solid()
            arrow.fill.fore_color.rgb = RGBColor.from_string(ACCENT)
            arrow.line.fill.background()
            _flat(arrow)


def _deck(plan, source_labels):
    deck = Presentation()
    deck.slide_width, deck.slide_height = Inches(13.333333), Inches(7.5)
    deck.core_properties.author = "brofessor"
    deck.core_properties.title = plan["title"]
    deck.core_properties.subject = "Source-grounded editable presentation"
    deck.core_properties.language = "ru-RU" if plan["language"] == "ru" else "en-US"
    for number, item in enumerate(plan["slides"], 1):
        try:
            slide = deck.slides.add_slide(deck.slide_layouts[6])
            slide.background.fill.solid()
            slide.background.fill.fore_color.rgb = RGBColor.from_string("F8FAFA")
            size = _fit([item["title"]], 12, 1.12, 32, 28, bold=True)
            title = _text(slide, item["title"], (0.6, 0.43, 12, 1.12), size, bold=True)
            title.vertical_anchor = MSO_ANCHOR.MIDDLE
            top = 1.8
            visual = item["table"] is not None or bool(item["steps"])
            if item["bullets"]:
                used = _bullets(slide, item["bullets"], top, 1.5 if visual else 4.5)
                top += used + 0.3
            if item["table"] is not None:
                _table(slide, item["table"], top, 6.3 - top)
            elif item["steps"]:
                _steps(slide, item["steps"], max(top, 2.35))
            footer = (
                f"Источники в заметках докладчика: {len(item['citations'])}"
                if plan["language"] == "ru"
                else f"Source references in speaker notes: {len(item['citations'])}"
            )
            _text(slide, footer, (0.7, 6.78, 11.1, 0.3), 11, MUTED)
            page = _text(slide, f"{number:02}", (12, 6.78, 0.6, 0.3), 12, ACCENT)
            page.paragraphs[0].alignment = PP_ALIGN.RIGHT
            heading = "Источники" if plan["language"] == "ru" else "Sources"
            references = [
                f"{key} · {source_labels[key]}" if key in source_labels else key
                for key in item["citations"]
            ]
            slide.notes_slide.notes_text_frame.text = (
                item["notes"] + "\n\n" + heading + ":\n" + "\n".join(references)
            )
        except ValueError as error:
            raise ValueError(f"Slide {number} ({item['title']}): {error}") from error
    return deck


def render(plan, output, *, source_labels=None):
    """Validate before atomic publication; never truncate text or add slides."""
    plan = Slides.model_validate(plan).model_dump()
    output = Path(output).resolve()
    if output.suffix.lower() != ".pptx":
        raise ValueError("Slide output must have a .pptx suffix")
    deck = _deck(plan, source_labels or {})
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{output.stem}.", suffix=".pptx", dir=output.parent)
    os.close(fd)
    temporary = Path(name)
    try:
        deck.save(temporary)
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    return output
