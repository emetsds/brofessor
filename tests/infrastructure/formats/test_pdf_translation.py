import hashlib
from io import BytesIO

import pytest
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen.canvas import Canvas

from brofessor.infrastructure.formats.pdf import PdfBook
from tests.helpers.pdf import make_pdf


def identity(book):
    return {"blocks": [{"id": b.id, "text": b.text} for b in book.blocks]}


def test_text_projection_accounts_for_columns_cells_footnotes_and_frozen_content(tmp_path):
    source = make_pdf(tmp_path / "source.pdf")
    book = PdfBook(source)
    text = "\n".join(b.text for b in book.blocks)
    assert "Do not acknowledge a record before the durable commit." in text
    assert "Only this installation was tested." in text
    assert "Required action" in text and "this experiment only" in text
    assert {b.document for b in book.blocks} == {"page:1", "page:2"}
    assert all(b.locator.startswith("page ") for b in book.blocks)
    assert {p["text"] for p in book.preserved} >= {"V = Q / C", "commit(record_id)", "1", "2"}
    # Each accepted region remains on its side of the table's central rule.
    for region in book._regions.values():
        if 350 < region.bbox[1] < 424 and region.bbox[0] < 306:
            assert region.box[2] < 306


def test_pdf_reconstruction_preserves_graphics_pages_and_original_snapshot(tmp_path):
    source = make_pdf(tmp_path / "source.pdf")
    before = source.read_bytes()
    book = PdfBook(source)
    output = tmp_path / "translated.pdf"
    report = book.render(identity(book), output, "en")
    result = PdfReader(output)
    assert len(result.pages) == len(PdfReader(source).pages)
    assert result.trailer["/Root"]["/Lang"] == "en"
    assert report["source_sha256"] == hashlib.sha256(before).hexdigest()
    for original, translated in zip(PdfReader(source).pages, result.pages, strict=True):
        assert [i.data for i in original.images] == [i.data for i in translated.images]
        assert "V = Q / C" in translated.extract_text()
        assert "commit(record_id)" in translated.extract_text()
        assert "Reliable sensor ingestion" in translated.extract_text()
    assert source.read_bytes() == before


def test_overflow_leaves_previous_output_and_original_untouched(tmp_path):
    book = PdfBook(make_pdf(tmp_path / "source.pdf", pages=1))
    output = tmp_path / "translated.pdf"
    book.render(identity(book), output, "en")
    before = output.read_bytes()
    value = identity(book)
    value["blocks"][0]["text"] = "Unbounded expansion " * 3000
    with pytest.raises(ValueError, match="overflows"):
        book.render(value, output, "en")
    assert output.read_bytes() == before
    with pytest.raises(ValueError, match="original"):
        book.render(identity(book), book.source, "en")


@pytest.mark.parametrize("fault", ["rotation", "image", "invisible", "clip"])
def test_unsupported_pages_are_named_before_translation(tmp_path, fault):
    source = make_pdf(tmp_path / "source.pdf", pages=1)
    writer = PdfWriter(clone_from=source)
    if fault == "rotation":
        writer.pages[0].rotate(90)
    else:
        stream = BytesIO()
        canvas = Canvas(stream, pagesize=(612, 792))
        if fault == "image":
            from PIL import Image
            from reportlab.lib.utils import ImageReader

            canvas.drawImage(ImageReader(Image.new("RGB", (20, 20), "red")), 42, 42)
        elif fault == "clip":
            path = canvas.beginPath()
            path.rect(42, 680, 50, 40)
            canvas.clipPath(path, stroke=0)
            canvas.drawString(42, 700, "Partly clipped text")
        else:
            text = canvas.beginText(42, 700)
            text.setTextRenderMode(3)
            text.textLine("Hidden OCR")
            canvas.drawText(text)
        canvas.showPage()
        canvas.save()
        writer = PdfWriter(clone_from=stream)
    writer.write(source)
    with pytest.raises(ValueError, match="page 1"):
        PdfBook(source)


def test_cancellation_before_publication_keeps_previous_pdf(tmp_path, monkeypatch):
    from brofessor.infrastructure.text.runners import CancelledError

    book = PdfBook(make_pdf(tmp_path / "source.pdf", pages=1))
    output = tmp_path / "translated.pdf"
    book.render(identity(book), output, "en")
    previous = output.read_bytes()
    write = PdfWriter.write
    stopped = False

    def write_then_cancel(self, stream):
        nonlocal stopped
        result = write(self, stream)
        stopped = True
        return result

    def check():
        if stopped:
            raise CancelledError("controlled cancellation after temporary write")

    monkeypatch.setattr(PdfWriter, "write", write_then_cancel)
    with pytest.raises(CancelledError):
        book.render(identity(book), output, "en", check=check)
    assert output.read_bytes() == previous
    assert not list(tmp_path.glob(".translation-*.pdf"))


def test_monospaced_prose_is_translated_and_missing_glyph_is_rejected(tmp_path):
    source = tmp_path / "mono.pdf"
    canvas = Canvas(str(source), pagesize=(612, 792))
    canvas.setFont("Courier", 12)
    canvas.drawString(42, 700, "Do not acknowledge before the durable commit.")
    canvas.save()
    book = PdfBook(source)
    assert any("Do not acknowledge" in b.text for b in book.blocks)
    value = identity(book)
    value["blocks"][0]["text"] = "Нет подходящего символа: \U0010ffff"
    with pytest.raises(ValueError, match="glyph"):
        book.render(value, tmp_path / "translated.pdf", "ru")


def test_original_link_destinations_and_outlines_survive_reconstruction(tmp_path):
    source = make_pdf(tmp_path / "linked.pdf", links=True)
    book = PdfBook(source)
    output = tmp_path / "translated.pdf"
    book.render(identity(book), output, "en")

    def navigation(reader):
        result = []
        for number, page in enumerate(reader.pages):
            for reference in page.get("/Annots", []):
                annotation = reference.get_object()
                if "/Dest" in annotation:
                    target = annotation["/Dest"][0]
                    destination = next(
                        i for i, p in enumerate(reader.pages) if p.indirect_reference == target
                    )
                else:
                    destination = annotation["/A"]["/URI"]
                result.append((number, destination, tuple(annotation["/Rect"])))
        return result, [reader.get_destination_page_number(item) for item in reader.outline]

    assert navigation(PdfReader(source)) == navigation(PdfReader(output))
