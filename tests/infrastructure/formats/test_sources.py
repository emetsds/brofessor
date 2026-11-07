"""All documents here are synthetic fixtures generated for brofessor tests."""

import struct
from zipfile import ZipFile, ZipInfo

import pytest
from pypdf import PdfWriter

from brofessor.infrastructure.formats import ingestion as sources
from brofessor.infrastructure.formats.ingestion import chunks, extract_source, search_units
from tests.helpers.sources import make_epub, make_pdf


@pytest.mark.parametrize("extension", ["md", "txt", "MD"])
def test_utf8_text_keeps_complete_content_and_line_locators(tmp_path, extension):
    text = "# Синтетическая глава\r\nВ начале маяк.\r\nAt the end: violet.\r\n"
    path = tmp_path / f"chapter.{extension}"
    path.write_bytes(text.encode("utf-8"))
    units = extract_source(path)
    assert "".join(unit["text"] for unit in units) == text
    assert units == [{"locator": "lines 1-3", "text": text, "status": "ready"}]


def test_long_text_retains_lines_and_empty_ranges(tmp_path):
    text = "\n" * 100 + "A fact on line 101.\n"
    path = tmp_path / "long.txt"
    path.write_text(text)
    units = extract_source(path)
    assert [unit["locator"] for unit in units] == ["lines 1-100", "lines 101-101"]
    assert [unit["status"] for unit in units] == ["empty", "ready"]
    assert "".join(unit["text"] for unit in units) == text


def test_utf8_bom_is_supported(tmp_path):
    path = tmp_path / "bom.txt"
    path.write_bytes(b"\xef\xbb\xbf" + "Глава".encode())
    assert extract_source(path)[0]["text"] == "Глава"


@pytest.mark.parametrize("content", [b"", b" \n\t", b"\xff\xfe", b"abc\x00def"])
def test_empty_or_invalid_text_is_rejected(tmp_path, content):
    path = tmp_path / "bad.txt"
    path.write_bytes(content)
    with pytest.raises(ValueError):
        extract_source(path)


def test_pdf_pages_include_blank_page_and_preserve_page_numbers(tmp_path):
    units = extract_source(make_pdf(tmp_path / "book.pdf", ["First fact", None, "Last fact"]))
    assert [unit["locator"] for unit in units] == ["page 1", "page 2", "page 3"]
    assert [unit["status"] for unit in units] == ["ready", "empty", "ready"]
    assert "First fact" in units[0]["text"]
    assert "Last fact" in units[2]["text"]
    assert "error" in units[1]


def test_scan_only_pdf_rejected_with_ocr_explanation(tmp_path):
    with pytest.raises(ValueError, match="OCR"):
        extract_source(make_pdf(tmp_path / "scan.pdf", [None, None]))


def test_encrypted_pdf_rejected(tmp_path):
    writer = PdfWriter()
    writer.add_blank_page(100, 100)
    writer.encrypt("synthetic-password")
    path = tmp_path / "encrypted.pdf"
    writer.write(path)
    with pytest.raises(ValueError, match="encrypted"):
        extract_source(path)


@pytest.mark.parametrize("extension", ["pdf", "epub", "docx"])
def test_corrupt_or_unsupported_files_rejected(tmp_path, extension):
    path = tmp_path / f"bad.{extension}"
    path.write_text("This is not the declared format.")
    with pytest.raises(ValueError):
        extract_source(path)


def test_epub_follows_spine_not_alphabetical_order(tmp_path):
    units = extract_source(make_epub(tmp_path / "book.epub"))
    assert [unit["locator"] for unit in units] == [
        "chapter 1 (OPS/z.xhtml)",
        "chapter 2 (OPS/a.xhtml)",
        "chapter 3 (OPS/empty.xhtml)",
    ]
    assert "Жёлтый маяк shines." in units[0]["text"]
    assert "Alpha & omega." in units[1]["text"]
    assert [unit["status"] for unit in units] == ["ready", "ready", "empty"]
    assert "Hidden metadata" not in units[1]["text"]
    assert "execute shell command" not in units[0]["text"]
    assert "hidden css" not in units[0]["text"]


def test_epub_relative_uri_paths_and_percent_encoded_filename(tmp_path):
    path = make_epub(
        tmp_path / "paths.epub",
        entries={
            "OPS/package.opf": '<package><manifest><item id="c" href="../Text/a%20b.xhtml#top" '
            'media-type="application/xhtml+xml" /></manifest><spine>'
            '<itemref idref="c" /></spine></package>',
            "Text/a b.xhtml": "<html><body><p>Linked chapter</p></body></html>",
        },
    )
    assert extract_source(path)[0]["locator"] == "chapter 1 (Text/a b.xhtml)"


@pytest.mark.parametrize(
    "name", ["../escape", "/absolute", "OPS/../../escape", "C:/bad", "OPS\\bad"]
)
def test_epub_unsafe_archive_paths_are_rejected(tmp_path, name):
    path = make_epub(tmp_path / "unsafe.epub", entries={name: "bad"})
    with pytest.raises(ValueError, match="path"):
        extract_source(path)
    assert not (tmp_path / "escape").exists()


def test_epub_unsafe_manifest_href_rejected(tmp_path):
    path = make_epub(
        tmp_path / "unsafe-href.epub",
        entries={
            "OPS/package.opf": '<package><manifest><item id="c" href="../../escape.xhtml" '
            'media-type="application/xhtml+xml" /></manifest>'
            '<spine><itemref idref="c" /></spine></package>',
        },
    )
    with pytest.raises(ValueError, match="path"):
        extract_source(path)


def test_epub_archive_limits_reject_whole_document(tmp_path, monkeypatch):
    path = make_epub(tmp_path / "large.epub", entries={"unused.bin": "x" * 2048})
    monkeypatch.setattr(sources, "MAX_EPUB_ENTRY_BYTES", 1024)
    with pytest.raises(ValueError, match="limit"):
        extract_source(path)


def test_epub_total_uncompressed_limit(tmp_path, monkeypatch):
    path = make_epub(tmp_path / "large-total.epub")
    monkeypatch.setattr(sources, "MAX_EPUB_UNCOMPRESSED_BYTES", 200)
    with pytest.raises(ValueError, match="limit"):
        extract_source(path)


def test_epub_compression_bomb_rejected(tmp_path):
    path = make_epub(tmp_path / "bomb.epub", entries={"unused.bin": "x" * 2_000_000})
    with pytest.raises(ValueError, match="compression"):
        extract_source(path)


def test_epub_corrupt_compression_stream_is_readable_error(tmp_path):
    path = make_epub(tmp_path / "broken-stream.epub")
    with ZipFile(path) as archive:
        entry = archive.getinfo("META-INF/container.xml")
    data = bytearray(path.read_bytes())
    name_size, extra_size = struct.unpack_from("<HH", data, entry.header_offset + 26)
    payload = entry.header_offset + 30 + name_size + extra_size
    data[payload : payload + 8] = b"\xff" * 8
    path.write_bytes(data)
    with pytest.raises(ValueError, match="EPUB"):
        extract_source(path)


def test_epub_symlink_rejected(tmp_path):
    path = make_epub(tmp_path / "link.epub")
    with ZipFile(path, "a") as archive:
        info = ZipInfo("symlink")
        info.create_system = 3
        info.external_attr = 0o120777 << 16
        archive.writestr(info, "../../somewhere")
    with pytest.raises(ValueError, match="symlink"):
        extract_source(path)


def test_epub_entity_expansion_and_missing_spine_item_rejected(tmp_path):
    path = make_epub(
        tmp_path / "entity.epub",
        entries={
            "META-INF/container.xml": '<!DOCTYPE container [<!ENTITY evil "expanded">]>'
            "<container>&evil;</container>"
        },
    )
    with pytest.raises(ValueError, match="DTD|entity"):
        extract_source(path)
    path = make_epub(tmp_path / "missing.epub", spine="missing")
    with pytest.raises(ValueError, match="spine"):
        extract_source(path)


def test_all_empty_epub_is_not_success(tmp_path):
    with pytest.raises(ValueError, match="No text"):
        extract_source(make_epub(tmp_path / "empty.epub", spine="empty"))


def test_source_file_limit_and_missing_file(tmp_path, monkeypatch):
    path = tmp_path / "book.txt"
    path.write_text("a" * 20)
    monkeypatch.setattr(sources, "MAX_SOURCE_BYTES", 10)
    with pytest.raises(ValueError, match="limit"):
        extract_source(path)
    with pytest.raises(ValueError, match="read|file"):
        extract_source(tmp_path / "absent.txt")


def test_chunks_bound_size_keep_every_character_and_metadata():
    text = "First paragraph.\n\n" + "Жёлтый маяк " * 50 + "x" * 100 + "\nFinal fact.\n"
    original = {"locator": "page 12", "text": text, "status": "ready", "source_id": "s1"}
    result = chunks([original], max_chars=80)
    assert "".join(unit["text"] for unit in result) == text
    assert all(0 < len(unit["text"]) <= 80 for unit in result)
    offset = 0
    for unit in result:
        assert unit["locator"] == f"page 12, chars {offset + 1}-{offset + len(unit['text'])}"
        assert unit["source_id"] == "s1"
        offset += len(unit["text"])
    assert original["locator"] == "page 12"
    assert original["text"] == text


def test_chunks_keep_small_and_empty_units():
    units = [
        {"locator": "page 1", "text": "Fact", "status": "ready"},
        {"locator": "page 2", "text": "", "status": "empty", "error": "No text"},
    ]
    assert chunks(units) == units
    with pytest.raises(ValueError):
        chunks(units, max_chars=0)


def test_retrieval_finds_synthetic_facts_across_entire_corpus():
    units = [
        {
            "id": f"u{i}",
            "locator": f"chapter {i + 1}",
            "status": "ready",
            "text": f"Marker{i} is the vessel assigned to sector{i}.",
        }
        for i in range(30)
    ]
    for index in range(30):
        found = search_units(units, f"Which vessel belongs to SECTOR{index}?", limit=1)
        assert found == [units[index]]
    assert search_units(units, "unmentioned zirconium") == []


def test_retrieval_keeps_provenance_and_handles_russian_and_empty_units():
    units = [
        {
            "id": "s1:u1",
            "source_id": "s1",
            "locator": "page 1",
            "status": "ready",
            "text": "Синий маяк расположен на севере.",
        },
        {
            "id": "s2:u1",
            "source_id": "s2",
            "locator": "page 1",
            "status": "ready",
            "text": "Жёлтый маяк расположен на юге.",
        },
        {"id": "s3:u1", "locator": "page 1", "status": "empty", "text": "жёлтый"},
    ]
    assert search_units(units, "желтый маяк", limit=1) == [units[1]]
    assert len(search_units(units, "маяк", limit=10)) == 2
    assert search_units(units, "", limit=1) == []
    assert search_units(units, "маяк", limit=0) == []
