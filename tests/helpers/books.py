"""Synthetic ambiguous terminology and a fake expensive text boundary for tests."""

import copy
import json
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

from brofessor.contracts.content import ContentLanguage
from brofessor.contracts.jobs import JobKind, JobStatus
from brofessor.features.books import terminology
from brofessor.infrastructure.storage.workspace import Workspace
from tests.helpers.paths import FIXTURES


def workspace_with_book(tmp_path, *, paragraphs=1):
    fixture = FIXTURES / "translation"
    source = tmp_path / "book.epub"
    prose = (
        "".join(
            f"<p>The database <em>log</em> stores records; the wooden log floats. Entry {index}.</p>"
            for index in range(paragraphs)
        )
        + "<p>The log records a retry.</p>"
    )
    chapter = f"""<html xmlns="http://www.w3.org/1999/xhtml" lang="en"><head><title>Logs</title></head>
    <body><section id="chapter"><h1>Logs</h1>{prose}</section></body></html>"""
    with ZipFile(source, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("mimetype", b"application/epub+zip", compress_type=ZIP_STORED)
        for path in fixture.rglob("*"):
            if path.is_file() and path.name not in {"README.md", "mimetype"}:
                name = path.relative_to(fixture).as_posix()
                archive.writestr(
                    name, chapter if name.endswith("chapter.xhtml") else path.read_bytes()
                )
    workspace = Workspace(tmp_path / "workspace")
    imported = workspace.add_source(source)
    return workspace, imported


def translated_book(tmp_path, monkeypatch):
    from brofessor.application import pipeline, service

    workspace, source = workspace_with_book(tmp_path)
    model = FakeBookModel()
    monkeypatch.setattr("brofessor.infrastructure.text.runners.generate", model)
    job = service.submit(
        workspace,
        JobKind.TRANSLATE_EPUB,
        source_ids=[source["id"]],
        language=ContentLanguage.RU,
        start_worker=False,
    )
    pipeline.execute(workspace, job)
    workspace.update_job(job["id"], status=JobStatus.SUCCEEDED)
    return workspace, source, job, model


def payloads(prompt):
    return [
        json.JSONDecoder().raw_decode(prompt[position + 1 :])[0]
        for position in range(len(prompt))
        if prompt.startswith("\n{", position)
    ]


class FakeBookModel:
    def __init__(self, *, review=False, bad_alignment=False, bad_repair=False):
        self.calls = []
        self.fail = None
        self.invalid_quote = False
        self.review = review
        self.bad_alignment = bad_alignment
        self.bad_repair = bad_repair

    def __call__(self, prompt, schema, provider, model=None, **kwargs):
        name = schema["title"]
        self.calls.append({"prompt": prompt, "schema": name, "provider": provider, "model": model})
        if self.fail and self.fail(name, prompt):
            raise RuntimeError("controlled text boundary failure")
        data = payloads(prompt)
        if name == "GlossaryReviewBatch":
            packet = data[-1]
            proposals = []
            if self.review:
                known = next((t for t in packet["known_meanings"] if t["term"] == "database"), None)
                meaning = known or {
                    "term": "database",
                    "sense": "stored collection of records",
                    "translation": "база данных",
                }
                proposals = [
                    {
                        **{k: meaning[k] for k in ("term", "sense", "translation")},
                        "existing_id": known["id"] if known else None,
                        "occurrences": [
                            {
                                "block_id": b["id"],
                                "quote": b["text"],
                                "surface": "database",
                                "match": 1,
                            }
                            for b in packet["blocks"]
                            if "database" in b["text"]
                        ],
                    }
                ]
            return {"assessed_blocks": [b["id"] for b in packet["blocks"]], "terms": proposals}
        if name == "GlossaryBatch":
            packet = data[-1]
            proposals = {}

            def entry(kind):
                sense = "database journal" if kind == "journal" else "wood in the river"
                known = next(
                    (term for term in packet["known_meanings"] if term["sense"] == sense), None
                )
                value = known or {
                    "term": "log",
                    "sense": sense,
                    "translation": "журнал" if kind == "journal" else "бревно",
                }
                return {key: value[key] for key in ("term", "sense", "translation")} | {
                    "existing_id": known["id"] if known else None,
                    "occurrences": [],
                }

            for block in packet["blocks"]:
                if "log" not in block["text"]:
                    continue
                kinds = ["journal", "wood"] if "wooden log" in block["text"] else ["journal"]
                for index, kind in enumerate(kinds, 1):
                    proposal = proposals.setdefault(kind, entry(kind))
                    proposal["occurrences"].append(
                        {
                            "block_id": block["id"],
                            "quote": "invented excerpt" if self.invalid_quote else block["text"],
                            "surface": "log",
                            "match": index,
                        }
                    )
            return {
                "assessed_blocks": [block["id"] for block in packet["blocks"]],
                "terms": list(proposals.values()),
            }
        if name == "AlignmentBatch":
            packet = data[-1]
            terms = {t["id"]: t for t in packet["glossary"]}
            return {
                "blocks": [
                    {
                        "id": b["id"],
                        "targets": [
                            {
                                "occurrence_id": o["id"],
                                "quote": "unmatched repair quote" if self.bad_repair else b["text"],
                                "surface": terms[o["term_id"]]["translation"],
                                "match": 1,
                            }
                            for o in b["occurrences"]
                        ],
                    }
                    for b in packet["blocks"]
                ]
            }
        if name == "AlignedBatch":
            source, links = data
            terms = {term["id"]: term for term in source["glossary"]}
            result = []
            for block in source["blocks"]:
                text, targets = block["text"], []
                mentions = [
                    item for item in links["occurrences"] if item["block_id"] == block["id"]
                ]
                for occurrence in sorted(mentions, key=lambda item: item["start"], reverse=True):
                    # Raw text has markers around the first journal occurrence. Resolve
                    # the numbered source word without asking core code to fake alignment.
                    before = terminology.MARKER.sub("", text)
                    surface = occurrence["surface"]
                    earlier = before[: occurrence["start"]].count(surface)
                    starts = []
                    position = 0
                    while (position := text.find(surface, position)) >= 0:
                        starts.append(position)
                        position += len(surface)
                    start = starts[earlier]
                    replacement = terms[occurrence["term_id"]]["translation"]
                    text = text[:start] + replacement + text[start + len(surface) :]
                for occurrence in mentions:
                    phrase = terms[occurrence["term_id"]]["translation"]
                    targets.append(
                        {
                            "occurrence_id": occurrence["id"],
                            "quote": text,
                            "surface": phrase,
                            "match": 1,
                        }
                    )
                result.append({"id": block["id"], "text": text, "targets": targets})
            if self.bad_alignment:
                next(target for b in result for target in b["targets"])["quote"] = (
                    "unmatched initial quote"
                )
                self.bad_alignment = False
            return {"blocks": result}
        if name == "Replacements":
            packet = data[-1]
            return {
                "replacements": [
                    {"occurrence_id": item["id"], "text": packet["meaning"]["translation"]}
                    for item in packet["occurrences"]
                ]
            }
        raise AssertionError(name)


def text_edits(draft, transform):
    result = copy.deepcopy(draft["data"])
    for block in result["blocks"]:
        block["text"] = transform(block["text"])
    return result
