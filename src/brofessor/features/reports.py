"""Written-report templates over original excerpts, with a shared saved format."""

import tempfile
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from brofessor import prompts
from brofessor.contracts.content import (
    ArtifactKind,
    ContentLanguage,
    ContentLanguageValue,
    EvidenceStatus,
    EvidenceStatusValue,
)
from brofessor.contracts.jobs import TRANSLATION_JOB_KINDS
from brofessor.features import questions
from brofessor.features.sources import navigation as source_navigation
from brofessor.infrastructure.storage.workspace import JOBS_DIRECTORY
from brofessor.models import Output, Quote
from brofessor.prompts import ids as prompt_ids


class ReportTemplate(StrEnum):
    COMPARISON = "comparison"
    GUIDE = "guide"
    REFERENCE = "reference"
    ARGUMENTS = "arguments"


class SectionOrigin(StrEnum):
    SOURCES = "sources"
    BROFESSOR = "brofessor"


SectionOriginValue = Literal[SectionOrigin.SOURCES, SectionOrigin.BROFESSOR]
TEMPLATES = tuple(ReportTemplate)


class ReportSection(Output):
    heading: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=12000)
    origin: SectionOriginValue
    citations: list[str]
    quotes: list[Quote] = Field(default_factory=list, max_length=24)

    @model_validator(mode="after")
    def source_section_has_evidence(self):
        if not self.heading.strip() or not self.text.strip():
            raise ValueError("Report sections must not be blank")
        if self.origin == SectionOrigin.SOURCES and not self.citations:
            raise ValueError("A source section requires original citations")
        return self


class Report(Output):
    title: str = Field(min_length=1, max_length=200)
    language: ContentLanguageValue
    evidence_status: EvidenceStatusValue
    sections: list[ReportSection] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def evidence_status_matches_references(self):
        if not self.title.strip():
            raise ValueError("Report title must not be blank")
        if self.evidence_status == EvidenceStatus.SUPPORTED and not any(
            s.citations for s in self.sections
        ):
            raise ValueError("A supported report requires original citations")
        if (
            self.evidence_status == EvidenceStatus.CONFLICTING_EVIDENCE
            and len({(q.citation, q.text) for s in self.sections for q in s.quotes}) < 2
        ):
            raise ValueError("Conflicting evidence requires at least two distinct original quotes")
        return self


def validate(value, units):
    for section in value["sections"]:
        questions.validate_answer({**section, "evidence_status": EvidenceStatus.SUPPORTED}, units)


def write(base, evidence, generate, units, language, template):
    if not evidence:
        return {
            "title": "Недостаточно исходных данных"
            if language == ContentLanguage.RU
            else "Insufficient evidence",
            "language": language,
            "evidence_status": EvidenceStatus.INSUFFICIENT_EVIDENCE,
            "sections": [
                {
                    "heading": "Ограничение" if language == ContentLanguage.RU else "Limitation",
                    "text": "Поиск не нашёл подходящих оригинальных фрагментов. Уточните источники или запрос."
                    if language == ContentLanguage.RU
                    else "Search found no matching original excerpts. Refine the sources or request.",
                    "origin": SectionOrigin.BROFESSOR,
                    "citations": [],
                    "quotes": [],
                }
            ],
        }
    task = {
        ReportTemplate.COMPARISON: prompts.render(prompt_ids.REPORTS_COMPARISON),
        ReportTemplate.GUIDE: prompts.render(prompt_ids.REPORTS_GUIDE),
        ReportTemplate.REFERENCE: prompts.render(prompt_ids.REPORTS_REFERENCE),
        ReportTemplate.ARGUMENTS: prompts.render(prompt_ids.REPORTS_ARGUMENTS),
    }[template]
    return generate(
        prompts.render(prompt_ids.REPORTS_WRITE, base=base, task=task),
        Report,
        validate=lambda value: validate(value, units),
    )


def accepted_terminology(workspace, reference, language):
    """Read one accepted translation revision; the report owns no second glossary."""
    from brofessor.features.books import terminology

    if (
        set(reference) != {"job_id", "revision"}
        or type(reference["revision"]) is not int
        or reference["revision"] < 1
    ):
        raise ValueError("Pin terminology to a positive saved translation revision")
    job = workspace.job(reference["job_id"])
    saved = workspace.draft(job["id"], reference["revision"])
    if job["kind"] not in TRANSLATION_JOB_KINDS or saved is None:
        raise ValueError("Choose a saved book translation for accepted terminology")
    if saved["data"]["language"] != language:
        raise ValueError("Accepted terminology must use the report language")
    return [
        terminology.Seed.model_validate(
            {k: term[k] for k in ("term", "sense", "translation")}
        ).model_dump()
        for term in saved["data"]["terms"]
    ]


def publish(workspace, job, draft):
    """Export the saved revision locally; generation and edits use the same path."""
    value = Report.model_validate(draft["data"]).model_dump()
    units = source_navigation.units(workspace, job)
    validate(value, units)
    names = source_navigation.names(workspace, job)
    originals = {u["id"]: u for u in units}
    ru = value["language"] == ContentLanguage.RU
    labels = {
        SectionOrigin.SOURCES: "По источникам" if ru else "From sources",
        SectionOrigin.BROFESSOR: "Адаптация и выводы brofessor"
        if ru
        else "brofessor adaptation and synthesis",
    }
    statuses = {
        EvidenceStatus.SUPPORTED: "Подтверждено источниками" if ru else "Supported by sources",
        EvidenceStatus.INSUFFICIENT_EVIDENCE: "Недостаточно данных"
        if ru
        else "Insufficient evidence",
        EvidenceStatus.CONFLICTING_EVIDENCE: "Противоречивые свидетельства"
        if ru
        else "Conflicting evidence",
    }
    lines = [
        f"# {value['title']}",
        "",
        statuses[value["evidence_status"]],
        "",
        (
            "Область: отобранные оригинальные фрагменты."
            if ru
            else "Scope: selected original excerpts."
        ),
        "",
    ]
    for section in value["sections"]:
        lines.extend(
            [f"## {section['heading']}", "", labels[section["origin"]], "", section["text"], ""]
        )
        for quote in section["quotes"]:
            unit = originals[quote["citation"]]
            lines.extend(
                [
                    f"{names[unit['source_id']]} · {unit['locator']} · {unit['id']}",
                    "",
                    "\n".join("> " + line for line in quote["text"].splitlines()),
                    "",
                ]
            )
    if job["params"].get("terminology"):
        lines.extend(["## " + ("Принятая терминология" if ru else "Accepted terminology"), ""])
        for term in accepted_terminology(
            workspace, job["params"]["terminology"], value["language"]
        ):
            lines.extend([f"{term['term']} ({term['sense']}): {term['translation']}", ""])
    path = workspace.path / JOBS_DIRECTORY / job["id"] / f"report-r{draft['revision']}.md"
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        temporary = Path(handle.name)
        handle.write("\n".join(lines))
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    workspace.add_artifact(job["id"], path, ArtifactKind.MARKDOWN, {"revision": draft["revision"]})
    return path
