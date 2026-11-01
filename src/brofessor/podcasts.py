"""Plan and write one long episode, using the existing validated generation boundary."""

import json
import math
import re

from pydantic import Field

from .models import Output, Podcast


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


def write(base, minutes, language, generate, progress, save_outline):
    parts = math.ceil(minutes / 5)

    def validate_outline(value):
        if len(value["sections"]) != parts:
            raise ValueError(f"Episode outline must contain {parts} sections")
        titles = [section["title"].strip().casefold() for section in value["sections"]]
        if len(set(titles)) != parts:
            raise ValueError("Episode outline contains duplicate section titles")

    progress({"stage": "outline", "completed": 0, "total": parts})
    outline = generate(
        base + f"\nPlan one {minutes}-minute learning podcast with exactly {parts} sections. "
        "Assign each section a distinct purpose and evidence IDs; progress from context through "
        "mechanisms, specific examples and consequences. Respect the user focus. Separate facts "
        "from interpretation. Do not repeat a topic just to fill time. Each brief must explain "
        "what this section adds and what belongs in other sections. Sections share the time equally; "
        "do not put minute estimates in titles or briefs. This is one episode, not a series.",
        Outline,
        validate=validate_outline,
    )
    save_outline(outline)
    # Initial prose estimate; measured speech and editorial feedback remain authoritative.
    target = round(minutes * (125 if language == "ru" else 100) / parts)
    turns = []
    for index, section in enumerate(outline["sections"]):
        progress({"stage": "script", "completed": index, "total": parts})
        prompt = (
            base
            + "\nEPISODE OUTLINE:\n"
            + json.dumps(outline, ensure_ascii=False)
            + f"\nWrite section {index + 1} of {parts}: "
            + json.dumps(section, ensure_ascii=False)
            + f"\nWrite {target} spoken words, within 15 percent. Both host and guest must "
            "contribute substantive questions, explanations and examples. Use natural spoken "
            "language, no stage directions or spoken citation IDs. Keep turns under 600 characters. "
            "Write numbers as spoken words, without numbered-list markers. For Russian speech, "
            "use Russian spellings of foreign names instead of mixing Latin spellings into turns. "
            "Cover only this section; do not restart the episode or recap earlier sections. "
            "Only the first section introduces the episode; only the last concludes it. "
            "Interpretations and analogies must be clearly labelled. Do not invent source events. "
            "Do not add repetitive agreement or filler.\nPrevious ending: "
            + " ".join(turn["text"] for turn in turns[-2:])
        )
        part = generate(prompt, Podcast)
        count = word_count(part["turns"])

        def validate_part(value):
            count = word_count(value["turns"])
            if not 0.85 * target <= count <= 1.15 * target:
                raise ValueError(
                    f"Podcast section {index + 1} has {count} words; expected about {target}. "
                    "Resume to retry this section without rewriting accepted sections."
                )
            if {turn["speaker"] for turn in value["turns"]} != {"host", "guest"}:
                raise ValueError(f"Podcast section {index + 1} must contain both speakers")

        if not 0.85 * target <= count <= 1.15 * target or {
            turn["speaker"] for turn in part["turns"]
        } != {"host", "guest"}:
            # One bounded editorial correction, checkpointed independently from the first attempt.
            part = generate(
                prompt + f"\nThe first version has {count} words. Rewrite it to {target} words "
                "within 15 percent by adding useful source-backed detail or removing redundancy. "
                "Preserve this section's purpose, citations and both speakers. First version:\n"
                + json.dumps(part, ensure_ascii=False),
                Podcast,
                validate=validate_part,
            )
        validate_part(part)
        turns.extend(split_turns(part["turns"], 300 if language == "ru" else 400))
    progress({"stage": "script", "completed": parts, "total": parts})
    return {"title": outline["title"], "language": language, "turns": turns}
