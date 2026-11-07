"""A check is a scoped, cancellable operation on an immutable script revision."""

import copy
import json

import pytest
from typer.testing import CliRunner

from brofessor.application import service, tasks, worker
from brofessor.contracts.jobs import JobKind, JobStatus
from brofessor.features.podcasts import checks as script_checks
from brofessor.infrastructure.storage import preferences
from brofessor.infrastructure.storage.workspace import Workspace
from brofessor.interfaces.cli.app import app


@pytest.fixture
def script(tmp_path):
    w = Workspace(tmp_path / "workspace")
    source = tmp_path / "source.txt"
    source.write_text("Eighty kilograms were tested in dry conditions. Floods were not tested.")
    w.add_source(source)
    cite = w.units()[0]["id"]
    job = service.submit(w, JobKind.PODCAST, start_worker=False)
    w.save_draft(
        job["id"],
        {
            "title": "Limits",
            "language": "en",
            "turns": [
                {
                    "speaker": "host" if n % 2 == 0 else "guest",
                    "text": f"Question {n + 1}: were floods tested?",
                    "citations": [cite],
                }
                for n in range(25)
            ],
        },
    )
    w.update_job(job["id"], status=JobStatus.SUCCEEDED)
    return w, job, cite


def result_for(prompt, cite):
    turns = json.loads(prompt.split("\nSCRIPT TURNS:\n")[1].split("\nORIGINALS:\n")[0])
    return {
        "assessments": [
            {
                "turn": item["turn"],
                "status": "supported",
                "explanation": "The question preserves uncertainty.",
                "findings": [],
                "quotes": [{"citation": cite, "text": "Floods were not tested."}],
            }
            for item in turns
        ]
    }


def test_check_resume_keeps_revision_model_and_previously_accepted_batches(script, monkeypatch):
    w, parent, cite = script
    original = copy.deepcopy(w.draft(parent["id"]))
    check = service.check_script(w, parent["id"], start_worker=False)
    calls = []
    fail = True

    def generate(prompt, schema, provider, *args, **kwargs):
        calls.append((prompt, provider))
        if fail and len(calls) == 2:
            raise RuntimeError("Controlled interruption")
        return result_for(prompt, cite)

    monkeypatch.setattr("brofessor.infrastructure.text.runners.generate", generate)
    worker.run(w, once=True)
    assert w.job(check["id"])["status"] == "failed"
    partial = script_checks.report(w, check["id"])
    assert len(partial["assessments"]) == 12 and len(partial["pending_turns"]) == 13
    assert not partial["complete"]
    assert w.draft(parent["id"]) == original
    changed = copy.deepcopy(original["data"])
    changed["turns"][0]["text"] = "A new saved wording."
    service.edit_draft(w, parent["id"], changed, 1)
    choices = tasks.models(w, parent["id"])
    tasks.save_models(
        w, parent["id"], {**choices["data"], "provider": "claude"}, choices["revision"]
    )
    preferences.update(ui_language="ru")
    fail = False
    w.resume(check["id"])
    worker.run(w, once=True)
    report = script_checks.report(w, check["id"])
    assert report["revision"] == 1 and report["complete"]
    assert len(report["assessments"]) == 25 and not report["pending_turns"]
    assert all(provider == "codex" for _, provider in calls)
    assert sum("Question 1:" in prompt for prompt, _ in calls) == 1
    assert w.draft(parent["id"])["data"] == changed
    assert len(tasks.list_tasks(w)) == 1 and tasks.recent_tasks()[0]["child_id"] == parent["id"]


@pytest.mark.parametrize("fault", ["quote", "claim", "missing", "contradiction_without_quote"])
def test_invalid_findings_never_become_accepted_checkpoints(script, monkeypatch, fault):
    w, parent, cite = script
    check = service.check_script(w, parent["id"], start_worker=False)

    def generate(prompt, *args, **kwargs):
        value = result_for(prompt, cite)
        row = value["assessments"][0]
        if fault == "quote":
            row["quotes"][0]["text"] = "Flood resistance was established."
        elif fault == "missing":
            value["assessments"].pop()
        else:
            row.update(
                status="issue",
                findings=[
                    {
                        "claim": "invented script wording"
                        if fault == "claim"
                        else "were floods tested?",
                        "kind": "contradiction",
                        "explanation": "A controlled invalid finding.",
                        "quotes": [],
                    }
                ],
            )
        return value

    monkeypatch.setattr("brofessor.infrastructure.text.runners.generate", generate)
    worker.run(w, once=True)
    assert w.job(check["id"])["status"] == "failed"
    assert not list((w.path / "jobs" / check["id"] / "checkpoints").glob("*.json"))
    assert not script_checks.report(w, check["id"])["assessments"]


def test_uncheckable_turns_are_reported_and_clean_report_is_not_an_approval(script, monkeypatch):
    w, parent, cite = script
    monkeypatch.setattr(script_checks, "PROMPT_BUDGET", 10)
    monkeypatch.setattr(
        "brofessor.infrastructure.text.runners.generate",
        lambda *a, **kw: pytest.fail("No original packet fits"),
    )
    check = service.check_script(w, parent["id"], start_worker=False)
    worker.run(w, once=True)
    report = script_checks.report(w, check["id"])
    assert report["complete"] and not report["assessments"]
    assert len(report["unchecked"]) == 25
    assert "not a search" in report["scope"]


def test_cli_check_uses_shared_worker_and_keeps_explicit_retry_snapshot(script, monkeypatch):
    w, parent, cite = script
    monkeypatch.setattr("brofessor.application.worker.ensure_worker", lambda *_: None)
    command = ["-w", str(w.path), "draft", "check", parent["id"], "--request-key", "review"]
    submitted = CliRunner().invoke(app, command)
    assert submitted.exit_code == 0, submitted.output
    check = json.loads(submitted.output)
    assert check["params"]["revision"] == 1
    assert check["report"] is None
    cancelled = CliRunner().invoke(app, ["-w", str(w.path), "job", "cancel", check["id"]])
    assert cancelled.exit_code == 0 and w.job(check["id"])["status"] == "cancelled"
    assert (
        service.check_script(w, parent["id"], request_key="review", start_worker=False)["id"]
        == check["id"]
    )
    monkeypatch.setattr(
        "brofessor.infrastructure.text.runners.generate", lambda p, *a, **kw: result_for(p, cite)
    )
    w.resume(check["id"])
    worker.run(w, once=True)
    result = CliRunner().invoke(app, ["-w", str(w.path), "draft", "check-report", check["id"]])
    assert result.exit_code == 0 and json.loads(result.output)["total_turns"] == 25
    w.save_draft(parent["id"], w.draft(parent["id"])["data"], expected_revision=1)
    with pytest.raises(ValueError, match="different operation"):
        service.check_script(w, parent["id"], revision=2, request_key="review", start_worker=False)
