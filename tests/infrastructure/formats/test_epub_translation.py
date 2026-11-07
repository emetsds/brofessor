"""Offline structural/provenance contracts; real translation quality is a separate probe."""

import hashlib
import xml.etree.ElementTree as ET
from zipfile import ZIP_STORED, ZipFile

import pytest

from brofessor.infrastructure.formats.epub import DC, OPF, XHTML, XML_LANG, EpubBook, validate_batch
from tests.helpers.epub import FIXTURE, make_book, translation


def test_reconstruction_preserves_original_assets_links_and_frozen_content(tmp_path):
    book = make_book(tmp_path)
    original = book.source.read_bytes()
    value = translation(book, lambda text: text.replace("write-ahead log", "журнал предзаписи"))
    translated = book.render(value, tmp_path / "translated.epub", "ru")
    assert book.source.read_bytes() == original
    assert book.source_hash == hashlib.sha256(original).hexdigest()
    with ZipFile(translated) as archive:
        mimetype = archive.infolist()[0]
        assert mimetype.filename == "mimetype" and mimetype.compress_type == ZIP_STORED
        assert not mimetype.extra
        assert set(archive.namelist()) == set(book.entries)
        for name in ("EPUB/style.css", "EPUB/flow.svg", "META-INF/container.xml"):
            assert archive.read(name) == book.entries[name]
        chapter = ET.fromstring(archive.read("EPUB/chapter.xhtml"))
        original_root = ET.fromstring(book.entries["EPUB/chapter.xhtml"])
        assert chapter.get("lang") == chapter.get(XML_LANG) == "ru"
        assert [node.attrib for node in chapter.iter() if node.get("href")] == [
            node.attrib for node in original_root.iter() if node.get("href")
        ]
        assert chapter.find(f".//{{{XHTML}}}em").text == "журнал предзаписи"
        for tag in (f"{{{XHTML}}}pre", "{http://www.w3.org/1998/Math/MathML}math"):
            assert ET.tostring(chapter.find(".//" + tag)) == ET.tostring(
                original_root.find(".//" + tag)
            )
        package = ET.fromstring(archive.read(book.package_path))
        original_package = ET.fromstring(book.entries[book.package_path])
        assert (
            package.find(f"{{{OPF}}}spine").attrib
            == original_package.find(f"{{{OPF}}}spine").attrib
        )
        assert [node.attrib for node in package.iter(f"{{{OPF}}}itemref")] == [
            node.attrib for node in original_package.iter(f"{{{OPF}}}itemref")
        ]
        assert package.find(f".//{{{DC}}}language").text == "ru"
        assert (
            package.find(f".//{{{DC}}}source").text
            == original_package.find(f".//{{{DC}}}identifier").text
        )
        assert (
            package.find(f".//{{{DC}}}identifier").text
            != original_package.find(f".//{{{DC}}}identifier").text
        )


def test_visible_attributes_navigation_and_footnote_text_are_translatable(tmp_path):
    book = make_book(tmp_path)
    value = translation(
        book,
        lambda text: (
            text.replace("Contents", "Оглавление")
            .replace("Three stages connected in order", "Три последовательных этапа")
            .replace("Return to the footnote reference", "Вернуться к ссылке на сноску")
            .replace("Return", "Назад")
        ),
    )
    output = book.render(value, tmp_path / "translated.epub", "ru")
    with ZipFile(output) as archive:
        nav = ET.fromstring(archive.read("EPUB/nav.xhtml"))
        chapter = ET.fromstring(archive.read("EPUB/chapter.xhtml"))
        assert nav.find(f".//{{{XHTML}}}h1").text == "Оглавление"
        assert (
            chapter.find(f".//{{{XHTML}}}img").get("alt").startswith("Три последовательных этапа")
        )
        backlink = next(node for node in chapter.iter() if node.get("href") == "#ref-1")
        assert backlink.get("aria-label") == "Вернуться к ссылке на сноску"
        assert backlink.text == "Назад"


@pytest.mark.parametrize(
    "fault", ["missing", "duplicate", "unknown", "marker", "number", "empty_span"]
)
def test_bad_response_cannot_replace_an_accepted_file(tmp_path, fault):
    book = make_book(tmp_path)
    output = book.render(translation(book), tmp_path / "accepted.epub", "en")
    accepted = output.read_bytes()
    bad = translation(book)
    if fault == "missing":
        bad["blocks"].pop()
    elif fault == "duplicate":
        bad["blocks"].append(bad["blocks"][0])
    elif fault == "unknown":
        bad["blocks"][0]["id"] = "invented-source"
    elif fault in {"marker", "empty_span"}:
        item = next(item for item in bad["blocks"] if "⟦open:1⟧must not⟦close:1⟧" in item["text"])
        item["text"] = (
            item["text"].replace("⟦close:1⟧", "⟦close:9⟧")
            if fault == "marker"
            else (item["text"].replace("must not", ""))
        )
    else:
        item = next(item for item in bad["blocks"] if "12 V" in item["text"])
        item["text"] = item["text"].replace("12 V", "120 V")
    with pytest.raises(ValueError):
        book.render(bad, output, "ru")
    assert output.read_bytes() == accepted
    assert not list(tmp_path.glob(".epub-*"))


def test_mixed_content_and_nested_lists_have_no_lost_or_duplicate_prose(tmp_path):
    chapter = f'''<html xmlns="{XHTML}" lang="en"><head><title>Mixed text</title></head>
    <body><div>Opening <em>emphasis</em> tail.<p>A paragraph.</p>After paragraph.
    <ul><li>List intro <strong>important</strong><ul><li>Nested item.</li></ul>List end.</li></ul>
    Closing.</div><p translate="no">Do not translate this <em>quotation</em>.</p></body></html>'''
    book = make_book(tmp_path, {"EPUB/chapter.xhtml": chapter.encode()})
    projected = "\n".join(
        block.text for block in book.blocks if block.document.endswith("chapter.xhtml")
    )
    for phrase in (
        "Opening",
        "emphasis",
        "tail.",
        "A paragraph.",
        "After paragraph.",
        "List intro",
        "important",
        "Nested item.",
        "List end.",
        "Closing.",
    ):
        assert projected.count(phrase) == 1
    assert "quotation" not in projected
    result = book.render(translation(book), tmp_path / "copy.epub", "ru")
    with ZipFile(result) as archive:
        root = ET.fromstring(archive.read("EPUB/chapter.xhtml"))
        assert "".join(root.itertext()) == "".join(ET.fromstring(chapter).itertext())


@pytest.mark.parametrize("alias", ["source", "symlink", "hardlink"])
def test_original_cannot_be_overwritten_even_through_an_alias(tmp_path, alias):
    book = make_book(tmp_path)
    output = book.source
    if alias != "source":
        output = tmp_path / "alias.epub"
        if alias == "symlink":
            output.symlink_to(book.source)
        else:
            output.hardlink_to(book.source)
    with pytest.raises(ValueError, match="original"):
        book.render(translation(book), output, "ru")
    assert hashlib.sha256(book.source.read_bytes()).hexdigest() == book.source_hash


def test_original_snapshot_and_stable_locators_survive_later_source_changes(tmp_path):
    book = make_book(tmp_path)
    assert book.blocks == EpubBook(book.source).blocks
    book.source.write_bytes(b"a later external change")
    result = book.render(translation(book), tmp_path / "translated.epub", "ru")
    with ZipFile(result) as archive:
        assert archive.read("EPUB/flow.svg") == book.entries["EPUB/flow.svg"]
    assert book.source.read_bytes() == b"a later external change"


@pytest.mark.parametrize(
    "kind",
    [
        "script",
        "event_handler",
        "javascript_link",
        "doctype",
        "fixed",
        "encrypted",
        "missing_asset",
        "ncx",
    ],
)
def test_unsupported_or_unsafe_input_fails_explicitly(tmp_path, kind):
    changes = {}
    chapter = (FIXTURE / "EPUB/chapter.xhtml").read_bytes()
    package = (FIXTURE / "EPUB/package.opf").read_bytes()
    if kind == "script":
        changes["EPUB/chapter.xhtml"] = chapter.replace(b"<body>", b"<body><script>bad()</script>")
    elif kind == "event_handler":
        changes["EPUB/chapter.xhtml"] = chapter.replace(b"<body>", b'<body onload="bad()">')
    elif kind == "javascript_link":
        changes["EPUB/chapter.xhtml"] = chapter.replace(
            b'href="#note-1"', b'href="javascript:bad()"'
        )
    elif kind == "doctype":
        changes["EPUB/chapter.xhtml"] = chapter.replace(
            b"<html", b'<!DOCTYPE html [<!ENTITY x "bad">]><html', 1
        )
    elif kind == "fixed":
        changes["EPUB/package.opf"] = package.replace(
            b"</metadata>", b'<meta property="rendition:layout">pre-paginated</meta></metadata>'
        )
    elif kind == "encrypted":
        changes["META-INF/encryption.xml"] = b"<encryption/>"
    elif kind == "missing_asset":
        changes["EPUB/package.opf"] = package.replace(b'"flow.svg"', b'"absent.svg"')
    else:
        changes["EPUB/package.opf"] = package.replace(
            b"</manifest>",
            b'<item id="ncx" href="nav.ncx" media-type="application/x-dtbncx+xml"/></manifest>',
        )
        changes["EPUB/nav.ncx"] = b"<ncx/>"
    with pytest.raises(ValueError):
        make_book(tmp_path, changes)


def test_decimal_separator_change_preserves_value_but_dropped_number_fails(tmp_path):
    book = make_book(tmp_path)
    value = translation(book, lambda text: text.replace("2.5", "2,5"))
    validate_batch(value, book.blocks)
    item = next(item for item in value["blocks"] if "2,5 m" in item["text"])
    item["text"] = item["text"].replace("2,5 m", "m")
    with pytest.raises(ValueError, match="numeric"):
        validate_batch(value, book.blocks)


def test_numeric_sign_is_not_lost_or_added(tmp_path):
    book = make_book(tmp_path)
    with pytest.raises(ValueError, match="numeric"):
        validate_batch(translation(book, lambda text: text.replace("2.5", "-2.5")), book.blocks)


def test_leading_decimal_zero_and_locale_preserve_value_and_precision(tmp_path):
    chapter = f'''<html xmlns="{XHTML}"><head><title>Decimals</title></head>
    <body><p>Input .340 V; gain −.08; output .0272 V.</p></body></html>'''
    book = make_book(tmp_path, {"EPUB/chapter.xhtml": chapter.encode()})
    validate_batch(
        translation(
            book,
            lambda t: (
                t.replace(".340", "0,340").replace("−.08", "-0,08").replace(".0272", "0,0272")
            ),
        ),
        book.blocks,
    )
    for changed in ("340", "0.34", "-0.340", "0.0340"):
        with pytest.raises(ValueError, match="numeric"):
            validate_batch(translation(book, lambda t: t.replace(".340", changed)), book.blocks)


def test_translated_language_attributes_do_not_relabel_immutable_code_or_quotes(tmp_path):
    chapter = f'''<html xmlns="{XHTML}" lang="en"><head><title>Language</title></head>
    <body><p lang="en">Text <em xml:lang="en">emphasis</em>.</p>
    <p translate="no" lang="en">Quotation.</p><pre lang="en">code</pre></body></html>'''
    book = make_book(tmp_path, {"EPUB/chapter.xhtml": chapter.encode()})
    output = book.render(translation(book), tmp_path / "translated.epub", "ru")
    with ZipFile(output) as archive:
        root = ET.fromstring(archive.read("EPUB/chapter.xhtml"))
        paragraphs = list(root.iter(f"{{{XHTML}}}p"))
        assert paragraphs[0].get("lang") == "ru"
        assert paragraphs[0].find(f"{{{XHTML}}}em").get(XML_LANG) == "ru"
        assert paragraphs[1].get("lang") == "en"
        assert root.find(f".//{{{XHTML}}}pre").get("lang") == "en"


def test_model_cannot_inject_markup_or_change_links(tmp_path):
    book = make_book(tmp_path)
    value = translation(
        book, lambda text: text.replace("Contents", '<script src="https://example.org/"/>')
    )
    output = book.render(value, tmp_path / "escaped.epub", "ru")
    with ZipFile(output) as archive:
        root = ET.fromstring(archive.read("EPUB/nav.xhtml"))
        assert not list(root.iter(f"{{{XHTML}}}script"))
        assert root.find(f".//{{{XHTML}}}h1").text == '<script src="https://example.org/"/>'
