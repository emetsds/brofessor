"""Original EPUB 2/3 fixture builders and identity translations."""

from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

from brofessor.infrastructure.formats.epub import NCX, XHTML, EpubBook
from tests.helpers.paths import FIXTURES

FIXTURE = FIXTURES / "translation"


def make_book(tmp_path, replacements=None):
    entries = {
        path.relative_to(FIXTURE).as_posix(): path.read_bytes()
        for path in FIXTURE.rglob("*")
        if path.is_file() and path.name not in {"mimetype", "README.md"}
    }
    entries.update(replacements or {})
    path = tmp_path / "original.epub"
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("mimetype", b"application/epub+zip", compress_type=ZIP_STORED)
        for name, data in entries.items():
            archive.writestr(name, data)
    return EpubBook(path)


def translation(book, transform=lambda text: text):
    return {"blocks": [{"id": block.id, "text": transform(block.text)} for block in book.blocks]}


DTD = "<!DOCTYPE html PUBLIC '-//W3C//DTD XHTML 1.1//EN' 'http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd'>"


def epub2_entries():
    package = (FIXTURE / "EPUB/package.opf").read_text().replace('version="3.0"', 'version="2.0"')
    package = (
        package.replace("<spine>", '<spine toc="ncx">')
        .replace(
            "</manifest>",
            '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/></manifest>',
        )
        .replace(
            "</package>",
            '<guide><reference type="text" title="Start" href="chapter.xhtml#start"/></guide></package>',
        )
    )
    package = package.replace(
        "<metadata ",
        '<metadata xmlns:q="urn:test:types" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" ',
    )
    package = package.replace("<dc:language>", '<dc:language xsi:type="q:Language">')
    ncx = f'''<ncx xmlns="{NCX}" version="2005-1" xml:lang="en"><head>
    <meta name="dtb:uid" content="urn:old"/></head><docTitle><text>Sensor guide</text></docTitle>
    <docAuthor><text>Original Author</text></docAuthor><navMap><navPoint id="n1" playOrder="1">
    <navLabel><text>First</text></navLabel><content src="chapter.xhtml#start"/>
    <navPoint id="n2" playOrder="2"><navLabel><text>Second</text></navLabel>
    <content src="chapter.xhtml#end"/></navPoint></navPoint></navMap></ncx>'''
    chapter = f'''{DTD}<html xmlns="{XHTML}" xml:lang="en"><head><title>Guide</title></head>
    <body><big id="start">First&nbsp;paragraph square(4).<br/><br/>Second <em>paragraph</em>.<br/>
    <br/>Last &amp;nbsp; paragraph.<br/><br/>End.</big><p id="end">Finish.</p></body></html>'''
    return {
        "EPUB/package.opf": package.encode(),
        "EPUB/toc.ncx": ncx.encode(),
        "EPUB/chapter.xhtml": chapter.encode(),
    }
