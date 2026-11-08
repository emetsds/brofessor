"""Named values serialize into readable plain-string records."""

from brofessor.contracts.content import ContentLanguage
from brofessor.contracts.jobs import JobKind, JobStatus
from brofessor.contracts.text import TextProvider
from brofessor.infrastructure.storage.workspace import Workspace


def test_job_record_exposes_plain_strings_after_named_inputs_and_reopening(tmp_path):
    workspace = Workspace(tmp_path)
    job = workspace.submit(
        JobKind.PODCAST,
        {"language": ContentLanguage.RU, "provider": TextProvider.CODEX},
    )
    workspace.update_job(job["id"], status=JobStatus.RUNNING)
    restored = Workspace(tmp_path).job(job["id"])
    assert restored["kind"] == "podcast"
    assert restored["status"] == "running"
    assert restored["params"] == {"language": "ru", "provider": "codex"}
    assert all(
        type(value) is str
        for value in (restored["kind"], restored["status"], *restored["params"].values())
    )


def test_saved_unknown_values_remain_readable_without_defaulting(tmp_path):
    workspace = Workspace(tmp_path)
    job = workspace.submit("unknown_operation", {})
    workspace.update_job(job["id"], status="unknown_state", progress={"stage": "unknown_stage"})
    restored = Workspace(tmp_path).job(job["id"])
    assert restored["kind"] == "unknown_operation"
    assert restored["status"] == "unknown_state"
    assert restored["progress"] == {"stage": "unknown_stage"}
