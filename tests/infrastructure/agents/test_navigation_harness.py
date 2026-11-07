"""Exercise SDK recovery and validation, replacing only the text-runner boundary."""

import pytest
from pydantic import ValidationError

from brofessor.application import pipeline, service, worker
from brofessor.contracts.jobs import JobKind
from brofessor.features.sources import collections
from brofessor.features.sources import navigation as source_navigation
from brofessor.infrastructure.storage.workspace import Workspace
from tests.helpers.collections import Navigator, vault


@pytest.mark.parametrize("settled_steps", [1, 4])
def test_recovery_replays_settled_tools_and_models_after_a_worker_fault(
    tmp_path, monkeypatch, settled_steps
):
    workspace = Workspace(tmp_path / "workspace")
    collections.connect(workspace, vault(tmp_path))

    def step(ctx):
        if ctx["memory"] == "evidence read":
            return {
                "memory": "checked other Studies documents",
                "actions": [
                    {"operation": "list", "collection_id": ctx["roots"][0]["id"], "path": "Studies"}
                ],
            }
        return Navigator.step(ctx)

    runner = Navigator(step)
    monkeypatch.setattr("brofessor.infrastructure.text.runners.generate", runner)
    save = source_navigation.NavigationSession.save
    failed = False

    def crash_after_settlement(session):
        nonlocal failed
        save(session)
        if len(session.state["steps"]) >= settled_steps and not failed:
            failed = True
            raise RuntimeError("controlled worker exit after settled tool")

    monkeypatch.setattr(source_navigation.NavigationSession, "save", crash_after_settlement)
    job = service.submit(workspace, JobKind.ASK, focus="Measured latency?", start_worker=False)
    with pytest.raises(RuntimeError, match="controlled worker exit"):
        pipeline.execute(workspace, job)
    settled = source_navigation.report(workspace, job)["steps"].copy()
    monkeypatch.setattr(source_navigation.NavigationSession, "save", save)
    pipeline.execute(workspace, job)
    state = source_navigation.report(workspace, job)
    assert state["steps"][: len(settled)] == settled
    assert len(set(runner.navigation_prompts)) == len(runner.navigation_prompts)
    assert service.answer_evidence(workspace, job["id"])[0]["quotes"]


@pytest.mark.parametrize("correction", ["coverage", "previews"])
def test_sdk_retries_finishing_without_original_evidence(tmp_path, monkeypatch, correction):
    workspace = Workspace(tmp_path / "workspace")
    collections.connect(workspace, vault(tmp_path))

    def step(ctx):
        root = ctx["roots"][0]["id"]
        observations = ctx["observations"]
        action = {"operation": "finish"}
        if correction == "coverage":
            if not observations and ctx["retry"]:
                action = {
                    "operation": "read",
                    "collection_id": root,
                    "path": "Studies/Experiment.md",
                }
        elif not observations:
            action = {"operation": "search", "collection_id": root, "query": "latency"}
        elif observations[-1][0]["action"]["operation"] == "search" and ctx["retry"]:
            action = {
                "operation": "read",
                "collection_id": root,
                "path": observations[-1][0]["result"]["matches"][0]["path"],
            }
        return {
            "memory": "Check original evidence before finishing",
            "exhaustive": correction == "coverage",
            "scope": [root + ":Studies"] if correction == "coverage" else [],
            "actions": [action],
        }

    runner = Navigator(step)
    monkeypatch.setattr("brofessor.infrastructure.text.runners.generate", runner)
    job = service.submit(workspace, JobKind.ASK, focus="Read all Studies notes", start_worker=False)
    pipeline.execute(workspace, job)
    state = source_navigation.report(workspace, job)
    assert state["units"] and state["status"] == "complete"
    assert service.answer_evidence(workspace, job["id"])[0]["quotes"]
    if correction == "coverage":
        assert state["verification"]["exhaustive"] is True


def test_cancelled_harness_job_resumes_without_repeating_accepted_inference(tmp_path, monkeypatch):
    workspace = Workspace(tmp_path / "workspace")
    collections.connect(workspace, vault(tmp_path))
    runner = Navigator()
    monkeypatch.setattr("brofessor.infrastructure.text.runners.generate", runner)
    save = source_navigation.NavigationSession.save
    job = service.submit(workspace, JobKind.ASK, focus="Measured latency?", start_worker=False)

    def cancel_after_settlement(session):
        save(session)
        if session.state.get("tool_results"):
            workspace.cancel(job["id"])

    monkeypatch.setattr(source_navigation.NavigationSession, "save", cancel_after_settlement)
    worker.run(workspace, once=True)
    assert workspace.job(job["id"])["status"] == "cancelled"
    assert workspace.draft(job["id"]) is None
    assert source_navigation.report(workspace, job)["steps"]
    monkeypatch.setattr(source_navigation.NavigationSession, "save", save)
    workspace.resume(job["id"])
    worker.run(workspace, once=True)
    assert workspace.job(job["id"])["status"] == "succeeded"
    assert len(set(runner.navigation_prompts)) == len(runner.navigation_prompts)


def test_crash_after_navigation_completion_recovers_the_report_artifact(tmp_path, monkeypatch):
    workspace = Workspace(tmp_path / "workspace")
    collections.connect(workspace, vault(tmp_path))
    runner = Navigator()
    monkeypatch.setattr("brofessor.infrastructure.text.runners.generate", runner)
    save = source_navigation.NavigationSession.save

    def crash_before_artifact_registration(session):
        save(session)
        if session.state["status"] == "complete":
            raise RuntimeError("controlled completion fault")

    monkeypatch.setattr(
        source_navigation.NavigationSession, "save", crash_before_artifact_registration
    )
    job = service.submit(workspace, JobKind.ASK, focus="Measured latency?", start_worker=False)
    with pytest.raises(RuntimeError, match="controlled completion fault"):
        pipeline.execute(workspace, job)
    accepted = runner.navigation_prompts.copy()
    monkeypatch.setattr(source_navigation.NavigationSession, "save", save)
    pipeline.execute(workspace, job)
    assert runner.navigation_prompts == accepted
    assert any(
        item["metadata"].get("role") == "source_navigation"
        for item in workspace.artifacts(job["id"])
    )


def test_agent_metadata_counts_toward_the_context_budget(tmp_path, monkeypatch):
    workspace = Workspace(tmp_path / "workspace")
    collections.connect(workspace, vault(tmp_path))
    runner = Navigator()
    monkeypatch.setattr("brofessor.infrastructure.text.runners.generate", runner)
    job = service.submit(workspace, JobKind.ASK, focus="Measured latency?", start_worker=False)
    monkeypatch.setattr(source_navigation, "MAX_CONTEXT", 1000)
    with pytest.raises(ValueError, match="Agent history exceeds"):
        pipeline.execute(workspace, job)
    assert not runner.navigation_prompts
    assert workspace.draft(job["id"]) is None


@pytest.mark.parametrize("invalid", ["operation", "finish_and_read"])
def test_invalid_navigation_is_not_executed_or_cached(tmp_path, monkeypatch, invalid):
    workspace = Workspace(tmp_path / "workspace")
    root = collections.connect(workspace, vault(tmp_path))
    actions = [{"operation": "invented-operation"}]
    if invalid == "finish_and_read":
        actions = [
            {"operation": "finish"},
            {"operation": "read", "collection_id": root["id"], "path": "Studies/Experiment.md"},
        ]
    monkeypatch.setattr(
        "brofessor.infrastructure.text.runners.generate", lambda *a, **kw: {"actions": actions}
    )
    job = service.submit(workspace, JobKind.ASK, focus="Measured latency?", start_worker=False)
    with pytest.raises(ValidationError):
        pipeline.execute(workspace, job)
    assert workspace.sources() == [] and workspace.draft(job["id"]) is None
    monkeypatch.setattr("brofessor.infrastructure.text.runners.generate", Navigator())
    pipeline.execute(workspace, job)
    assert service.answer_evidence(workspace, job["id"])[0]["quotes"]
