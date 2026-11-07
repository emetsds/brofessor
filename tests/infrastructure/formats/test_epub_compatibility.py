"""Synthetic EPUB 2/3 contracts; no downloaded books or model output in fixtures."""

from xml.dom import minidom
from zipfile import ZipFile

import pytest

from brofessor.infrastructure.formats.epub import DC, NCX, OPF, XHTML, XML_LANG, EpubBook
from brofessor.infrastructure.formats.epub_xml import publication_xml
from tests.helpers.epub import DTD, legacy_entries, make_book, translation


def test_xhtml_prefix_spelling_is_retained_for_reader_compatibility(tmp_path):
    # EPUB.js 0.3.88 cannot read the old serializer's newly prefixed XHTML.
    # Preserve the input spelling, as well as its namespace-expanded XML tree.
    book = make_book(tmp_path)
    output = book.render(translation(book), tmp_path / "copy.epub", "ru")
    with ZipFile(output) as archive:
        for path in book.document_paths:
            original = minidom.parseString(book.entries[path])
            rebuilt = minidom.parseString(archive.read(path))
            assert [e.tagName for e in original.getElementsByTagName("*")] == [
                e.tagName for e in rebuilt.getElementsByTagName("*")
            ]


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16"])
def test_legacy_epub_roundtrip_retains_navigation_qnames_entities_and_prose(tmp_path, encoding):
    entries = legacy_entries()
    entries["EPUB/chapter.xhtml"] = entries["EPUB/chapter.xhtml"].decode().encode(encoding)
    book = make_book(tmp_path, entries)
    value = translation(
        book,
        lambda t: (
            t.replace("First", "Первый").replace("Second", "Второй").replace("Start", "Начало")
        ),
    )
    output = book.render(value, tmp_path / "translated.epub", "ru")
    with ZipFile(output) as archive:
        chapter = publication_xml(archive.read("EPUB/chapter.xhtml"))
        original = publication_xml(entries["EPUB/chapter.xhtml"])
        assert "".join(chapter.itertext()) == "".join(original.itertext()).replace(
            "First", "Первый"
        ).replace("Second", "Второй")
        assert chapter.get(XML_LANG) == "ru"
        assert "<!DOCTYPE html" in archive.read("EPUB/chapter.xhtml").decode()
        ncx = publication_xml(archive.read("EPUB/toc.ncx"))
        original_ncx = publication_xml(entries["EPUB/toc.ncx"])
        for tag in ("navPoint", "content"):
            assert [e.attrib for e in ncx.iter(f"{{{NCX}}}{tag}")] == [
                e.attrib for e in original_ncx.iter(f"{{{NCX}}}{tag}")
            ]
        assert ncx.find(f".//{{{NCX}}}navLabel/{{{NCX}}}text").text == "Первый"
        assert ncx.find(f"{{{NCX}}}docAuthor/{{{NCX}}}text").text == "Original Author"
        package_bytes = archive.read("EPUB/package.opf")
        package = publication_xml(package_bytes)
        uid = package.find(f".//{{{DC}}}identifier").text
        assert ncx.find(f".//{{{NCX}}}meta").get("content") == uid
        assert package.find(f"{{{OPF}}}guide/{{{OPF}}}reference").get("title") == "Начало"
        assert b'xmlns:q="urn:test:types"' in package_bytes
        assert b'xsi:type="q:Language"' in package_bytes


@pytest.mark.parametrize(
    "fault",
    ["missing_toc", "wrong_toc", "unknown_dtd", "internal_subset", "entity", "utf16_entity"],
)
def test_legacy_input_does_not_bypass_navigation_or_xml_safety(tmp_path, fault):
    entries = legacy_entries()
    if fault in {"missing_toc", "wrong_toc"}:
        entries["EPUB/package.opf"] = entries["EPUB/package.opf"].replace(
            b'toc="ncx"', b"" if fault == "missing_toc" else b'toc="chapter"'
        )
    else:
        chapter = entries["EPUB/chapter.xhtml"].decode()
        if fault == "unknown_dtd":
            chapter = chapter.replace(
                "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd", "https://example.invalid/remote.dtd"
            )
        elif fault == "internal_subset":
            chapter = chapter.replace(DTD, '<!DOCTYPE html [<!ENTITY x "expanded">]>')
        else:
            chapter = chapter.replace(DTD, DTD + '<!ENTITY x SYSTEM "file:///etc/passwd">')
        entries["EPUB/chapter.xhtml"] = chapter.encode(
            "utf-16" if fault == "utf16_entity" else "utf-8"
        )
    with pytest.raises(ValueError):
        make_book(tmp_path, entries)


def test_older_projection_and_original_license_notices_survive_new_runs(tmp_path):
    chapter = f'''<html xmlns="{XHTML}" lang="en"><head><title>Book</title></head><body>
    <p>Ordinary passage.</p><div id="pg-footer" class="pg-boilerplate footer">
    <p>Original license.</p></div></body></html>'''
    current = make_book(tmp_path, {"EPUB/chapter.xhtml": chapter.encode()})
    old = EpubBook(current.source, projection_version=1)
    assert any("Original license" in b.text for b in old.blocks)
    assert not any("Original license" in b.text for b in current.blocks)
    old_prose = next(b for b in old.blocks if "Ordinary passage" in b.text)
    assert old_prose in current.blocks
    assert current.preserved_notices[0]["id"] == "pg-footer"
    output = current.render(
        translation(current, lambda t: t.replace("Ordinary passage", "Обычный текст")),
        tmp_path / "translated.epub",
        "ru",
    )
    with ZipFile(output) as archive:
        root = publication_xml(archive.read("EPUB/chapter.xhtml"))
        notice = next(e for e in root.iter() if e.get("id") == "pg-footer")
        assert "".join(notice.itertext()).strip() == "Original license."
        assert notice.get(XML_LANG) == "en"


def test_cdata_comments_and_literal_entity_spelling_survive_reconstruction(tmp_path):
    chapter = f'''{DTD}<html xmlns="{XHTML}"><head><title>Guide</title></head><body>
    <p>Before<!--preserved comment--> after <![CDATA[&nbsp;]]> &amp;nbsp; &nbsp;.</p></body></html>'''
    book = make_book(tmp_path, {"EPUB/chapter.xhtml": chapter.encode()})
    output = book.render(translation(book), tmp_path / "copy.epub", "en")
    with ZipFile(output) as archive:
        data = archive.read("EPUB/chapter.xhtml")
        assert b"<!--preserved comment-->" in data
        assert "".join(publication_xml(data).itertext()) == "".join(
            publication_xml(chapter.encode()).itertext()
        )


def test_plain_ascii_math_is_immutable_inside_mixed_prose_without_reprojecting_old_jobs(tmp_path):
    chapter = f'''<html xmlns="{XHTML}"><head><title>Math</title></head><body>
    <p>Compute square( 4 ) and <em>use cube_root(27)</em>, then square_root(9).</p>
    <p>square(25.4)</p></body></html>'''
    book = make_book(tmp_path, {"EPUB/chapter.xhtml": chapter.encode()})
    projected = "\n".join(b.text for b in book.blocks)
    assert "square(" not in projected and "cube_root(" not in projected
    protected = {value for b in book.blocks for value in b.protected.values()}
    assert {"square( 4 )", "cube_root(27)", "square_root(9)"} <= protected
    legacy = EpubBook(book.source, projection_version=2)
    assert any("square( 4 )" in b.text for b in legacy.blocks)
    result = book.render(
        translation(
            book,
            lambda t: (
                t.replace("Compute", "Вычислите")
                .replace("use", "используйте")
                .replace("and", "и")
                .replace("then", "затем")
            ),
        ),
        tmp_path / "math.epub",
        "ru",
    )
    with ZipFile(result) as archive:
        root = publication_xml(archive.read("EPUB/chapter.xhtml"))
        assert root.find(f".//{{{XHTML}}}p").text == "Вычислите square( 4 ) и "
        assert root.find(f".//{{{XHTML}}}em").text == "используйте cube_root(27)"
        assert root.find(f".//{{{XHTML}}}em").tail == ", затем square_root(9)."
        assert list(root.iter(f"{{{XHTML}}}p"))[1].text == "square(25.4)"
