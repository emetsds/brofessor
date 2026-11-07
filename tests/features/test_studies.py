"""Practice and feedback use original evidence and pinned learner revisions."""

import copy
import json

import pytest
from streamlit.testing.v1 import AppTest
from typer.testing import CliRunner

from brofessor.application import pipeline, service, tasks, worker
from brofessor.contracts.content import ContentLanguage
from brofessor.contracts.jobs import JobKind, JobStatus
from brofessor.features import studies
from brofessor.infrastructure.storage.workspace import Workspace
from brofessor.interfaces.cli.app import app
from tests.helpers.ui import UI_APP


def setup(tmp_path, monkeypatch):
    workspace = Workspace(tmp_path / "workspace")
    for name, text in [
        ("ratio.txt", "Hit ratio is hits divided by requests."),
        ("power.txt", "Power-loss behavior was not tested."),
    ]:
        path = tmp_path / name
        path.write_text(text)
        workspace.add_source(path)
    model = StudyModel(workspace.units())
    monkeypatch.setattr("brofessor.infrastructure.text.runners.generate", model)
    monkeypatch.setattr("brofessor.application.worker.ensure_worker", lambda _: None)
    return workspace, model


class StudyModel:
    def __init__(self, units):
        self.units = units
        ratio = next(u for u in units if "ratio" in u["text"])
        power = next(u for u in units if "Power" in u["text"])
        self.value = {
            "title": "Using evidence",
            "language": "en",
            "evidence_status": "supported",
            "questions": [
                {
                    "id": "q1",
                    "kind": "application",
                    "prompt": "Four of ten requests hit the cache. What is the hit ratio?",
                    "expected_answer": "0.4",
                    "criteria": ["Divide hits by all requests"],
                    "citations": [ratio["id"]],
                    "quotes": [{"citation": ratio["id"], "text": ratio["text"]}],
                },
                {
                    "id": "q2",
                    "kind": "explanation",
                    "prompt": "Does the experiment prove power-loss safety?",
                    "expected_answer": "No, that behavior was not tested.",
                    "criteria": ["Distinguish untested from false"],
                    "citations": [power["id"]],
                    "quotes": [{"citation": power["id"], "text": power["text"]}],
                },
            ],
            "answers": {},
        }
        self.problem = None
        self.fail_second = False
        self.feedback_calls = []
        self.accepted = []

    def __call__(self, prompt, schema, *args, **kwargs):
        if schema["title"] == "StudySet":
            value = copy.deepcopy(self.value)
            if self.problem == "answers":
                value["answers"] = {"q1": "The model impersonates the learner"}
            elif self.problem == "quote":
                value["questions"][0]["quotes"][0]["text"] = "An invented formula."
            return value
        assert schema["title"] == "FeedbackBatch"
        packet = json.loads(prompt.rsplit("\n", 1)[1])
        self.feedback_calls.append(packet)
        if self.fail_second and len(self.feedback_calls) == 2:
            raise RuntimeError("controlled second packet failure")
        rows = []
        for question in packet["questions"]:
            other = self.value["questions"][1] if self.problem == "cross_citation" else question
            rows.append(
                {
                    "question_id": question["id"],
                    "assessment": "supported" if question["id"] == "q1" else "needs_work",
                    "feedback": "Use the hit ratio equation."
                    if question["id"] == "q1"
                    else "The source says untested, not impossible or guaranteed.",
                    "citations": other["citations"],
                    "quotes": other["quotes"],
                }
            )
        self.accepted.append(prompt)
        return {"language": packet["language"], "findings": rows}


def make_study(workspace):
    job = service.submit(
        workspace,
        JobKind.STUDY,
        focus="Apply the evidence",
        language=ContentLanguage.EN,
        question_count=2,
        start_worker=False,
    )
    pipeline.execute(workspace, job)
    workspace.update_job(job["id"], status=JobStatus.SUCCEEDED)
    return job


@pytest.mark.parametrize("language", ["en", "ru"])
def test_review_pins_saved_answers_language_and_model_while_later_answers_keep_their_history(
    tmp_path, monkeypatch, language
):
    workspace, model = setup(tmp_path, monkeypatch)
    job = make_study(workspace)
    answered = studies.save_answers(
        workspace, job["id"], {"q1": "0.4", "q2": "Safety is guaranteed."}, 1
    )
    if language != answered["data"]["language"]:
        answered = service.edit_draft(
            workspace, job["id"], {**answered["data"], "language": language}, answered["revision"]
        )
    revision = answered["revision"]
    review = studies.submit_review(workspace, job["id"], revision=revision, start_worker=False)
    assert (
        studies.submit_review(workspace, job["id"], revision=revision, start_worker=False)["id"]
        == review["id"]
    )
    studies.save_answers(workspace, job["id"], {"q1": "I changed my answer."}, revision)
    tasks.save_models(
        workspace,
        job["id"],
        {"provider": "claude", "model": None},
        tasks.models(workspace, job["id"])["revision"],
    )
    pipeline.execute(workspace, review)
    answers = {q["id"]: q["learner_answer"] for p in model.feedback_calls for q in p["questions"]}
    assert answers["q1"] == "0.4" and review["params"]["provider"] == "codex"
    assert workspace.draft(job["id"], revision)["data"]["answers"]["q1"] == "0.4"
    assert (
        review["params"]["language"]
        == workspace.draft(review["id"])["data"]["language"]
        == language
    )
    assert workspace.draft(job["id"])["data"]["answers"]["q1"] == "I changed my answer."
    assert service.answer_evidence(workspace, review["id"])
    assert len(tasks.list_tasks(workspace)) == 1


@pytest.mark.parametrize("problem", ["answers", "quote"])
def test_question_generation_cannot_invent_learner_answers_or_cache_invalid_evidence(
    tmp_path, monkeypatch, problem
):
    workspace, model = setup(tmp_path, monkeypatch)
    model.problem = problem
    job = service.submit(
        workspace,
        JobKind.STUDY,
        focus="Apply evidence",
        language=ContentLanguage.EN,
        question_count=2,
        start_worker=False,
    )
    with pytest.raises(ValueError):
        pipeline.execute(workspace, job)
    assert workspace.draft(job["id"]) is None
    model.problem = None
    pipeline.execute(workspace, job)
    assert workspace.draft(job["id"])["data"]["answers"] == {}


def test_feedback_cannot_borrow_another_questions_citations(tmp_path, monkeypatch):
    workspace, model = setup(tmp_path, monkeypatch)
    job = make_study(workspace)
    studies.save_answers(workspace, job["id"], {"q1": "0.4"}, 1)
    review = studies.submit_review(workspace, job["id"], start_worker=False)
    model.problem = "cross_citation"
    with pytest.raises(ValueError, match="citations"):
        pipeline.execute(workspace, review)
    assert workspace.draft(review["id"]) is None
    model.problem = None
    pipeline.execute(workspace, review)
    assert workspace.draft(review["id"])["data"]["unanswered"] == ["q2"]


def test_feedback_resume_reuses_accepted_packets_after_a_later_failure(tmp_path, monkeypatch):
    workspace, model = setup(tmp_path, monkeypatch)
    job = make_study(workspace)
    studies.save_answers(workspace, job["id"], {"q1": "0.4 " * 1500, "q2": "Unknown " * 900}, 1)
    monkeypatch.setattr(studies, "FEEDBACK_BUDGET", 11000)
    model.fail_second = True
    review = studies.submit_review(workspace, job["id"], start_worker=False)
    with pytest.raises(RuntimeError, match="controlled"):
        pipeline.execute(workspace, review)
    assert workspace.draft(review["id"]) is None
    model.fail_second = False
    pipeline.execute(workspace, review)
    assert len(model.accepted) == len(set(model.accepted))
    assert {f["question_id"] for f in workspace.draft(review["id"])["data"]["findings"]} == {
        "q1",
        "q2",
    }


def test_cli_questions_ui_answers_and_cli_feedback_share_one_saved_revision(tmp_path, monkeypatch):
    workspace, _ = setup(tmp_path, monkeypatch)
    runner = CliRunner()
    created = runner.invoke(
        app,
        [
            "-w",
            str(workspace.path),
            "study",
            "create",
            "Apply evidence",
            "--count",
            "2",
            "--language",
            "en",
        ],
    )
    assert created.exit_code == 0, created.output
    job = json.loads(created.output)
    worker.run(workspace, once=True)
    monkeypatch.setattr("sys.argv", ["ui.py", "--workspace", str(workspace.path)])
    ui = AppTest.from_file(UI_APP, default_timeout=30).run()
    assert not ui.exception
    answer = next(w for w in ui.text_area if w.key and w.key.endswith(":answers:q1"))
    answer.set_value("0.4").run()
    ui.button(key="save-" + job["id"]).click().run()
    assert not ui.exception
    checked = runner.invoke(app, ["-w", str(workspace.path), "study", "review", job["id"]])
    assert checked.exit_code == 0, checked.output
    review = json.loads(checked.output)
    worker.run(workspace, once=True)
    ui.run()
    assert not ui.exception
    shown = runner.invoke(app, ["-w", str(workspace.path), "draft", "show", review["id"]])
    result = json.loads(shown.output)
    assert result["evidence"] and result["data"]["findings"][0]["assessment"] == "supported"
    assert any("Use the hit ratio" in item.value for item in ui.text)
