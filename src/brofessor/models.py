"""The small set of model outputs accepted by the workflows."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Output(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Quote(Output):
    citation: str = Field(min_length=1)
    text: str = Field(min_length=1, max_length=2000)


class Answer(Output):
    answer: str = Field(min_length=1)
    citations: list[str]
    evidence_status: Literal["supported", "insufficient_evidence", "conflicting_evidence"] = (
        "supported"
    )
    quotes: list[Quote] = Field(default_factory=list, max_length=24)

    @model_validator(mode="after")
    def supported_answer_has_citations(self):
        if self.evidence_status == "supported" and not self.citations:
            raise ValueError("A supported answer requires source citations")
        return self


class Note(Output):
    title: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=100000)
    citations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def not_blank(self):
        if not self.title.strip() or not self.text.strip():
            raise ValueError("Note title and text must not be blank")
        return self


class Turn(Output):
    speaker: Literal["host", "guest"]
    text: str = Field(min_length=1, max_length=1000)
    citations: list[str] = Field(min_length=1)


class Podcast(Output):
    title: str = Field(min_length=1)
    language: Literal["ru", "en"]
    turns: list[Turn] = Field(min_length=2)


class SlideTable(Output):
    headers: list[str] = Field(min_length=1, max_length=6)
    rows: list[list[str]] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def rectangular(self):
        if any(len(row) != len(self.headers) for row in self.rows):
            raise ValueError("Every table row must match its headers")
        return self


class Slide(Output):
    title: str = Field(min_length=1)
    bullets: list[str] = Field(max_length=6)
    notes: str
    citations: list[str] = Field(min_length=1)
    table: SlideTable | None = None
    steps: list[str] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def one_visual(self):
        if self.table is not None and self.steps:
            raise ValueError("Use a table or a sequence of steps, not both on one slide")
        if self.steps and len(self.steps) < 2:
            raise ValueError("A process needs 2–5 steps")
        if (self.table is not None or self.steps) and len(self.bullets) > 2:
            raise ValueError("Keep at most two brief bullets with a table or process")
        if any(not text.strip() for text in [self.title, *self.bullets, *self.steps]):
            raise ValueError("Slide text must not be blank")
        return self


class Slides(Output):
    title: str = Field(min_length=1)
    language: Literal["ru", "en"]
    slides: list[Slide] = Field(min_length=1, max_length=40)


def validate_citations(value: dict, allowed: set[str]) -> None:
    """Check referential integrity; this is not a factual correctness score."""

    def visit(node):
        if isinstance(node, dict):
            for key, child in node.items():
                if key == "citations":
                    unknown = set(child) - allowed
                    if unknown:
                        raise ValueError(
                            f"Unknown source citations: {len(unknown)} invalid ID(s); "
                            "use original fragment IDs"
                        )
                else:
                    visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(value)
