"""Bounded whole-source reading, with original citations and incremental coverage."""

import json
from enum import StrEnum
from typing import Final

from pydantic import Field

from brofessor import prompts
from brofessor.contracts.content import UnitStatus
from brofessor.contracts.jobs import StageId
from brofessor.infrastructure.storage.workspace import atomic_json
from brofessor.models import Output
from brofessor.prompts import ids as prompt_ids

COVERAGE_FILENAME: Final = "coverage.json"


class ReadingMode(StrEnum):
    DIRECT = "direct"
    SUMMARIZED = "summarized"
    RETRIEVED = "retrieved"
    NAVIGATED = "navigated"
    NARRATION = "narration"


class ReadingStatus(StrEnum):
    PENDING = "pending"
    READ = "read"
    EXCLUDED = "excluded"
    NOT_SELECTED = "not_selected"


READING_BUDGET = 24000
SYNTHESIS_BUDGET = 90000


class FragmentNote(Output):
    summary: str = Field(min_length=1, max_length=1200)
    citations: list[str] = Field(min_length=1, max_length=1)


class ReadingBatch(Output):
    notes: list[FragmentNote] = Field(min_length=1)


class SectionNote(Output):
    summary: str = Field(min_length=1, max_length=4000)
    citations: list[str] = Field(min_length=1)


class SectionNotes(Output):
    notes: list[FragmentNote] = Field(min_length=1)


def encoded(value):
    return json.dumps(value, ensure_ascii=False)


def batches(items, budget=READING_BUDGET):
    """Bound the serialized evidence, including IDs and locators, without truncation."""
    batch = []
    size = 2
    for item in items:
        length = len(encoded(item)) + 2
        if length + 2 > budget:
            raise ValueError("A source fragment exceeds the reading budget")
        if batch and size + length > budget:
            yield batch
            batch, size = [], 2
        batch.append(item)
        size += length
    if batch:
        yield batch


def validate_batch(value, expected):
    citations = [note["citations"][0] for note in value["notes"]]
    if len(citations) != len(expected) or set(citations) != expected:
        raise ValueError("Reading notes must cover every requested fragment exactly once")


def with_metadata(evidence, units, names):
    """Resolve provenance locally, including notes reused from historical series."""
    by_id = {unit["id"]: unit for unit in units}
    result = []
    for item in evidence:
        ids = item.get("citations", [item.get("id")])
        origins = []
        for identifier in ids:
            unit = by_id[identifier]
            origins.append(
                {
                    "id": identifier,
                    "source": names.get(unit["source_id"], unit["source_id"]),
                    "locator": unit["locator"],
                }
            )
        result.append({**item, "origins": origins})
    return result


def prepare(units, focus, generate, check, progress, folder, *, version=1, names=None):
    if version >= 3:
        names = names or {}
        units = [
            {**unit, "source": names.get(unit["source_id"], unit["source_id"])} for unit in units
        ]

    def provenance(evidence):
        return with_metadata(evidence, units, names) if version >= 3 else evidence

    ready = [unit for unit in units if unit["status"] == UnitStatus.READY]
    report = {
        "mode": ReadingMode.DIRECT
        if len(encoded(ready)) <= READING_BUDGET
        else ReadingMode.SUMMARIZED,
        "read": [],
        "count": 0,
        "excluded": [unit["id"] for unit in units if unit["status"] != UnitStatus.READY],
        "units": [
            {
                "id": unit["id"],
                "source_id": unit["source_id"],
                "locator": unit["locator"],
                "status": ReadingStatus.PENDING
                if unit["status"] == UnitStatus.READY
                else ReadingStatus.EXCLUDED,
                "reason": "" if unit["status"] == UnitStatus.READY else unit["status"],
            }
            for unit in units
        ],
    }
    save_coverage(folder, report)
    evidence = [
        {"id": unit["id"], "locator": unit["locator"], "text": unit["text"]} for unit in ready
    ]
    if report["mode"] == ReadingMode.DIRECT:
        # These fragments count as read only after the final model result is accepted.
        return provenance(evidence), report

    evidence = []
    for batch in batches(ready):
        check()
        progress({"stage": StageId.READING, "completed": report["count"], "total": len(ready)})
        ids = {unit["id"] for unit in batch}
        result = generate(
            prompts.render(
                prompt_ids.READING_FRAGMENTS, payload=encoded({"focus": focus, "fragments": batch})
            ),
            ReadingBatch,
            citation_scope=ids,
            validate=lambda value: validate_batch(value, ids),
        )
        notes = {note["citations"][0]: note["summary"] for note in result["notes"]}
        evidence.extend({"citations": [unit["id"]], "text": notes[unit["id"]]} for unit in batch)
        for unit in report["units"]:
            if unit["id"] in ids:
                unit["status"] = ReadingStatus.READ
        save_coverage(folder, report)
        progress({"stage": StageId.READING, "completed": report["count"], "total": len(ready)})

    # Large source sets need another bounded pass. Notes keep original source IDs;
    # coverage records reading separately from the editorial selection in summaries.
    evidence = provenance(evidence)
    while len(encoded(evidence)) > SYNTHESIS_BUDGET:
        previous_size = len(encoded(evidence))
        groups = list(batches(evidence))
        reduced = []
        for index, group in enumerate(groups):
            check()
            progress({"stage": StageId.CONSOLIDATING, "completed": index, "total": len(groups)})
            ids = {citation for item in group for citation in item["citations"]}
            if version >= 2:
                result = generate(
                    prompts.render(
                        "reading/reduce", payload=encoded({"focus": focus, "notes": group})
                    ),
                    SectionNotes,
                    citation_scope=ids,
                )
                reduced.extend(
                    {"text": note["summary"], "citations": note["citations"]}
                    for note in result["notes"]
                )
                continue
            note = generate(
                prompts.render(
                    "reading/reduce_v1", payload=encoded({"focus": focus, "notes": group})
                ),
                SectionNote,
                citation_scope=ids,
            )
            reduced.append({"text": note["summary"], "citations": note["citations"]})
        reduced = provenance(reduced)
        if len(encoded(reduced)) >= previous_size:
            raise ValueError("Reading notes could not be reduced within the synthesis budget")
        evidence = reduced
    return evidence, report


def save_coverage(folder, report):
    report["read"] = [
        unit["id"] for unit in report["units"] if unit["status"] == ReadingStatus.READ
    ]
    report["count"] = len(report["read"])
    atomic_json(folder / COVERAGE_FILENAME, report)
