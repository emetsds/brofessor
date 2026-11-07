"""An independently edited ZIP must expose plain-math corruption in QA."""

import json
import subprocess
import sys
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

import pytest

from tests.helpers.epub import FIXTURE, make_book, translation
from tests.helpers.paths import TOOLS


@pytest.mark.parametrize("corruption", ["function", "decimal"])
def test_audit_detects_math_corruption_in_an_independently_edited_epub(tmp_path, corruption):
    chapter = (
        (FIXTURE / "EPUB/chapter.xhtml")
        .read_bytes()
        .replace(
            b"</body>", b"<p>Compute square_root(4) and square(9).</p><p>Supply .340 V.</p></body>"
        )
    )
    book = make_book(tmp_path, {"EPUB/chapter.xhtml": chapter})
    output = book.render(translation(book), tmp_path / "translated.epub", "en")
    tool = TOOLS / "check_epub_translation.py"

    def check():
        result = subprocess.run(
            [sys.executable, str(tool), str(book.source), str(output)],
            capture_output=True,
            text=True,
        )
        return result.returncode, json.loads(result.stdout)

    status, clean = check()
    assert status == 0 and clean["problems"] == []
    with ZipFile(output) as archive:
        entries = {p: archive.read(p) for p in archive.namelist()}
    before, after = (
        (b"square_root(4)", b"translated_root(4)")
        if corruption == "function"
        else (b".340", b"340")
    )
    entries["EPUB/chapter.xhtml"] = entries["EPUB/chapter.xhtml"].replace(before, after)
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(
                name, data, compress_type=ZIP_STORED if name == "mimetype" else ZIP_DEFLATED
            )
    status, broken = check()
    assert status != 0
    if corruption == "function":
        assert "Changed plain-text mathematical/code function calls" in broken["problems"]
    else:
        assert "Changed XHTML numeric values: EPUB/chapter.xhtml" in broken["problems"]
