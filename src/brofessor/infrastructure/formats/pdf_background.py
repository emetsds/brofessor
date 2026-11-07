"""Remove selected PDF text shows while preserving cursor advance and resources.

Unlike regenerating the entire page through PDFium, this leaves original font
encodings, Form streams and graphics intact. Only selected strings become TJ
positioning numbers; source text is actually removed, not painted invisibly.
"""

from pypdf import PdfWriter
from pypdf.generic import (
    ArrayObject,
    ContentStream,
    DecodedStreamObject,
    FloatObject,
    TextStringObject,
)
from reportlab.pdfbase import pdfmetrics

SHOW = (b"Tj", b"TJ", b"'", b'"')


def text_keys(page, reader, seen_forms, *, check=lambda: None):
    keys = []

    def visit(data, resources, path=()):
        if len(path) > 15:
            raise ValueError("PDF Form nesting exceeds the supported limit")
        stream = ContentStream(data, reader)
        font, size, charspace, wordspace = None, 0, 0, 0
        stack = []
        for index, (args, op) in enumerate(stream.operations):
            if index % 64 == 0:
                check()
            if op == b"q":
                stack.append((font, size, charspace, wordspace))
            elif op == b"Q" and stack:
                font, size, charspace, wordspace = stack.pop()
            elif op == b"Tf":
                font, size = resources["/Font"][args[0]], float(args[1])
            elif op == b"Tc":
                charspace = float(args[0])
            elif op == b"Tw":
                wordspace = float(args[0])
            if op in SHOW and any(bool(x) for x in (args[0] if op == b"TJ" else [args[-1]])):
                if font is None:
                    raise ValueError("PDF text without an explicit local font is unsupported")
                # Check the removal contract before any model sees the book.
                # Composite encodings need a separate cursor-advance decoder.
                for value in args[0] if op == b"TJ" else [args[-1]]:
                    if isinstance(value, (str, bytes)):
                        _advance(value, font, size, charspace, wordspace)
                keys.append((*path, index))
            elif op == b"Do":
                obj = resources["/XObject"][args[0]]
                if obj.get("/Subtype") == "/Form":
                    before = len(keys)
                    visit(obj, obj.get("/Resources", resources), (*path, index))
                    if len(keys) > before:
                        identity = obj.indirect_reference
                        if identity in seen_forms:
                            raise ValueError("Shared text Form XObjects are unsupported")
                        seen_forms.add(identity)

    visit(page.get_contents(), page["/Resources"])
    return keys


def _bytes(value):
    return value.original_bytes if isinstance(value, TextStringObject) else bytes(value)


def _advance(value, font, size, charspace, wordspace):
    data = _bytes(value)
    if font.get("/Subtype") == "/Type0":
        raise ValueError("Position-preserving PDF text removal requires a simple font")
    widths = font.get("/Widths")
    if widths:
        widths = widths.get_object()
        first = font.get("/FirstChar", 0)
        descriptor = font.get("/FontDescriptor")
        missing = descriptor.get_object().get("/MissingWidth", 0) if descriptor else 0
        width = sum(
            float(widths[n - first]) if 0 <= n - first < len(widths) else float(missing)
            for n in data
        )
    else:
        name = str(font["/BaseFont"]).lstrip("/").split("+")[-1]
        try:
            width = pdfmetrics.stringWidth(data.decode("latin-1"), name, 1000)
        except KeyError as error:
            raise ValueError(f"PDF font lacks usable widths: {name}") from error
    if not size:
        raise ValueError("Cannot remove zero-sized PDF text")
    return -(width + 1000 * (len(data) * charspace + data.count(b" ") * wordspace) / size)


def remove_text(data, page_keys, regions, *, check=lambda: None):
    writer = PdfWriter(clone_from=data)
    for number, page in enumerate(writer.pages, 1):
        check()
        selected = {
            page_keys[number - 1][i]
            for r in regions.values()
            if r.page == number
            for i in r.text_ordinals
        }

        def visit(data, resources, path=()):
            content = ContentStream(data, writer)
            result = []
            font, size, charspace, wordspace = None, 0, 0, 0
            stack = []
            for index, (args, op) in enumerate(content.operations):
                if index % 64 == 0:
                    check()
                if op == b"q":
                    stack.append((font, size, charspace, wordspace))
                elif op == b"Q" and stack:
                    font, size, charspace, wordspace = stack.pop()
                elif op == b"Tf":
                    font, size = resources["/Font"][args[0]], float(args[1])
                elif op == b"Tc":
                    charspace = float(args[0])
                elif op == b"Tw":
                    wordspace = float(args[0])
                if op == b"Do":
                    obj = resources["/XObject"][args[0]]
                    if obj.get("/Subtype") == "/Form" and any(
                        k[: len(path) + 1] == (*path, index) for k in selected
                    ):
                        updated = DecodedStreamObject()
                        updated.update(
                            {
                                k: v
                                for k, v in obj.items()
                                if k not in ("/Length", "/Filter", "/DecodeParms")
                            }
                        )
                        updated.set_data(
                            visit(obj, obj.get("/Resources", resources), (*path, index)).get_data()
                        )
                        resources["/XObject"][args[0]] = writer._add_object(updated)
                if (*path, index) in selected:
                    if op in (b"'", b'"'):
                        if op == b'"':
                            wordspace, charspace = float(args[0]), float(args[1])
                            result.extend([([args[0]], b"Tw"), ([args[1]], b"Tc")])
                        result.append(([], b"T*"))
                    array = args[0] if op == b"TJ" else [args[-1]]
                    replacement = ArrayObject(
                        FloatObject(_advance(v, font, size, charspace, wordspace))
                        if isinstance(v, (str, bytes))
                        else v
                        for v in array
                    )
                    result.append(([replacement], b"TJ"))
                else:
                    result.append((args, op))
            content.operations = result
            return content

        page.replace_contents(visit(page.get_contents(), page["/Resources"]))
    return writer
