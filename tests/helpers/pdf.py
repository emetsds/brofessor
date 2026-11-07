"""Original MIT PDF fixtures, generated locally; no books or external images."""

from io import BytesIO

from PIL import Image, ImageDraw
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Paragraph

from brofessor.infrastructure.formats.pdf import _PDF_LOCK, _font_names
from brofessor.infrastructure.storage.workspace import Workspace
from tests.helpers.books import payloads


def make_pdf(path, *, pages=2, links=False):
    with _PDF_LOCK:
        fonts = _font_names()
        canvas = Canvas(str(path), pagesize=(612, 792), invariant=True)
        canvas.setTitle("Reliable sensor ingestion")

        def paragraph(text, x, top, width, size=11, style="regular"):
            value = Paragraph(
                text,
                ParagraphStyle("source", fontName=fonts[style], fontSize=size, leading=size * 1.3),
            )
            _, height = value.wrap(width, 700)
            value.drawOn(canvas, x, top - height)
            return top - height

        for page in range(pages):
            if links:
                canvas.bookmarkPage(f"page-{page}")
                canvas.addOutlineEntry(f"Page {page + 1}", f"page-{page}")
                canvas.linkURL("https://example.org/sensor", (42, 728, 300, 752), relative=False)
                canvas.linkRect(
                    "", f"page-{(page + 1) % pages}", (42, 100, 570, 122), relative=False
                )
            paragraph("Reliable sensor ingestion", 42, 752, 528, 19, "bold")
            paragraph("Recovery and acknowledgement", 42, 712, 240, 13, "bold")
            paragraph(
                "The database log records each accepted observation. Do not acknowledge "
                "a record before the durable commit. The checkpoint limits replay work, "
                "but does not guarantee protection from destroyed storage.",
                42,
                681,
                240,
            )
            paragraph(
                "The field team measures hydraulic head at 3.5 m. The head of the team "
                "checks the sensor. A wooden log floating in the river is not part of "
                "the database log. The delay must not exceed 20 ms.",
                42,
                555,
                240,
            )
            paragraph("Limits of this experiment", 330, 712, 240, 13, "bold")
            paragraph(
                "Only this installation was tested. A missing acknowledgement may cause "
                "a retry, even if the write succeeded. A retry must not create another "
                "observation with the same identifier.",
                330,
                681,
                240,
            )
            paragraph(
                "Use the journal for recovery; use the measurement as evidence. The "
                "observed rate was 5 V/s. An unconfirmed record may be lost. This result "
                "does not establish a universal reliability guarantee.",
                330,
                555,
                240,
            )
            # A ruled, two-column table: translated cells must not cross its rules.
            for y in (424, 387, 350):
                canvas.line(42, y, 570, y)
            for x in (42, 306, 570):
                canvas.line(x, 350, x, 424)
            paragraph("Condition", 50, 416, 246, 11, "bold")
            paragraph("Required action", 314, 416, 246, 11, "bold")
            paragraph("Commit is not durable", 50, 379, 246)
            paragraph("Do not acknowledge", 314, 379, 246)
            paragraph("A simple model", 42, 322, 240, 12, "bold")
            canvas.setFont("Courier", 11)
            canvas.drawString(42, 280, "V = Q / C")
            canvas.drawString(42, 254, "commit(record_id)")
            image = Image.new("RGB", (160, 75), "#e7edf4")
            draw = ImageDraw.Draw(image)
            draw.rectangle((10, 20, 60, 55), fill="#327b9b")
            draw.line((60, 37, 110, 37), fill="black", width=3)
            draw.ellipse((110, 20, 145, 55), fill="#c37842")
            image_bytes = BytesIO()
            image.save(image_bytes, format="PNG")
            canvas.drawImage(ImageReader(image_bytes), 330, 230, width=240, height=112.5)
            paragraph("Figure: the sensor and its durable store.", 330, 210, 240, 9)
            canvas.line(42, 135, 570, 135)
            paragraph(
                "Note: the 20 ms bound applies to this experiment only. Original code "
                "and formula are retained; labels inside raster images are not translated.",
                42,
                122,
                528,
                8,
            )
            canvas.setFont(fonts["regular"], 9)
            canvas.drawCentredString(306, 42, str(page + 1))
            canvas.showPage()
        canvas.save()
    return path


class PdfModel:
    def __init__(self):
        self.calls = []
        self.fail = False

    def __call__(self, prompt, schema, provider, model=None, **kwargs):
        self.calls.append(schema["title"])
        packets = payloads(prompt)
        if schema["title"] in ("GlossaryBatch", "GlossaryReviewBatch"):
            return {"assessed_blocks": [b["id"] for b in packets[-1]["blocks"]], "terms": []}
        if self.fail:
            raise RuntimeError("controlled translation failure")
        return {
            "blocks": [
                {"id": b["id"], "text": b["text"], "targets": []} for b in packets[0]["blocks"]
            ]
        }


def workspace_with_pdf(tmp_path, monkeypatch):
    workspace = Workspace(tmp_path / "workspace")
    source = workspace.add_source(make_pdf(tmp_path / "book.pdf", pages=1))
    model = PdfModel()
    monkeypatch.setattr("brofessor.infrastructure.text.runners.generate", model)
    monkeypatch.setattr("brofessor.application.worker.ensure_worker", lambda _: None)
    return workspace, source, model
