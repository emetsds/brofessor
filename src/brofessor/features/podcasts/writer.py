"""Plan and write one long episode, using the existing validated generation boundary."""

import json
import math
import re
from enum import StrEnum

from pydantic import Field

from brofessor import prompts
from brofessor.contracts.content import ContentLanguage, Speaker
from brofessor.contracts.jobs import StageId
from brofessor.models import Output, Podcast
from brofessor.prompts import ids as prompt_ids


class WritingMethod(StrEnum):
    CLASSIC = "classic"
    ORIGINALS = "originals"


class Section(Output):
    title: str = Field(min_length=1, max_length=160)
    brief: str = Field(min_length=1, max_length=1200)
    citations: list[str] = Field(min_length=1)


class Outline(Output):
    title: str = Field(min_length=1)
    sections: list[Section] = Field(min_length=1, max_length=12)


def word_count(turns):
    return sum(len(turn["text"].split()) for turn in turns)


def duration_feedback(plan, minutes, seconds):
    """Measured duration is authoritative; word counts only guide substantive editing."""
    target = minutes * 60
    words = word_count(plan["turns"])
    matches = abs(seconds - target) <= target * 0.1
    if minutes >= 20:
        matches = matches and 1200 <= seconds <= 3600
    return {
        "requested_seconds": target,
        "duration_matches": matches,
        "duration_difference_percent": round((seconds / target - 1) * 100, 2),
        "script_words": words,
        "measured_words_per_minute": round(words * 60 / seconds, 2),
        "suggested_word_count": round(words * target / seconds),
    }


def split_turns(turns, limit):
    """Split at sentence/word boundaries, preserving speaker, citations and all words."""
    result = []
    for turn in turns:
        remaining = turn["text"].strip()
        while len(remaining) > limit:
            cut = remaining.rfind(" ", 0, limit + 1)
            if cut <= 0:
                raise ValueError("A speech word is too long; edit the draft")
            sentences = list(re.finditer(r"[.!?…][\"»]?(?=\s)", remaining[: cut + 1]))
            if sentences:
                cut = sentences[-1].end()
            result.append({**turn, "text": remaining[:cut].strip()})
            remaining = remaining[cut:].strip()
        if remaining:
            result.append({**turn, "text": remaining})
    return result


def write(
    base,
    minutes,
    language,
    generate,
    progress,
    save_outline,
    *,
    target_words=None,
    writer_context=None,
    save_section=None,
):
    if writer_context is not None:
        from brofessor.features.podcasts.episode_writer import write as grounded_write

        if target_words is None:
            raise ValueError("Source-backed writing requires original context and a word budget")
        return grounded_write(
            writer_context,
            minutes,
            language,
            generate,
            progress,
            save_outline,
            target_words=target_words,
            save_section=save_section,
        )
    parts = math.ceil(minutes / 5)

    def validate_outline(value):
        if len(value["sections"]) != parts:
            raise ValueError(f"Episode outline must contain {parts} sections")
        titles = [section["title"].strip().casefold() for section in value["sections"]]
        if len(set(titles)) != parts:
            raise ValueError("Episode outline contains duplicate section titles")

    progress({"stage": StageId.OUTLINE, "completed": 0, "total": parts})
    outline = generate(
        prompts.render(prompt_ids.PODCASTS_OUTLINE, base=base, minutes=minutes, parts=parts),
        Outline,
        validate=validate_outline,
    )
    save_outline(outline)
    if target_words is None:
        raise ValueError("Podcast writing requires a frozen word budget")
    target = round(target_words / parts)
    turns = []
    for index, section in enumerate(outline["sections"]):
        progress({"stage": StageId.SCRIPT, "completed": index, "total": parts})
        written = word_count(turns)
        target = round((target_words - written) / (parts - index))
        lower, upper = math.ceil(0.85 * target), math.floor(1.15 * target)
        if index == parts - 1:
            margin = max(1, round(target_words * 0.02))
            lower = max(lower, target_words - margin - written)
            upper = min(upper, target_words + margin - written)
        word_instruction = prompts.render(
            prompt_ids.PODCASTS_WORD_BUDGET,
            target_words=target_words,
            written=written,
            target=target,
            lower=lower,
            upper=upper,
        )
        correction_instruction = prompts.render(
            prompt_ids.PODCASTS_CORRECTION_RANGE, lower=lower, upper=upper
        )
        prompt = prompts.render(
            prompt_ids.PODCASTS_SECTION,
            base=base,
            outline=json.dumps(outline, ensure_ascii=False),
            section_number=index + 1,
            parts=parts,
            section=json.dumps(section, ensure_ascii=False),
            word_instruction=word_instruction,
            previous=" ".join(turn["text"] for turn in turns[-2:]),
        )
        part = generate(prompt, Podcast)
        count = word_count(part["turns"])

        def validate_part(value):
            count = word_count(value["turns"])
            if not lower <= count <= upper:
                raise ValueError(
                    f"Podcast section {index + 1} has {count} words; expected about {target}. "
                    "Resume to retry this section without rewriting accepted sections."
                )
            if {turn["speaker"] for turn in value["turns"]} != {Speaker.HOST, Speaker.GUEST}:
                raise ValueError(f"Podcast section {index + 1} must contain both speakers")

        if not lower <= count <= upper or {turn["speaker"] for turn in part["turns"]} != {
            Speaker.HOST,
            Speaker.GUEST,
        }:
            # One bounded editorial correction, checkpointed independently from the first attempt.
            part = generate(
                prompts.render(
                    prompt_ids.PODCASTS_CORRECT_SECTION,
                    prompt=prompt,
                    count=count,
                    target=target,
                    correction_instruction=correction_instruction,
                    first_version=json.dumps(part, ensure_ascii=False),
                ),
                Podcast,
                validate=validate_part,
            )
        validate_part(part)
        turns.extend(split_turns(part["turns"], 300 if language == ContentLanguage.RU else 400))
    progress({"stage": StageId.SCRIPT, "completed": parts, "total": parts})
    return {"title": outline["title"], "language": language, "turns": turns}
