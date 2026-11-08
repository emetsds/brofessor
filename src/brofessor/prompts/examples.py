"""Synthetic, local-only examples of the actual prompt composition and framing.

These values are illustrative inputs, not model output or a quality evaluation.
Production workflows still own evidence selection, serialization, and budgets.
"""

import json

from brofessor import prompts
from brofessor.contracts.content import ContentLanguage, Speaker
from brofessor.contracts.text import TextProvider
from brofessor.prompts import ids as prompt_ids

TEXT = "A synthetic bridge carried 1200 kilograms. Flood resistance is unknown."
EVIDENCE = [{"id": "synthetic:1", "locator": "lines 1-1", "text": TEXT}]
ORIGINALS = {
    "originals": [{**EVIDENCE[0], "source": "synthetic.md"}],
    "additional_context_omitted": [],
}


def encoded(value):
    return json.dumps(value, ensure_ascii=False)


def values_for(identifier):
    spec = prompts.catalogue().get(identifier)
    if spec is None:
        raise prompts.PromptError(f"Unknown prompt ID: {identifier}")
    values = {
        "language": ContentLanguage.EN,
        "language_name": "English",
        "focus": "What was tested?",
        "verification": encoded({"exhaustive": True, "documents": 1, "fragments": 1}),
        "evidence": encoded(EVIDENCE),
        "conversation": encoded(
            [{"question": "What is known?", "answer": "Only one load was tested."}]
        ),
        "glossary": encoded(
            [{"term": "load", "sense": "carried weight", "translation": "нагрузка"}]
        ),
        "scope": encoded(
            [{"source": "synthetic.md", "selected_fragments": 1, "readable_fragments": 1}]
        ),
        "slide_count": 3,
        "count": 3,
        "minutes": 20,
        "parts": 4,
        "part_number": 1,
        "section_number": 1,
        "sections": 4,
        "last_part": 4,
        "target_words": 3000,
        "written": 0,
        "target": 750,
        "lower": 638,
        "upper": 862,
        "low": 638,
        "high": 862,
        "previous": "",
        "first_version": encoded(
            {
                "language": ContentLanguage.EN,
                "turns": [
                    {
                        "speaker": Speaker.HOST,
                        "text": "What remains unknown?",
                        "citations": ["synthetic:1"],
                    },
                    {
                        "speaker": Speaker.GUEST,
                        "text": "Flood resistance was not tested.",
                        "citations": ["synthetic:1"],
                    },
                ],
            }
        ),
        "section": encoded(
            {
                "title": "Limits of the test",
                "brief": "Separate tested load from unknown flood resistance.",
                "citations": ["synthetic:1"],
            }
        ),
        "outline": encoded(
            {
                "title": "What the test establishes",
                "sections": [
                    {
                        "title": "The measured load",
                        "brief": "One synthetic test, with stated limits.",
                        "citations": ["synthetic:1"],
                    }
                ],
            }
        ),
        "plan": encoded(
            {
                "title": "What the test establishes",
                "listener_goal": "Distinguish tested and unknown properties.",
                "material_sufficient": False,
                "reason": "A short excerpt cannot support twenty minutes.",
                "source_relationships": [],
                "sections": [],
            }
        ),
        "handoff": encoded({"covered_points": [], "introduced_terms": [], "open_question": ""}),
        "series": encoded(
            {
                "title": "Synthetic series",
                "episode": 1,
                "topics": ["tested load"],
                "shared_terms": [],
            }
        ),
        "occurrences": encoded({"occurrences": []}),
        "turns": encoded(
            [
                {
                    "turn": 1,
                    "speaker": Speaker.GUEST,
                    "text": "Only this load was tested.",
                    "citations": ["synthetic:1"],
                }
            ]
        ),
    }
    if identifier.startswith("books/"):
        values["language"] = ContentLanguage.RU
    needed = set(spec["variables"])
    if needed & {"base", "instructions"}:
        instructions = prompts.render(
            prompt_ids.COMMON_MATERIALS,
            language=ContentLanguage.EN,
            language_name="English",
            focus=values["focus"],
        )
        values["instructions"] = instructions
        if "base" in needed:
            values["base"] = prompts.render(
                prompt_ids.COMMON_EVIDENCE, instructions=instructions, evidence=values["evidence"]
            )
            if identifier.startswith("podcasts/") and identifier != prompt_ids.PODCASTS_SERIES:
                values["base"] += prompts.render(prompt_ids.PODCASTS_VOICES)
            if identifier == prompt_ids.REPORTS_WRITE:
                values["base"] = prompts.render(
                    prompt_ids.REPORTS_SCOPE, base=values["base"], scope=values["scope"]
                )
        if identifier.startswith("podcasts/originals_"):
            values["instructions"] += prompts.render(prompt_ids.PODCASTS_VOICES)
        if identifier.startswith("experiments/"):
            values["instructions"] = prompts.render(
                prompt_ids.EXPERIMENTS_EPISODE_MATERIALS, focus=values["focus"]
            )
            if "base" in needed:
                values["base"] = prompts.render(
                    prompt_ids.EXPERIMENTS_EVIDENCE,
                    instructions=values["instructions"],
                    evidence=values["evidence"],
                )
    if "task" in needed:
        values["task"] = prompts.render(prompt_ids.REPORTS_COMPARISON)
    if "word_instruction" in needed:
        values["word_instruction"] = prompts.render(
            prompt_ids.PODCASTS_WORD_BUDGET,
            **{k: values[k] for k in ["target_words", "written", "target", "lower", "upper"]},
        )
    if "correction_instruction" in needed:
        values["correction_instruction"] = prompts.render(
            prompt_ids.PODCASTS_CORRECTION_RANGE, lower=values["lower"], upper=values["upper"]
        )
    if "prompt" in needed:
        values["prompt"] = prompts.render(
            prompt_ids.PODCASTS_SECTION, **values_for(prompt_ids.PODCASTS_SECTION)
        )
    if "header" in needed:
        values["header"] = prompts.render(prompt_ids.PODCASTS_CHECK, language=values["language"])
    if "conversation_rule" in needed:
        values["conversation_rule"] = prompts.render(prompt_ids.QUESTIONS_SEARCH_CONVERSATION)
    if "translation" in needed:
        values["translation"] = prompts.render(
            prompt_ids.BOOKS_TRANSLATE, **values_for(prompt_ids.BOOKS_TRANSLATE)
        )
    if "metalinguistic" in needed:
        values["metalinguistic"] = prompts.render(prompt_ids.BOOKS_METALINGUISTIC)
    if "agent" in needed:
        values["agent"] = encoded(
            {
                "instructions": [prompts.render(prompt_ids.NAVIGATION_AGENT)],
                "history": [
                    {
                        "kind": "request",
                        "parts": [
                            {
                                "part_kind": "user-prompt",
                                "content": encoded(
                                    {
                                        "task": values["focus"],
                                        "roots": [{"id": "synthetic", "name": "demo"}],
                                    }
                                ),
                            }
                        ],
                    }
                ],
            }
        )
    if "payload" in needed:
        if identifier == prompt_ids.EXPERIMENTS_WHOLE_XHTML:
            payload = {
                "glossary": [],
                "metadata": [],
                "documents": [
                    {
                        "path": "chapter.xhtml",
                        "xhtml": "<html><body><p>Synthetic source.</p></body></html>",
                    }
                ],
            }
        elif identifier == prompt_ids.QUESTIONS_SEARCH:
            payload = {
                "question": values["focus"],
                "conversation": json.loads(values["conversation"]),
            }
        elif identifier.startswith("reading/"):
            payload = {
                "focus": values["focus"],
                "fragments" if identifier == prompt_ids.READING_FRAGMENTS else "notes": EVIDENCE,
            }
        elif identifier == prompt_ids.STUDIES_REVIEW:
            payload = {
                "language": ContentLanguage.EN,
                "questions": [
                    {
                        "id": "q1",
                        "prompt": "Was flood resistance established?",
                        "learner_answer": "It remains unknown.",
                        "criteria": "Distinguish missing evidence from a disproved claim.",
                        "citations": ["synthetic:1"],
                    }
                ],
                "originals": EVIDENCE,
            }
        else:
            payload = {
                "source_language": ContentLanguage.EN,
                "target_language": ContentLanguage.RU,
                "glossary": [],
                "known_meanings": [],
                "candidates": [],
                "blocks": [{"id": "synthetic:1", "text": TEXT, "protected": {}}],
            }
            if identifier == prompt_ids.BOOKS_REPAIR_ALIGNMENT:
                payload["blocks"][0].update(
                    source={"id": "synthetic:1", "text": TEXT},
                    text="Синтетический мост выдержал 1200 килограммов.",
                    rejected_targets=[],
                    error="Missing target for an occurrence",
                    occurrences=[],
                )
            if identifier == prompt_ids.BOOKS_REVISE_TERM:
                payload.update(
                    meaning={"term": "load", "sense": "carried weight", "translation": "нагрузка"},
                    language=ContentLanguage.RU,
                    occurrences=[],
                )
        values["payload"] = encoded(payload)
    return {key: values[key] for key in spec["variables"]}


def _answer(base):
    available = prompts.available()
    if prompt_ids.QUESTIONS_ANSWER in available:
        return prompts.render(prompt_ids.QUESTIONS_ANSWER, base=base)
    if prompt_ids.SLIDES_CREATE in available:
        return prompts.render(prompt_ids.SLIDES_CREATE, base=base, slide_count=3)
    return prompts.render(prompt_ids.PODCASTS_OUTLINE, base=base, minutes=20, parts=4)


def _complete(identifier, rendered):
    """Attach shared parts to a representative complete operation, without inference."""
    if identifier == prompt_ids.COMMON_RUNNER:
        return ""  # The complete frame is still displayed, including its boundary.
    if identifier == prompt_ids.EXPERIMENTS_EPISODE_MATERIALS:
        base = prompts.render(
            prompt_ids.EXPERIMENTS_EVIDENCE, instructions=rendered, evidence=encoded(EVIDENCE)
        )
        return prompts.render(prompt_ids.EXPERIMENTS_EPISODE_OUTLINE, base=base)
    if identifier == prompt_ids.EXPERIMENTS_EVIDENCE:
        return prompts.render(prompt_ids.EXPERIMENTS_EPISODE_OUTLINE, base=rendered)
    if identifier in {prompt_ids.COMMON_MATERIALS, prompt_ids.COMMON_COVERAGE}:
        instructions = rendered
        if identifier == prompt_ids.COMMON_COVERAGE:
            instructions = (
                prompts.render(
                    prompt_ids.COMMON_MATERIALS, **values_for(prompt_ids.COMMON_MATERIALS)
                )
                + rendered
            )
        return _answer(
            prompts.render(
                prompt_ids.COMMON_EVIDENCE, instructions=instructions, evidence=encoded(EVIDENCE)
            )
        )
    if identifier == prompt_ids.COMMON_EVIDENCE:
        return _answer(rendered)
    if identifier == prompt_ids.QUESTIONS_CONVERSATION:
        return _answer(values_for(prompt_ids.QUESTIONS_ANSWER)["base"] + rendered)
    if identifier == prompt_ids.QUESTIONS_SEARCH_CONVERSATION:
        return prompts.render(
            prompt_ids.QUESTIONS_SEARCH,
            **{**values_for(prompt_ids.QUESTIONS_SEARCH), "conversation_rule": rendered},
        )
    if identifier in {
        prompt_ids.REPORTS_COMPARISON,
        prompt_ids.REPORTS_GUIDE,
        prompt_ids.REPORTS_REFERENCE,
        prompt_ids.REPORTS_ARGUMENTS,
    }:
        return prompts.render(
            prompt_ids.REPORTS_WRITE, **{**values_for(prompt_ids.REPORTS_WRITE), "task": rendered}
        )
    if identifier == prompt_ids.REPORTS_TERMINOLOGY:
        defaults = values_for(prompt_ids.REPORTS_WRITE)
        return prompts.render(
            prompt_ids.REPORTS_WRITE, **{**defaults, "base": defaults["base"] + rendered}
        )
    if identifier == prompt_ids.REPORTS_SCOPE:
        return prompts.render(
            prompt_ids.REPORTS_WRITE, **{**values_for(prompt_ids.REPORTS_WRITE), "base": rendered}
        )
    if identifier in {prompt_ids.PODCASTS_VOICES, prompt_ids.PODCASTS_SERIES_CONTEXT}:
        defaults = values_for(prompt_ids.PODCASTS_OUTLINE)
        return prompts.render(
            prompt_ids.PODCASTS_OUTLINE, **{**defaults, "base": defaults["base"] + rendered}
        )
    if identifier in {prompt_ids.PODCASTS_WORD_BUDGET}:
        return prompts.render(
            prompt_ids.PODCASTS_SECTION,
            **{**values_for(prompt_ids.PODCASTS_SECTION), "word_instruction": rendered},
        )
    if identifier in {
        prompt_ids.PODCASTS_CORRECTION_RANGE,
    }:
        return prompts.render(
            prompt_ids.PODCASTS_CORRECT_SECTION,
            **{
                **values_for(prompt_ids.PODCASTS_CORRECT_SECTION),
                "correction_instruction": rendered,
            },
        )
    if identifier == prompt_ids.PODCASTS_ORIGINALS_SECTION:
        return rendered + encoded(ORIGINALS)
    if identifier == prompt_ids.PODCASTS_CORRECT_ORIGINALS:
        header = prompts.render(
            prompt_ids.PODCASTS_ORIGINALS_SECTION,
            **values_for(prompt_ids.PODCASTS_ORIGINALS_SECTION),
        )
        return header + encoded(ORIGINALS) + rendered
    if identifier == prompt_ids.PODCASTS_CHECK:
        return prompts.render(
            prompt_ids.PODCASTS_CHECK_PACKET,
            header=rendered,
            turns=values_for(prompt_ids.PODCASTS_CHECK_PACKET)["turns"],
        ) + encoded(ORIGINALS)
    if identifier == prompt_ids.PODCASTS_CHECK_PACKET:
        return rendered + encoded(ORIGINALS)
    if identifier == prompt_ids.BOOKS_METALINGUISTIC:
        return prompts.render(
            prompt_ids.BOOKS_ALIGN_TRANSLATION,
            **{**values_for(prompt_ids.BOOKS_ALIGN_TRANSLATION), "metalinguistic": rendered},
        )
    if identifier.startswith("navigation/") and identifier != prompt_ids.NAVIGATION_STEP:
        payload = json.loads(values_for(prompt_ids.NAVIGATION_STEP)["agent"])
        if identifier == prompt_ids.NAVIGATION_AGENT:
            payload["instructions"] = [rendered]
        elif identifier != prompt_ids.NAVIGATION_RETRIEVE:
            payload["history"].append(
                {"kind": "request", "parts": [{"part_kind": "retry-prompt", "content": rendered}]}
            )
        return prompts.render(prompt_ids.NAVIGATION_STEP, agent=encoded(payload))
    return rendered


def preview(identifier, *, provider=TextProvider.CODEX, variables=None):
    spec = prompts.catalogue().get(identifier)
    if spec is None:
        raise prompts.PromptError(f"Unknown prompt ID: {identifier}")
    values = values_for(identifier) if variables is None else variables
    if not isinstance(values, dict):
        raise prompts.PromptError("Preview variables must be a JSON object")
    # JSON input values follow the same serialization used by production builders.
    values = {
        key: encoded(value) if isinstance(value, (dict, list)) else value
        for key, value in values.items()
    }
    rendered = prompts.render(identifier, **values)
    full = _complete(identifier, rendered)
    return {
        "id": identifier,
        "path": str(prompts.location(identifier)),
        "source": "frozen" if prompts.snapshot_info() else "current package",
        "snapshot": prompts.snapshot_info(),
        "synthetic_example": variables is None,
        "purpose": spec["purpose"],
        "schema": spec["schema"],
        "versions": spec["versions"],
        "uses": spec["uses"],
        "variables": values,
        "component": rendered,
        "provider": provider,
        "messages": prompts.messages(full, provider),
    }
