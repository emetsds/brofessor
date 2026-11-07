"""Optional, scoped review of a pinned podcast script against original fragments."""

import json
from enum import StrEnum
from typing import Final, Literal

from pydantic import Field

from brofessor import prompts
from brofessor.contracts.content import ArtifactKind, EvidenceStatus, UnitStatus
from brofessor.contracts.jobs import JobKind, StageId
from brofessor.features.podcasts.episode_writer import original_pack
from brofessor.features.questions import validate_answer
from brofessor.infrastructure.storage.workspace import JOBS_DIRECTORY, atomic_json
from brofessor.models import Output, Podcast, Quote
from brofessor.prompts import ids as prompt_ids

CHECK_FILENAME: Final = "script-check.json"

PROMPT_BUDGET = 60000
MAX_BATCH_TURNS = 12


class FindingKind(StrEnum):
    UNSUPPORTED = "unsupported"
    CONTRADICTION = "contradiction"
    PARTIAL_SUPPORT = "partial_support"
    UNLABELLED_INFERENCE = "unlabelled_inference"


class CheckStatus(StrEnum):
    SUPPORTED = "supported"
    ISSUE = "issue"
    NEEDS_CONTEXT = "needs_context"


FindingKindValue = Literal[
    FindingKind.UNSUPPORTED,
    FindingKind.CONTRADICTION,
    FindingKind.PARTIAL_SUPPORT,
    FindingKind.UNLABELLED_INFERENCE,
]
CheckStatusValue = Literal[CheckStatus.SUPPORTED, CheckStatus.ISSUE, CheckStatus.NEEDS_CONTEXT]


class Finding(Output):
    claim: str = Field(min_length=1, max_length=1000)
    kind: FindingKindValue
    explanation: str = Field(min_length=1, max_length=1200)
    quotes: list[Quote] = Field(max_length=8)


class Assessment(Output):
    turn: int = Field(ge=1)
    status: CheckStatusValue
    explanation: str = Field(min_length=1, max_length=600)
    findings: list[Finding] = Field(max_length=8)
    quotes: list[Quote] = Field(max_length=8)


class CheckBatch(Output):
    assessments: list[Assessment] = Field(min_length=1, max_length=MAX_BATCH_TURNS)


def encoded(value):
    return json.dumps(value, ensure_ascii=False)


def validate_batch(value, turns, originals):
    expected = {item["turn"]: item for item in turns}
    actual = [item["turn"] for item in value["assessments"]]
    if len(actual) != len(expected) or set(actual) != set(expected):
        raise ValueError("Script check must assess every requested turn exactly once")
    units = [{**item, "status": UnitStatus.READY} for item in originals]
    allowed = {item["id"] for item in originals}
    for assessment in value["assessments"]:
        if (assessment["status"] == CheckStatus.ISSUE) != bool(assessment["findings"]):
            raise ValueError("Only an issue assessment may contain findings")
        if assessment["status"] == CheckStatus.SUPPORTED and not assessment["quotes"]:
            raise ValueError("A supported assessment needs an original excerpt")
        groups = [assessment["quotes"]]
        for finding in assessment["findings"]:
            # Claims point to immutable script wording, including genuine punctuation.
            if finding["claim"] not in expected[assessment["turn"]]["text"]:
                raise ValueError("A finding must quote the exact claim from its pinned turn")
            if finding["kind"] == FindingKind.CONTRADICTION and not finding["quotes"]:
                raise ValueError("A contradiction needs an original excerpt")
            groups.append(finding["quotes"])
        for quotes in groups:
            ids = {quote["citation"] for quote in quotes}
            if not ids <= allowed:
                raise ValueError("Review excerpts must come from originals in this check packet")
            validate_answer(
                {
                    "citations": list(ids),
                    "quotes": quotes,
                    "evidence_status": EvidenceStatus.SUPPORTED,
                },
                units,
            )


def packets(turns, units, names, header):
    """Keep whole turns and mandatory originals; record uncheckable inputs explicitly."""
    batches, unchecked = [], []
    current = []

    def packet(items):
        prefix = prompts.render(
            prompt_ids.PODCASTS_CHECK_PACKET, header=header, turns=encoded(items)
        )
        ids = list(dict.fromkeys(citation for item in items for citation in item["citations"]))
        evidence = original_pack(ids, units, names, budget=PROMPT_BUDGET - len(prefix))
        return {"turns": items, "evidence": evidence, "prompt": prefix + encoded(evidence)}

    for index, turn in enumerate(turns, 1):
        item = {"turn": index, **turn}
        try:
            candidate = packet([*current, item]) if len(current) < MAX_BATCH_TURNS else None
        except ValueError:
            candidate = None
        if candidate is not None:
            current.append(item)
            continue
        if current:
            batches.append(packet(current))
            current = []
        try:
            packet([item])
        except ValueError as error:
            unchecked.append({"turn": index, "reason": str(error)})
        else:
            current = [item]
    if current:
        batches.append(packet(current))
    return batches, unchecked


def run(workspace, job, generate, progress, check):
    params = job["params"]
    draft = workspace.draft(params["draft_job_id"], params["revision"])
    if draft is None:
        raise ValueError("The requested script revision does not exist")
    script = Podcast.model_validate(draft["data"]).model_dump()
    from brofessor.features.sources import navigation as source_navigation

    units = source_navigation.units(workspace, job)
    names = source_navigation.names(workspace, job)
    header = prompts.render(prompt_ids.PODCASTS_CHECK, language=params["language"])
    batches, unchecked = packets(script["turns"], units, names, header)
    report = {
        "draft_job_id": params["draft_job_id"],
        "revision": params["revision"],
        "scope": "Cited originals and bounded neighbouring fragments; not a search of all source claims.",
        "total_turns": len(script["turns"]),
        "assessments": [],
        "unchecked": unchecked,
        "pending_turns": [item["turn"] for batch in batches for item in batch["turns"]],
        "packets": [],
        "complete": False,
    }
    path = workspace.path / JOBS_DIRECTORY / job["id"] / CHECK_FILENAME
    atomic_json(path, report)
    for index, batch in enumerate(batches):
        check()
        progress({"stage": StageId.CHECKING_SCRIPT, "completed": index, "total": len(batches)})
        originals = batch["evidence"]["originals"]
        result = generate(
            batch["prompt"],
            CheckBatch,
            citation_scope={item["id"] for item in originals},
            validate=lambda value, b=batch: validate_batch(
                value, b["turns"], b["evidence"]["originals"]
            ),
        )
        report["assessments"].extend(result["assessments"])
        processed = {item["turn"] for item in result["assessments"]}
        report["pending_turns"] = [
            number for number in report["pending_turns"] if number not in processed
        ]
        report["packets"].append(
            {
                "turns": sorted(processed),
                "originals": [{k: u[k] for k in ("id", "source", "locator")} for u in originals],
                "additional_context_omitted": batch["evidence"]["additional_context_omitted"],
            }
        )
        atomic_json(path, report)
    check()
    report["complete"] = True
    report["assessments"].sort(key=lambda item: item["turn"])
    atomic_json(path, report)
    workspace.add_artifact(
        job["id"], path, ArtifactKind.JSON, {"role": "script_check", "revision": params["revision"]}
    )
    progress({"stage": StageId.CHECKED_SCRIPT, "completed": len(batches), "total": len(batches)})
    return report


def report(workspace, job_id):
    job = workspace.job(job_id)
    if job["kind"] != JobKind.CHECK_PODCAST:
        raise ValueError("Choose a script check job")
    path = workspace.path / JOBS_DIRECTORY / job_id / CHECK_FILENAME
    return json.loads(path.read_text()) if path.is_file() else None
