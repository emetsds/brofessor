"""Source-grounded practice questions, saved learner answers and bounded feedback."""

import hashlib
from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from brofessor import prompts
from brofessor.contracts.content import (
    ArtifactKind,
    ContentLanguage,
    ContentLanguageValue,
    EvidenceStatus,
    StudyEvidenceStatusValue,
    UnitStatus,
)
from brofessor.contracts.jobs import JobKind, StageId
from brofessor.features import questions
from brofessor.features.sources import navigation as source_navigation
from brofessor.features.sources import reading
from brofessor.infrastructure.storage.workspace import JOBS_DIRECTORY, atomic_json
from brofessor.models import Output, Quote, validate_citations
from brofessor.prompts import ids as prompt_ids

FEEDBACK_BUDGET = 60000


class QuestionKind(StrEnum):
    APPLICATION = "application"
    EXPLANATION = "explanation"


class FeedbackAssessment(StrEnum):
    SUPPORTED = "supported"
    PARTIAL = "partial"
    NEEDS_WORK = "needs_work"
    INSUFFICIENT_CONTEXT = "insufficient_context"


QuestionKindValue = Literal[QuestionKind.APPLICATION, QuestionKind.EXPLANATION]
FeedbackAssessmentValue = Literal[
    FeedbackAssessment.SUPPORTED,
    FeedbackAssessment.PARTIAL,
    FeedbackAssessment.NEEDS_WORK,
    FeedbackAssessment.INSUFFICIENT_CONTEXT,
]


class StudyQuestion(Output):
    id: str = Field(pattern=r"^q[1-9][0-9]*$")
    kind: QuestionKindValue
    prompt: str = Field(min_length=1, max_length=2000)
    expected_answer: str = Field(min_length=1, max_length=4000)
    criteria: list[str] = Field(min_length=1, max_length=6)
    citations: list[str] = Field(min_length=1)
    quotes: list[Quote] = Field(min_length=1, max_length=12)


class StudySet(Output):
    title: str = Field(min_length=1)
    language: ContentLanguageValue
    evidence_status: StudyEvidenceStatusValue
    questions: list[StudyQuestion] = Field(max_length=12)
    answers: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def valid_answers(self):
        ids = [q.id for q in self.questions]
        if len(ids) != len(set(ids)) or set(self.answers) - set(ids):
            raise ValueError("Question IDs must be unique and answers must use those IDs")
        if any(len(text) > 8000 for text in self.answers.values()):
            raise ValueError("Keep each learner answer within 8000 characters")
        if self.evidence_status == EvidenceStatus.SUPPORTED and {
            q.kind for q in self.questions
        } != {
            QuestionKind.APPLICATION,
            QuestionKind.EXPLANATION,
        }:
            raise ValueError("A study set needs application and explanation questions")
        return self


class Feedback(Output):
    question_id: str
    assessment: FeedbackAssessmentValue
    feedback: str = Field(min_length=1, max_length=6000)
    citations: list[str]
    quotes: list[Quote] = Field(max_length=12)

    @model_validator(mode="after")
    def grounded_feedback(self):
        if self.assessment != FeedbackAssessment.INSUFFICIENT_CONTEXT and not self.citations:
            raise ValueError("Feedback needs original evidence or an explicit context limitation")
        return self


class FeedbackBatch(Output):
    language: ContentLanguageValue
    findings: list[Feedback] = Field(min_length=1, max_length=12)


def validate_set(value, units):
    for question in value["questions"]:
        questions.validate_answer({**question, "evidence_status": EvidenceStatus.SUPPORTED}, units)


def write(base, evidence, generate, units, language, count):
    if not evidence:
        return {
            "title": "Недостаточно материала для вопросов"
            if language == ContentLanguage.RU
            else "Insufficient material for questions",
            "language": language,
            "evidence_status": EvidenceStatus.INSUFFICIENT_EVIDENCE,
            "questions": [],
            "answers": {},
        }

    def validate(value):
        validate_set(value, units)
        if value["answers"]:
            raise ValueError("The model must not invent learner answers")
        if len(value["questions"]) > count:
            raise ValueError("Generated more questions than requested")

    return generate(
        prompts.render("studies/create", base=base, count=count),
        StudySet,
        validate=validate,
    )


def save_answers(workspace, job_id, answers, expected_revision):
    from brofessor.application.service import edit_draft

    job = workspace.job(job_id)
    saved = workspace.draft(job_id)
    if not isinstance(answers, dict):
        raise ValueError("Answers must map question IDs to text")
    if job["kind"] != JobKind.STUDY or saved is None:
        raise ValueError("Choose saved practice questions")
    return edit_draft(
        workspace,
        job_id,
        {**saved["data"], "answers": {**saved["data"]["answers"], **answers}},
        expected_revision,
    )


def submit_review(workspace, job_id, *, revision=None, request_key=None, start_worker=True):
    from brofessor.application import service, tasks

    original = workspace.job(job_id)
    saved = workspace.draft(job_id, revision)
    if original["kind"] != JobKind.STUDY or saved is None:
        raise ValueError("Choose saved practice questions and learner answers")
    value = StudySet.model_validate(saved["data"])
    if not any(text.strip() for text in value.answers.values()):
        raise ValueError("Save at least one learner answer before checking it")
    previous = workspace.job_by_request_key(request_key) if request_key else None
    if previous:
        if (
            previous["kind"] != JobKind.REVIEW_STUDY
            or previous["params"]["draft_job_id"] != job_id
            or previous["params"]["revision"] != saved["revision"]
        ):
            raise ValueError("Request key already belongs to a different operation")
        result = previous
    else:
        choices = tasks.models(workspace, job_id)["data"]
        params = service._with_models(original["params"], choices)
        params.update(
            draft_job_id=job_id,
            revision=saved["revision"],
            source_snapshot_job=job_id,
            language=value.language,
        )
        params = service._text_params(JobKind.REVIEW_STUDY, params)
        key = (
            request_key
            or "study-review:" + hashlib.sha256(reading.encoded(params).encode()).hexdigest()
        )
        result = service._submit_text(workspace, JobKind.REVIEW_STUDY, params, key)
    if start_worker:
        from brofessor.application.worker import ensure_worker

        ensure_worker(workspace)
    return result


def review(workspace, job, generate, progress, check):
    params = job["params"]
    saved = workspace.draft(params["draft_job_id"], params["revision"])
    value = StudySet.model_validate(saved["data"]).model_dump()
    units = {
        u["id"]: u
        for u in source_navigation.units(workspace, job)
        if u["status"] == UnitStatus.READY
    }
    answered = [q for q in value["questions"] if value["answers"].get(q["id"], "").strip()]

    def prompt(batch):
        ids = {citation for q in batch for citation in q["citations"]}
        return prompts.render(
            prompt_ids.STUDIES_REVIEW,
            payload=reading.encoded(
                {
                    "language": value["language"],
                    "questions": [
                        {**q, "learner_answer": value["answers"][q["id"]]} for q in batch
                    ],
                    "originals": [units[key] for key in sorted(ids)],
                }
            ),
        )

    findings, batch = [], []

    def assess(packet):
        check()
        by_id = {q["id"]: q for q in packet}

        def validate(result):
            ids = [f["question_id"] for f in result["findings"]]
            if len(ids) != len(set(ids)) or set(ids) != set(by_id):
                raise ValueError("Feedback must assess each answered question exactly once")
            for finding in result["findings"]:
                validate_citations(finding, set(by_id[finding["question_id"]]["citations"]))
                questions.validate_answer(
                    {**finding, "evidence_status": EvidenceStatus.SUPPORTED}, units.values()
                )

        result = generate(
            prompt(packet), FeedbackBatch, citation_scope=set(units), validate=validate
        )
        findings.extend(result["findings"])
        progress(
            {"stage": StageId.STUDY_REVIEW, "completed": len(findings), "total": len(answered)}
        )

    for question in answered:
        if len(prompt([question])) > FEEDBACK_BUDGET:
            raise ValueError("One answer and its original evidence exceed the feedback budget")
        if batch and len(prompt([*batch, question])) > FEEDBACK_BUDGET:
            assess(batch)
            batch = []
        batch.append(question)
    if batch:
        assess(batch)
    result = {
        "title": value["title"],
        "language": value["language"],
        "findings": findings,
        "unanswered": [q["id"] for q in value["questions"] if q not in answered],
    }
    check()
    if workspace.draft(job["id"]) is None:
        workspace.save_draft(job["id"], result)
    path = workspace.path / JOBS_DIRECTORY / job["id"] / "feedback.json"
    atomic_json(path, result)
    workspace.add_artifact(job["id"], path, ArtifactKind.JSON, {"revision": params["revision"]})
