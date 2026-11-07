"""A saved topic allocation and vocabulary, shared by ordinary podcast jobs."""

import json
from collections import Counter
from typing import Final

from pydantic import Field, model_validator

from brofessor import prompts
from brofessor.contracts.jobs import StageId
from brofessor.features.sources.reading import COVERAGE_FILENAME
from brofessor.infrastructure.storage.workspace import JOBS_DIRECTORY, atomic_json
from brofessor.models import Output, validate_citations
from brofessor.prompts import ids as prompt_ids

EVIDENCE_FILENAME: Final = "series-evidence.json"


class Topic(Output):
    id: str = Field(pattern=r"^t[1-9][0-9]*$")
    title: str = Field(min_length=1, max_length=160)
    brief: str = Field(min_length=1, max_length=1200)
    citations: list[str] = Field(min_length=1)


class Term(Output):
    term: str = Field(min_length=1, max_length=160)
    meaning: str = Field(min_length=1, max_length=600)
    citations: list[str] = Field(min_length=1)


class Episode(Output):
    title: str = Field(min_length=1, max_length=160)
    topic_ids: list[str] = Field(min_length=1, max_length=60)


class Series(Output):
    title: str = Field(min_length=1, max_length=160)
    language: str = Field(pattern=r"^(ru|en)$")
    terms: list[Term] = Field(max_length=30)
    topics: list[Topic] = Field(min_length=2, max_length=60)
    episodes: list[Episode] = Field(min_length=2, max_length=12)

    @model_validator(mode="after")
    def topics_are_allocated_once(self):
        def unique(values, label):
            normalized = [" ".join(value.split()).casefold() for value in values]
            if not all(normalized) or len(set(normalized)) != len(normalized):
                raise ValueError(f"Series {label} must be nonempty and unique")

        unique([topic.id for topic in self.topics], "topic IDs")
        unique([topic.title for topic in self.topics], "topic titles")
        unique([episode.title for episode in self.episodes], "episode titles")
        unique([term.term for term in self.terms], "terms")
        assigned = Counter(topic for episode in self.episodes for topic in episode.topic_ids)
        if assigned != Counter(topic.id for topic in self.topics):
            raise ValueError("Every series topic must belong to exactly one episode")
        return self


def write(base, count, minutes, generate, progress):
    progress({"stage": StageId.SERIES_PLAN})

    def validate(value):
        if len(value["episodes"]) != count:
            raise ValueError(f"Series plan must contain {count} episodes")

    return generate(
        prompts.render(prompt_ids.PODCASTS_SERIES, base=base, count=count, minutes=minutes),
        Series,
        validate=validate,
    )


def episode_context(plan, number):
    if type(number) is not int or not 1 <= number <= len(plan["episodes"]):
        raise ValueError("Episode number is outside this series plan")
    selected = plan["episodes"][number - 1]
    topics = {topic["id"]: topic for topic in plan["topics"]}
    return {
        "series_title": plan["title"],
        "episode_number": number,
        "episode_count": len(plan["episodes"]),
        "terms": plan["terms"],
        "episode_title": selected["title"],
        "assigned_topics": [topics[key] for key in selected["topic_ids"]],
        "other_episodes": [
            {
                "title": episode["title"],
                "topics": [topics[key]["title"] for key in episode["topic_ids"]],
            }
            for index, episode in enumerate(plan["episodes"], 1)
            if index != number
        ],
    }


def reading_notes(workspace, reference, folder, allowed):
    """Use the series' accepted notes without another model read or a cross-job cache."""
    parent = workspace.path / JOBS_DIRECTORY / reference["job_id"]
    try:
        evidence = json.loads((parent / EVIDENCE_FILENAME).read_text())
        coverage = json.loads((parent / COVERAGE_FILENAME).read_text())
    except FileNotFoundError:
        raise ValueError(
            "Series reading notes are missing; restore the series project files"
        ) from None
    validate_citations(evidence, allowed)
    ids = {citation for item in evidence for citation in item.get("citations", [item.get("id")])}
    if not ids or not ids <= allowed or set(coverage["read"]) != allowed:
        raise ValueError("Series reading notes do not match the selected sources")
    coverage["series"] = reference
    atomic_json(folder / COVERAGE_FILENAME, coverage)
    return evidence, coverage
