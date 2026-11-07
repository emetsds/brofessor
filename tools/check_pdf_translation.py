"""Audit the actual text and graphics of a saved PDF translation.

This checks the rendered PDF, rather than accepting model JSON or the layout
report as proof of rendering. Semantic and visual review remain separate.
"""

import argparse
import hashlib
import json
import re
from contextlib import closing
from pathlib import Path

import pypdfium2 as pdfium
from pypdf import PdfReader
from pypdfium2 import raw

from brofessor.application import service
from brofessor.features.books import translation as book_translation
from brofessor.infrastructure.formats.epub import _numbers
from brofessor.infrastructure.storage.workspace import Workspace, atomic_json


def _letters(text):
    return "".join(text.replace("\x02", "-").replace("\ufffe", "-").split())


def _same_text(actual, expected):
    # PDFium collapses discretionary end-of-line hyphens to U+0002 and often
    # suppresses that line break entirely. This is distinct from a literal '-'.
    def matches(text):
        target = " ".join(expected.split())
        text = re.sub(r"([\x02\ufffe])\s*", r"\1", text)
        text = re.sub(r"\r?\n(?=[,.!?;:])", "", text)
        index = 0
        for char in " ".join(text.split()):
            if char in ("\x02", "\ufffe"):
                if index < len(target) and target[index] == "-":
                    index += 1
                continue
            if index == len(target) or target[index] != char:
                return False
            index += 1
        return index == len(target)

    if matches(actual):
        return True
    # A discretionary hyphen may also be exposed as '-' at a line boundary.
    joined = re.sub(r"(?<=[А-Яа-яЁё])-[ \t]*\r?\n(?=[А-Яа-яЁё])", "", actual)
    return matches(joined)


def _text(document, item):
    with closing(document[item["page"] - 1]) as page, closing(page.get_textpage()) as text:
        left, bottom, right, top = item["bbox"]
        return text.get_text_bounded(
            left=left - 0.2, bottom=bottom - 0.2, right=right + 0.2, top=top + 0.2
        )


def audit(workspace, job_id, revision=None):
    job = workspace.job(job_id)
    saved = workspace.draft(job_id, revision)
    if saved is None:
        raise ValueError("Choose a saved PDF translation")
    artifact = book_translation.rendered_artifact(workspace, job, saved["revision"])
    if artifact is None or artifact["kind"] != "pdf":
        raise ValueError("Choose a PDF translation with an available export")
    source = book_translation.source_book(workspace, job["params"])
    output = service.artifact_path(workspace, artifact["path"])
    mapping = json.loads(
        service.artifact_path(workspace, artifact["metadata"]["layout"]).read_text()
    )
    translated = {b["id"]: b["text"] for b in saved["data"]["blocks"]}
    originals = {b.id: b for b in source.blocks}
    from brofessor.infrastructure.formats.epub import MARKER

    rendered = {
        key: MARKER.sub(lambda m: originals[key].protected.get(m[0], ""), value)
        for key, value in translated.items()
    }
    issues = []
    if set(translated) != {b["id"] for b in mapping["blocks"]} or len(translated) != len(
        mapping["blocks"]
    ):
        issues.append("layout does not cover every saved block exactly once")
    with (
        pdfium.PdfDocument(str(output)) as result,
        pdfium.PdfDocument(str(source.source)) as original,
    ):
        if len(result) != len(original):
            issues.append("changed page count")
        for item in mapping["blocks"]:
            actual = _text(result, item)
            suffix = "\n" + item["suffix"] if item.get("suffix") else ""
            if not _same_text(actual, rendered[item["id"]] + suffix):
                issues.append(f"rendered text differs: {item['id']}")
            if _numbers(actual) != _numbers(originals[item["id"]].plain_text() + suffix):
                issues.append(f"rendered numeric values differ: {item['id']}")
        for item in mapping["preserved"]:
            if _letters(_text(result, item)) != _letters(item.get("raw_text", item["text"])):
                issues.append(f"preserved text differs: {item['id']}")
        for number in range(min(len(original), len(result))):

            def paths(document):
                with closing(document[number]) as page:
                    return [
                        tuple(round(v, 3) for v in obj.get_bounds())
                        for obj in page.get_objects(filter=[raw.FPDF_PAGEOBJ_PATH])
                    ]

            if paths(original) != paths(result):
                issues.append(f"changed native vector path bounds: page {number + 1}")
    before, after = PdfReader(source.source), PdfReader(output)
    for number, (a, b) in enumerate(zip(before.pages, after.pages), 1):
        if [hashlib.sha256(i.data).hexdigest() for i in a.images] != [
            hashlib.sha256(i.data).hexdigest() for i in b.images
        ]:
            issues.append(f"changed image contents: page {number}")
    return {
        "passed": not issues,
        "issues": issues,
        "blocks": len(translated),
        "preserved": len(mapping["preserved"]),
        "pages": len(after.pages),
        "source_sha256": source.source_hash,
        "revision": saved["revision"],
        "pdf_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--job", required=True)
    parser.add_argument("--revision", type=int)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = audit(Workspace(args.workspace), args.job, args.revision)
    if args.output:
        atomic_json(args.output, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["passed"] else 1)
