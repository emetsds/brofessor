"""Regressions reduced from the full-book check, using original synthetic PDFs."""

import hashlib
from contextlib import closing
from io import BytesIO
from types import SimpleNamespace

import pypdfium2 as pdfium
import pytest
from pypdf import PdfReader
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    NumberObject,
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen.canvas import Canvas

from brofessor.infrastructure.formats.pdf import PdfBook, _font_names
from brofessor.infrastructure.formats.pdf_background import remove_text, text_keys
from brofessor.infrastructure.formats.pdf_layout import decode, font_aliases


def test_private_typographic_glyphs_use_the_documents_own_named_encoding():
    cmap = DecodedStreamObject()
    cmap.set_data(
        b"4 beginbfrange\n<21><21><e1eb>\n<22><22><e08a>\n<23><23><f731>\n<24><24><e037>\nendbfrange"
    )
    font = DictionaryObject(
        {
            NameObject("/BaseFont"): NameObject("/SUBSET+Example"),
            NameObject("/Encoding"): DictionaryObject(
                {
                    NameObject("/Differences"): ArrayObject(
                        [
                            NumberObject(33),
                            NameObject("/t.end"),
                            NameObject("/T_h"),
                            NameObject("/one.oldstyle"),
                            NameObject("/H.sc"),
                        ]
                    )
                }
            ),
            NameObject("/ToUnicode"): cmap,
        }
    )
    page = DictionaryObject(
        {
            NameObject("/Resources"): DictionaryObject(
                {NameObject("/Font"): DictionaryObject({NameObject("/F"): font})}
            )
        }
    )
    aliases = font_aliases(page)
    assert decode("\ue1eb\ue08a\uf731\ue037", aliases["Example"]) == "tTh1H"
    with pytest.raises(ValueError, match="private-use"):
        decode("\ue1eb", {})


def test_mixed_runs_and_indented_footnote_remain_complete_paragraphs(tmp_path):
    source = tmp_path / "mixed.pdf"
    c = Canvas(str(source), pagesize=(612, 792))
    f = _font_names()
    t = c.beginText(42, 700)
    t.setFont(f["regular"], 12)
    t.textOut("A ")
    t.setFont(f["italic"], 12)
    t.textOut("tree")
    t.setFont(f["regular"], 12)
    t.textOut(" contains ")
    t.setFont("Courier", 9)
    t.textOut("HEAD")
    t.setFont(f["regular"], 12)
    t.textOut(" values.")
    c.drawText(t)
    c.setFont(f["regular"], 9)
    c.drawString(42, 120, "1. The explanation continues on the next line")
    c.drawString(60, 108, "with a hanging indent and the same baseline spacing.")
    c.save()
    book = PdfBook(source)
    assert any(
        b.plain_text() == "A tree contains HEAD values." and b.protected for b in book.blocks
    )
    assert any("next line with a hanging indent" in b.plain_text() for b in book.blocks)
    from brofessor.infrastructure.formats.epub import validate_batch

    phrase = next(b for b in book.blocks if "A tree" in b.plain_text())
    translated = phrase.text.replace("A tree", "Дерево")
    assert "A " not in translated
    assert validate_batch({"blocks": [{"id": phrase.id, "text": translated}]}, [phrase])
    output = tmp_path / "rendered.pdf"
    book.render({"blocks": [{"id": b.id, "text": b.text} for b in book.blocks]}, output, "en")
    text = PdfReader(output).pages[0].extract_text()
    assert text.count("HEAD") == 1 and "hanging indent" in text


def test_nested_diagram_text_is_removed_from_form_before_translated_overlay(tmp_path):
    source = tmp_path / "form.pdf"
    c = Canvas(str(source), pagesize=(612, 792))
    c.beginForm("diagram")
    # An exporter background is filled, not a table separator.
    c.setFillColorRGB(1, 1, 1)
    c.rect(0, 0, 612, 792, fill=1, stroke=0)
    c.setFillColorRGB(0, 0, 0)
    c.setFont("Helvetica", 12)
    c.drawString(42, 700, "Nested diagram label")
    c.endForm()
    c.doForm("diagram")
    c.save()
    before = source.read_bytes()
    book = PdfBook(source)
    output = tmp_path / "rendered.pdf"
    book.render(
        {"blocks": [{"id": b.id, "text": "Переведённая подпись схемы"} for b in book.blocks]},
        output,
        "ru",
    )
    text = PdfReader(output).pages[0].extract_text()
    assert "Nested diagram label" not in text
    assert text.count("Переведённая подпись схемы") == 1
    assert hashlib.sha256(source.read_bytes()).digest() == hashlib.sha256(before).digest()
    with pytest.raises(ValueError, match="Form XObjects"):
        PdfBook(source, projection_version=1)


def test_removing_one_show_keeps_the_cursor_of_following_original_text(tmp_path):
    source = tmp_path / "cursor.pdf"
    c = Canvas(str(source), pagesize=(612, 792))
    t = c.beginText(42, 700)
    t.setFont("Helvetica", 12)
    t.textOut("Remove this ")
    t.textOut("123")
    c.drawText(t)
    c.save()
    reader = PdfReader(source)
    keys = [text_keys(reader.pages[0], reader, set())]
    writer = remove_text(
        BytesIO(source.read_bytes()), keys, {"selected": SimpleNamespace(page=1, text_ordinals=[0])}
    )
    output = tmp_path / "removed.pdf"
    writer.write(output)

    def position(path):
        with (
            pdfium.PdfDocument(str(path)) as d,
            closing(d[0]) as page,
            closing(page.get_textpage()) as text,
        ):
            return next(
                o.get_bounds()[0]
                for o in page.get_objects(textpage=text)
                if o.type == 1 and o.extract() == "123"
            )

    assert "Remove this" not in PdfReader(output).pages[0].extract_text()
    assert position(output) == pytest.approx(position(source), abs=0.01)


def test_shared_text_form_is_rejected_before_any_model_call(tmp_path):
    source = tmp_path / "shared.pdf"
    c = Canvas(str(source), pagesize=(612, 792))
    c.beginForm("shared")
    c.drawString(42, 700, "Shared text")
    c.endForm()
    c.doForm("shared")
    c.showPage()
    c.doForm("shared")
    c.save()
    with pytest.raises(ValueError, match="Shared text Form"):
        PdfBook(source)


def test_composite_source_fonts_fail_preflight_before_translation(tmp_path):
    source = tmp_path / "composite.pdf"
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    c = Canvas(str(source))
    c.setFont("STSong-Light", 12)
    c.drawString(42, 700, "Example 中文")
    c.save()
    with pytest.raises(ValueError, match="simple font"):
        PdfBook(source)


def test_contents_rows_keep_their_original_page_number_baselines(tmp_path):
    source = tmp_path / "contents.pdf"
    c = Canvas(str(source), pagesize=(612, 792))
    c.setFont(_font_names()["regular"], 12)
    expected = {}
    for index, label in enumerate(
        ["First section", "Second section", "Third section", "Last section"]
    ):
        baseline = 700 - index * 18
        c.drawString(42, baseline, label)
        c.drawString(510, baseline, str(index + 2))
        expected[label] = baseline
    c.save()
    book = PdfBook(source)
    output = tmp_path / "translated.pdf"
    book.render({"blocks": [{"id": b.id, "text": b.text} for b in book.blocks]}, output, "en")
    positions = {}
    with (
        pdfium.PdfDocument(str(output)) as d,
        closing(d[0]) as page,
        closing(page.get_textpage()) as text,
    ):
        for obj in page.get_objects(textpage=text):
            if obj.type == 1 and obj.extract().strip() in expected:
                positions[obj.extract().strip()] = obj.get_matrix().f
    assert positions == pytest.approx(expected, abs=0.02)


def test_monospace_glyph_ink_gaps_do_not_split_a_command_option(tmp_path):
    source = tmp_path / "option.pdf"
    c = Canvas(str(source), pagesize=(612, 792))
    t = c.beginText(42, 700)
    t.setFont(_font_names()["regular"], 12)
    t.textOut("Pass ")
    t.setFont("Courier", 9)
    t.textOut("-")
    t.textOut("f")
    t.setFont(_font_names()["regular"], 12)
    t.textOut(" option.")
    c.drawText(t)
    c.save()
    book = PdfBook(source)
    assert any("Pass -f option." == " ".join(b.plain_text().split()) for b in book.blocks)
    output = tmp_path / "output.pdf"
    book.render({"blocks": [{"id": b.id, "text": b.text} for b in book.blocks]}, output, "en")
    assert "-f" in PdfReader(output).pages[0].extract_text()


def test_wrapped_contents_moves_numbers_and_links_with_their_rows(tmp_path):
    source = tmp_path / "contents.pdf"
    c = Canvas(str(source), pagesize=(612, 792))
    c.setFont(_font_names()["regular"], 12)
    for index, label in enumerate(
        ["First section", "Second section", "Third section", "Last section"]
    ):
        baseline = 700 - index * 18
        c.drawString(42, baseline, label)
        c.drawString(510, baseline, str(index + 2))
        c.linkURL(f"https://example.test/{index}", (42, baseline - 2, 530, baseline + 12))
    c.save()
    book = PdfBook(source)
    output = tmp_path / "translated.pdf"
    translated = "Первый раздел с длинным названием о сохранении исходного содержимого репозитория и истории изменений"
    mapping = book.render(
        {
            "blocks": [
                {"id": b.id, "text": b.text.replace("First section", translated)}
                for b in book.blocks
            ]
        },
        output,
        "ru",
    )
    rows = next(item["rows"] for item in mapping["blocks"] if "rows" in item)
    assert rows[1]["baseline"] < rows[1]["source_baseline"]
    links = {
        str(a.get_object()["/A"]["/URI"]): a.get_object()
        for a in PdfReader(output).pages[0]["/Annots"]
    }
    rect = links["https://example.test/1"]["/Rect"]
    assert float(rect[1]) < rows[1]["bbox"][1] < rows[1]["bbox"][3] < float(rect[3])
    moved = next(item for item in mapping["preserved"] if item["id"] == rows[1]["number_id"])
    assert moved["bbox"][1] < rows[1]["baseline"] < moved["bbox"][3]
    assert "First section" not in PdfReader(output).pages[0].extract_text()


def test_diagram_command_follows_its_caption_without_being_translated_twice(tmp_path):
    source = tmp_path / "caption.pdf"
    c = Canvas(str(source), pagesize=(612, 792))
    c.beginForm("diagram")
    c.setFont("Helvetica", 12)
    c.drawString(42, 700, "Changes are recorded")
    c.drawString(42, 686, "in the repository using")
    c.drawString(190, 700, "Neighbouring label")
    c.setFont("Courier", 9)
    c.drawString(42, 672, "git-commit")
    c.setFont("Helvetica", 12)
    c.drawString(42, 600, "The next paragraph stays below the caption.")
    c.endForm()
    c.doForm("diagram")
    c.save()
    book = PdfBook(source)
    output = tmp_path / "translated.pdf"
    mapping = book.render(
        {
            "blocks": [
                {
                    "id": b.id,
                    "text": "Изменения фиксируются в репозитории на основе состояния индекса с помощью"
                    if "Changes" in b.text
                    else b.text,
                }
                for b in book.blocks
            ]
        },
        output,
        "ru",
    )
    item = next(item for item in mapping["blocks"] if item.get("suffix"))
    command = next(p for p in mapping["preserved"] if p["text"] == "git-commit")
    assert command["bbox"][3] < command["source_bbox"][3]
    assert item["bbox"][1] <= command["bbox"][3] <= item["bbox"][3]
    text = PdfReader(output).pages[0].extract_text()
    assert text.count("git-commit") == 1 and "Changes are recorded" not in text


def test_russian_inline_styles_keep_word_spaces_and_narrow_labels_wrap(tmp_path):
    source = tmp_path / "labels.pdf"
    f = _font_names()
    c = Canvas(str(source), pagesize=(612, 792))
    t = c.beginText(42, 700)
    t.setFont(f["regular"], 12)
    t.textOut("Use ")
    t.setFont(f["italic"], 12)
    t.textOut("trees")
    t.setFont(f["regular"], 12)
    t.textOut(" with ")
    t.setFont("Courier", 9)
    t.textOut("HEAD")
    t.setFont(f["regular"], 12)
    t.textOut(" safely.")
    c.drawText(t)
    c.setFont(f["bold"], 12)
    c.drawString(42, 600, "squash")
    c.setFont(f["regular"], 12)
    c.drawString(112, 600, "The explanation occupies the other column.")
    c.drawString(112, 586, "This keeps enough vertical space for a narrow label.")
    c.drawString(42, 500, "Another paragraph below.")
    c.save()
    book = PdfBook(source)
    output = tmp_path / "translated.pdf"
    values = [
        {
            "id": b.id,
            "text": b.text.replace("Use ", "Используйте ")
            .replace("trees", "деревья")
            .replace(" with ", " вместе с ")
            .replace(" safely.", " осторожно.")
            if "Use " in b.text
            else "squash — объединить коммиты"
            if b.text == "squash"
            else b.text,
        }
        for b in book.blocks
    ]
    mapping = book.render({"blocks": values}, output, "ru")
    text = PdfReader(output).pages[0].extract_text()
    assert "Используйте деревья вместе с HEAD осторожно." in text
    label = next(
        item
        for item in mapping["blocks"]
        if item["id"] == next(b.id for b in book.blocks if b.text == "squash")
    )
    with (
        pdfium.PdfDocument(str(output)) as d,
        closing(d[0]) as page,
        closing(page.get_textpage()) as text,
    ):
        left, bottom, right, top = label["bbox"]
        actual = text.get_text_bounded(
            left=left - 0.2, bottom=bottom - 0.2, right=right + 0.2, top=top + 0.2
        )
        assert (
            "".join(actual.replace("\x02", "").replace("-", "").split())
            == "squash—объединитькоммиты"
        )


def test_wrapped_node_label_stays_inside_the_shape_and_clear_of_its_leader(tmp_path):
    from PIL import Image, ImageDraw
    from reportlab.lib.utils import ImageReader

    source = tmp_path / "node.pdf"
    picture = Image.new("RGB", (100, 100), "white")
    ImageDraw.Draw(picture).ellipse((20, 15, 80, 85), fill="white", outline="black", width=2)
    c = Canvas(str(source), pagesize=(612, 792))
    c.line(100, 450, 220, 450)
    c.beginForm("node")
    c.drawImage(ImageReader(picture), 200, 400, 100, 100)
    c.setFont("Helvetica", 11)
    c.drawCentredString(250, 450, "Working")
    c.drawCentredString(250, 437, "Tree")
    c.endForm()
    c.doForm("node")
    c.save()
    book = PdfBook(source)
    output = tmp_path / "translated.pdf"
    book.render(
        {"blocks": [{"id": b.id, "text": "Рабочее дерево"} for b in book.blocks]}, output, "ru"
    )
    with (
        pdfium.PdfDocument(str(output)) as d,
        closing(d[0]) as page,
        closing(page.get_textpage()) as text,
    ):
        labels = [
            o
            for o in page.get_objects(textpage=text)
            if o.type == 1 and any("А" <= ch <= "я" for ch in o.extract())
        ]
        assert labels
        assert all(220 < o.get_bounds()[0] < o.get_bounds()[2] < 280 for o in labels)
