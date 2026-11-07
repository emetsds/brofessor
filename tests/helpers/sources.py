"""Small original EPUB and PDF inputs for import/provenance checks."""

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, StreamObject


def make_epub(path: Path, *, entries=None, spine="later first empty") -> Path:
    files = {
        "META-INF/container.xml": (
            '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            '<rootfiles><rootfile full-path="OPS/package.opf" /></rootfiles></container>'
        ),
        "OPS/package.opf": (
            '<package xmlns="http://www.idpf.org/2007/opf"><manifest>'
            '<item id="first" href="a.xhtml" media-type="application/xhtml+xml" />'
            '<item id="later" href="z.xhtml" media-type="application/xhtml+xml" />'
            '<item id="empty" href="empty.xhtml" media-type="application/xhtml+xml" />'
            "</manifest><spine>"
            + "".join(f'<itemref idref="{item}" />' for item in spine.split())
            + "</spine></package>"
        ),
        "OPS/a.xhtml": "<html><head><title>Hidden metadata</title></head>"
        "<body><h1>Second chapter</h1><p>Alpha &amp; omega.</p></body></html>",
        "OPS/z.xhtml": "<html><body><h1>First chapter</h1>"
        "<p>Жёлтый <em>маяк</em> shines.</p>"
        "<script>execute shell command</script><style>hidden css</style></body></html>",
        "OPS/empty.xhtml": "<html><head><title>No body text</title></head><body/></html>",
    }
    files.update(entries or {})
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        for name, value in files.items():
            archive.writestr(name, value)
    return path


def make_pdf(path: Path, texts: list[str | None]) -> Path:
    writer = PdfWriter()
    for text in texts:
        page = writer.add_blank_page(300, 300)
        if text is not None:
            font = DictionaryObject(
                {
                    NameObject("/Type"): NameObject("/Font"),
                    NameObject("/Subtype"): NameObject("/Type1"),
                    NameObject("/BaseFont"): NameObject("/Helvetica"),
                }
            )
            page[NameObject("/Resources")] = DictionaryObject(
                {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
            )
            stream = StreamObject()
            stream.set_data(f"BT /F1 12 Tf 10 200 Td ({text}) Tj ET".encode("ascii"))
            page[NameObject("/Contents")] = writer._add_object(stream)
    writer.write(path)
    return path
