"""Questions use original excerpts, exact quotes and bounded lexical retrieval."""

import re
from collections import defaultdict

from pydantic import Field

from brofessor import prompts
from brofessor.contracts.content import ContentLanguage, EvidenceStatus, UnitStatus
from brofessor.contracts.jobs import JobKind, JobStatus, StageId
from brofessor.features.sources import reading
from brofessor.features.sources.reading import ReadingStatus
from brofessor.infrastructure.formats.ingestion import search_units
from brofessor.models import Output
from brofessor.prompts import ids as prompt_ids

DIRECT_BUDGET = 24000
EVIDENCE_BUDGET = 90000
MATCH_LIMIT = 8
HISTORY_TURNS = 6
HISTORY_BUDGET = 12000


class HistoryLimit(ValueError):
    """The selected conversation cannot fit without dropping an older turn."""


def saved_answer(workspace, job_id, revision=None):
    job = workspace.job(job_id)
    if job["kind"] != JobKind.ASK or job["status"] != JobStatus.SUCCEEDED:
        raise ValueError("Choose a completed question")
    if revision is not None and (type(revision) is not int or revision < 1):
        raise ValueError("Answer revision must be a positive integer")
    draft = workspace.draft(job_id, revision)
    if draft is None:
        raise ValueError("The requested answer revision does not exist")
    return job, draft


def history(workspace, references, source_ids, *, collections=None):
    """Resolve a bounded, frozen list of answer revisions, never the latest ones."""
    if len(references) > HISTORY_TURNS:
        raise HistoryLimit("Conversation exceeds the turn limit")
    turns = []
    for ref in references:
        if set(ref) != {"job_id", "revision"}:
            raise ValueError("Invalid conversation reference")
        if type(ref["revision"]) is not int or ref["revision"] < 1:
            raise ValueError("Conversation references require pinned positive revisions")
        job, draft = saved_answer(workspace, ref["job_id"], ref["revision"])
        if set(job["params"]["source_ids"]) != set(source_ids):
            raise ValueError("Conversation must use the same source selection")
        if {r["id"] for r in job["params"].get("collections", [])} != {
            r["id"] for r in collections or []
        }:
            raise ValueError("Conversation must use the same document collections")
        turns.append(
            {
                **ref,
                "question": job["params"]["focus"],
                "answer": draft["data"]["answer"],
                "evidence_status": draft["data"].get("evidence_status", EvidenceStatus.SUPPORTED),
            }
        )
    if len(reading.encoded(turns)) > HISTORY_BUDGET:
        raise HistoryLimit(
            "Previous answer is too long for follow-up context; shorten it or start a new question"
        )
    return turns


class SearchQueries(Output):
    queries: list[str] = Field(min_length=1, max_length=4)


def references(items):
    """Flatten actual content references for the shared evidence viewer."""
    return {
        "citations": list(dict.fromkeys(c for item in items for c in item["citations"])),
        "quotes": list(
            {(q["citation"], q["text"]): q for item in items for q in item["quotes"]}.values()
        ),
    }


def _evidence(units):
    return [
        {
            "id": u["id"],
            "source": u.get("source", u["source_id"]),
            "locator": u["locator"],
            "text": u["text"],
        }
        for u in units
    ]


def prepare(
    units, question, generate, check, progress, folder, *, conversation=None, required_ids=None
):
    """Small sets pass through; larger sets use query variants and whole originals.

    Unselected units are explicitly accounted for, never reported as read. There
    is no evidence summarization and no claim of exhaustive retrieval.
    """
    check()
    ready = [u for u in units if u["status"] == UnitStatus.READY]
    evidence = _evidence(ready)
    queries = []
    matched = []
    mode = "direct"
    required_ids = set(required_ids or [])
    if required_ids and {u["id"] for u in ready} <= required_ids:
        if len(reading.encoded(evidence)) > EVIDENCE_BUDGET:
            raise ValueError("Selected original text exceeds the answer context budget")
        mode = "navigated"
    elif len(reading.encoded(evidence)) > min(DIRECT_BUDGET, EVIDENCE_BUDGET):
        mode = "retrieved"
        progress({"stage": StageId.SEARCHING})
        result = generate(
            prompts.render(
                prompt_ids.QUESTIONS_SEARCH,
                conversation_rule=prompts.render(prompt_ids.QUESTIONS_SEARCH_CONVERSATION)
                if conversation
                else "",
                payload=reading.encoded(
                    {
                        "question": question,
                        **({"conversation": conversation} if conversation else {}),
                    }
                ),
            ),
            SearchQueries,
        )
        queries = list(dict.fromkeys([question, *result["queries"]]))
        scores = defaultdict(float)
        for query in queries:
            check()
            for rank, u in enumerate(search_units(ready, query, limit=MATCH_LIMIT), 1):
                scores[u["id"]] += 1 / (60 + rank)
        order = {u["id"]: i for i, u in enumerate(ready)}
        matched = sorted(scores, key=lambda key: (-scores[key], order[key]))[:MATCH_LIMIT]
        # Keep a scene's continuation ahead of unrelated lower-ranked matches.
        indexes = [order[key] for key in matched]
        context = [
            i + delta
            for i in indexes
            for delta in (0, 1, 2, -1)
            if 0 <= i + delta < len(ready)
            and ready[i + delta]["source_id"] == ready[i]["source_id"]
        ]
        selected = [u for u in ready if u["id"] in required_ids]
        if len(reading.encoded(_evidence(selected))) > EVIDENCE_BUDGET:
            raise ValueError("Required original fragments exceed the answer context budget")
        for index in dict.fromkeys(context):
            if ready[index]["id"] in required_ids:
                continue
            candidate = [*selected, ready[index]]
            if len(reading.encoded(_evidence(candidate))) <= EVIDENCE_BUDGET:
                selected = candidate
        evidence = _evidence(sorted(selected, key=lambda u: order[u["id"]]))
    selected_ids = {item["id"] for item in evidence}
    report = {
        "mode": mode,
        "queries": queries,
        **(
            {
                "conversation": [
                    {"job_id": turn["job_id"], "revision": turn["revision"]}
                    for turn in conversation
                ]
            }
            if conversation
            else {}
        ),
        "matched": matched,
        "selected_count": len(selected_ids),
        "excluded": [u["id"] for u in units if u["status"] != UnitStatus.READY],
        "units": [
            {
                "id": u["id"],
                "source_id": u["source_id"],
                "locator": u["locator"],
                "status": ReadingStatus.EXCLUDED
                if u["status"] != UnitStatus.READY
                else ReadingStatus.PENDING
                if u["id"] in selected_ids
                else ReadingStatus.NOT_SELECTED,
                "reason": u["status"]
                if u["status"] != UnitStatus.READY
                else "not_selected_by_search"
                if u["id"] not in selected_ids
                else "",
            }
            for u in units
        ],
    }
    reading.save_coverage(folder, report)
    return evidence, report


def validate_answer(value, units, *, require_quotes=True):
    """Restore original whitespace in quotes, then require verbatim source text.

    Imported EPUB/PDF line wrapping is not semantic content. Only whitespace
    may differ; words, punctuation and numbers must match. Stored quotes always
    contain the original substring, never the model's rewritten wrapping.
    """
    originals = {u["id"]: u["text"] for u in units if u["status"] == UnitStatus.READY}
    cited = set(value["citations"])
    quoted = set()
    for quote in value.get("quotes", []):
        key, text = quote["citation"], quote["text"]
        if key not in cited or key not in originals:
            raise ValueError("Each quote must reference a cited original fragment in scope")
        if not text.strip():
            raise ValueError("Quote must not be blank")
        if text not in originals[key]:
            pattern = r"\s+".join(re.escape(word) for word in text.split())
            match = re.search(pattern, originals[key])
            if match is None:
                raise ValueError(f"Quote is not an exact substring of original fragment {key}")
            quote["text"] = match.group()  # Canonical original, including its line breaks.
        quoted.add(key)
    if require_quotes and cited != quoted:
        raise ValueError("Every cited fragment requires an exact original quote")
    if (
        value["evidence_status"] == EvidenceStatus.CONFLICTING_EVIDENCE
        and len({(q["citation"], q["text"]) for q in value.get("quotes", [])}) < 2
    ):
        raise ValueError("Conflicting evidence requires at least two distinct original quotes")


def write(base, evidence, generate, units, language):
    if not evidence:
        return {
            "answer": "Поиск не нашёл подходящих фрагментов в выбранных источниках. Это не доказывает отсутствие ответа во всём материале. Уточните вопрос или поисковые слова."
            if language == ContentLanguage.RU
            else "Search found no matching fragments in the selected sources. This does not prove the answer is absent from the entire material. Refine the question or search terms.",
            "citations": [],
            "quotes": [],
            "evidence_status": EvidenceStatus.INSUFFICIENT_EVIDENCE,
        }
    from brofessor.models import Answer

    return generate(
        prompts.render(prompt_ids.QUESTIONS_ANSWER, base=base),
        Answer,
        validate=lambda value: validate_answer(value, units),
    )
