"""Source-backed episode writing with bounded originals and editorial handoffs."""

import hashlib
import json
import math
from enum import StrEnum
from typing import Literal

from pydantic import Field

from brofessor import prompts
from brofessor.contracts.content import ContentLanguage, Speaker, UnitStatus
from brofessor.contracts.jobs import StageId
from brofessor.features.podcasts.writer import Section, split_turns, word_count
from brofessor.models import Output, Podcast
from brofessor.prompts import ids as prompt_ids

PROMPT_BUDGET = 90000
CORRECTION_RESERVE = 10000


class RelationshipKind(StrEnum):
    AGREEMENT = "agreement"
    DISAGREEMENT = "disagreement"
    DIFFERENT_CONDITIONS = "different_conditions"
    SUPERSEDED = "superseded"
    UNKNOWN = "unknown"


RelationshipKindValue = Literal[
    RelationshipKind.AGREEMENT,
    RelationshipKind.DISAGREEMENT,
    RelationshipKind.DIFFERENT_CONDITIONS,
    RelationshipKind.SUPERSEDED,
    RelationshipKind.UNKNOWN,
]


class EpisodeSection(Section):
    citations: list[str] = Field(min_length=1, max_length=12)
    weight: int = Field(ge=1, le=5)


class SourceRelationship(Output):
    kind: RelationshipKindValue
    explanation: str = Field(min_length=1, max_length=600)
    citations: list[str] = Field(min_length=2, max_length=8)


class EpisodePlan(Output):
    title: str = Field(min_length=1, max_length=200)
    listener_goal: str = Field(min_length=1, max_length=600)
    material_sufficient: bool
    reason: str = Field(max_length=600)
    source_relationships: list[SourceRelationship] = Field(max_length=12)
    sections: list[EpisodeSection] = Field(max_length=12)


class Handoff(Output):
    covered_points: list[str] = Field(max_length=24)
    introduced_terms: list[str] = Field(max_length=16)
    open_question: str = Field(max_length=240)


class WrittenSection(Podcast):
    handoff: Handoff


def encoded(value):
    return json.dumps(value, ensure_ascii=False)


def bounded(prompt, budget=PROMPT_BUDGET):
    if len(prompt) > budget:
        raise ValueError(
            "Episode context exceeds its budget; narrow the section or split its sources"
        )
    return prompt


def original_pack(citations, units, names, *, budget):
    """Required IDs always fit whole; optional neighbours are explicitly accounted for."""
    ready = [unit for unit in units if unit["status"] == UnitStatus.READY]
    by_id = {unit["id"]: unit for unit in ready}
    required = list(dict.fromkeys(citations))
    if not required or not set(required) <= by_id.keys():
        raise ValueError("The section references unavailable original fragments")
    siblings = {}
    for unit in units:
        siblings.setdefault(unit["source_id"], []).append(unit)
    neighbours = []
    for identifier in required:
        unit = by_id[identifier]
        group = siblings[unit["source_id"]]
        position = next(index for index, item in enumerate(group) if item["id"] == identifier)
        for offset in (-1, 1):
            index = position + offset
            if 0 <= index < len(group):
                candidate = group[index]
                if (
                    candidate["status"] == UnitStatus.READY
                    and candidate["id"] not in required + neighbours
                ):
                    neighbours.append(candidate["id"])

    def value(included):
        return {
            "originals": [
                {
                    "id": identifier,
                    "source": names.get(
                        by_id[identifier]["source_id"], by_id[identifier]["source_id"]
                    ),
                    "locator": by_id[identifier]["locator"],
                    "text": by_id[identifier]["text"],
                }
                for identifier in required + included
            ],
            "additional_context_omitted": [item for item in neighbours if item not in included],
        }

    included = []
    if len(encoded(value(included))) > budget:
        raise ValueError(
            "Required original fragments exceed the section budget; narrow its citations"
        )
    for identifier in neighbours:
        if len(encoded(value([*included, identifier]))) <= budget:
            included.append(identifier)
    return value(included)


def validate_plan(value, minutes):
    sections = value["sections"]
    if not value["material_sufficient"]:
        if not value["reason"].strip():
            raise ValueError("An insufficient-material plan needs an explanation")
        return
    if not max(1, math.ceil(minutes / 10)) <= len(sections) <= min(12, math.ceil(minutes / 4)):
        raise ValueError("Episode plan needs a bounded number of substantive sections")
    titles = [item["title"].strip().casefold() for item in sections]
    if len(set(titles)) != len(titles):
        raise ValueError("Episode outline contains duplicate section titles")


def validate_handoff(value):
    if len(encoded(value)) > 6000 or any(
        not item.strip() or len(item) > 240
        for key in ("covered_points", "introduced_terms")
        for item in value[key]
    ):
        raise ValueError(
            "Editorial handoff must contain short, nonempty points within 6000 characters"
        )


def make_plan(context, minutes, target_words, generate, progress):
    instructions, evidence = context["instructions"], context["evidence"]
    lower, upper = max(1, math.ceil(minutes / 10)), min(12, math.ceil(minutes / 4))
    progress({"stage": StageId.OUTLINE})
    prompt = prompts.render(
        "podcasts/originals_outline",
        instructions=instructions,
        evidence=encoded(evidence),
        minutes=minutes,
        target_words=target_words,
        lower=lower,
        upper=upper,
    )
    plan = generate(
        bounded(prompt, 110000), EpisodePlan, validate=lambda v: validate_plan(v, minutes)
    )
    return plan


def write(
    context,
    minutes,
    language,
    generate,
    progress,
    save_outline,
    *,
    target_words,
    save_section=None,
    plan=None,
):
    """Generate only new-version prompts; legacy prompts remain in podcasts.write."""
    instructions = context["instructions"]
    units, names = context["units"], context["names"]
    if plan is None:
        plan = make_plan(context, minutes, target_words, generate, progress)
    else:
        plan = EpisodePlan.model_validate(plan).model_dump()
        validate_plan(plan, minutes)
    save_outline(plan)
    if not plan["material_sufficient"]:
        raise ValueError("Not enough source material for this duration: " + plan["reason"])
    handoff = {"covered_points": [], "introduced_terms": [], "open_question": ""}
    turns = []
    sections = plan["sections"]
    for index, section in enumerate(sections):
        progress({"stage": StageId.SCRIPT, "completed": index, "total": len(sections)})
        written = word_count(turns)
        remaining_weight = sum(item["weight"] for item in sections[index:])
        target = round((target_words - written) * section["weight"] / remaining_weight)
        low, high = math.ceil(target * 0.85), math.floor(target * 1.15)
        if index == len(sections) - 1:
            margin = max(1, round(target_words * 0.02))
            low, high = (
                max(low, target_words - margin - written),
                min(high, target_words + margin - written),
            )
        header = prompts.render(
            prompt_ids.PODCASTS_ORIGINALS_SECTION,
            instructions=instructions,
            plan=encoded(plan),
            handoff=encoded(handoff),
            previous=" ".join(turn["text"] for turn in turns[-2:]),
            section_number=index + 1,
            sections=len(sections),
            section=encoded(section),
            target=target,
            low=low,
            high=high,
            target_words=target_words,
            written=written,
        )
        packet = original_pack(
            section["citations"],
            units,
            names,
            budget=PROMPT_BUDGET - CORRECTION_RESERVE - len(header),
        )
        prompt = bounded(header + encoded(packet), PROMPT_BUDGET - CORRECTION_RESERVE)
        allowed = {item["id"] for item in packet["originals"]}

        def validate(value):
            if value["language"] != language:
                raise ValueError("Generated language does not match the request")
            validate_handoff(value["handoff"])

        def validate_length(value):
            validate(value)
            if not low <= word_count(value["turns"]) <= high:
                raise ValueError(
                    f"Podcast section {index + 1} has an invalid word count; resume to retry"
                )
            if {turn["speaker"] for turn in value["turns"]} != {Speaker.HOST, Speaker.GUEST}:
                raise ValueError("The section must contain both speakers")

        part = generate(prompt, WrittenSection, citation_scope=allowed, validate=validate)
        prompt_sizes = [len(prompt)]
        if not low <= word_count(part["turns"]) <= high or {
            t["speaker"] for t in part["turns"]
        } != {Speaker.HOST, Speaker.GUEST}:
            correction_suffix = prompts.render(
                prompt_ids.PODCASTS_CORRECT_ORIGINALS,
                target=target,
                low=low,
                high=high,
                first_version=encoded(part),
            )
            # A long first response must not permanently wedge a cached section.
            # Keep its cited originals mandatory while reclaiming optional context.
            correction_ids = list(
                dict.fromkeys(
                    [
                        *section["citations"],
                        *(key for turn in part["turns"] for key in turn["citations"]),
                    ]
                )
            )
            packet = original_pack(
                correction_ids,
                units,
                names,
                budget=PROMPT_BUDGET - len(header) - len(correction_suffix),
            )
            correction = header + encoded(packet) + correction_suffix
            allowed = {item["id"] for item in packet["originals"]}
            prompt_sizes.append(len(correction))
            part = generate(
                bounded(correction),
                WrittenSection,
                citation_scope=allowed,
                validate=validate_length,
            )
        validate_length(part)
        if save_section:
            save_section(
                index + 1,
                {
                    "required_ids": section["citations"],
                    "included": [
                        {
                            "id": u["id"],
                            "source": u["source"],
                            "locator": u["locator"],
                            "sha256": hashlib.sha256(u["text"].encode()).hexdigest(),
                        }
                        for u in packet["originals"]
                    ],
                    "additional_context_omitted": packet["additional_context_omitted"],
                    "prompt_characters": len(prompt),
                    "prompt_character_counts": prompt_sizes,
                    "input_handoff": handoff,
                    "handoff": part["handoff"],
                    "words": word_count(part["turns"]),
                },
            )
        handoff = part["handoff"]
        turns.extend(split_turns(part["turns"], 300 if language == ContentLanguage.RU else 400))
    progress({"stage": StageId.SCRIPT, "completed": len(sections), "total": len(sections)})
    return {"title": plan["title"], "language": language, "turns": turns}
