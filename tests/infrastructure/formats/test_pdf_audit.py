"""A saved valid model response cannot hide independently damaged PDF content."""

import json
import runpy
import subprocess
import sys

from pypdf import PdfReader, PdfWriter
from pypdf.generic import ByteStringObject, ContentStream, TextStringObject

from brofessor.application import pipeline, service
from brofessor.contracts.jobs import JobKind
from tests.helpers.paths import TOOLS
from tests.helpers.pdf import workspace_with_pdf


def test_pdf_audit_distinguishes_word_spaces_and_discretionary_hyphens():
    same_text = runpy.run_path(str(TOOLS / "check_pdf_translation.py"))["_same_text"]
    assert not same_text("UseHEAD safely.", "Use HEAD safely.")
    assert same_text("пере\x02\r\nносы", "переносы")
    assert same_text("re\x02", "re-")
    assert not same_text("пере\x02нос", "переносы")


def test_pdf_audit_detects_lost_text_in_an_independently_edited_pdf(tmp_path, monkeypatch):
    workspace, source, _ = workspace_with_pdf(tmp_path, monkeypatch)
    job = service.submit(
        workspace, JobKind.TRANSLATE_PDF, source_ids=[source["id"]], start_worker=False
    )
    pipeline.execute(workspace, job)
    output = service.rendered_file(workspace, job)
    tool = TOOLS / "check_pdf_translation.py"

    def check():
        result = subprocess.run(
            [sys.executable, str(tool), "--workspace", str(workspace.path), "--job", job["id"]],
            capture_output=True,
            text=True,
        )
        return result.returncode, json.loads(result.stdout)

    status, clean = check()
    assert status == 0 and clean["passed"]
    reader = PdfReader(output)
    writer = PdfWriter(clone_from=reader)
    page = writer.pages[0]
    content = ContentStream(page.get_contents(), writer)
    # Lose rendered text while leaving the saved draft and layout manifest intact.
    # Original formula/code/numbers remain, exposing missing translation coverage.
    for operands, operator in content.operations:
        if operator == b"Tj" and isinstance(operands[0], (TextStringObject, ByteStringObject)):
            operands[0] = TextStringObject("")
        elif operator == b"TJ":
            operands[0][:] = [
                v for v in operands[0] if not isinstance(v, (TextStringObject, ByteStringObject))
            ]
    page.replace_contents(content)
    writer.write(output)
    status, broken = check()
    assert status != 0 and not broken["passed"]
    assert any("rendered text differs" in issue for issue in broken["issues"])
