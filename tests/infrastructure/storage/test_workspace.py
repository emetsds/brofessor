import hashlib
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from brofessor.contracts.content import ArtifactKind
from brofessor.contracts.jobs import JobKind, JobStatus
from brofessor.infrastructure.formats import ingestion as sources
from brofessor.infrastructure.storage.workspace import Workspace


@pytest.fixture
def workspace(tmp_path):
    return Workspace(tmp_path / "workspace")


def test_concurrent_request_key_has_one_job_and_conflicting_retry_is_rejected(workspace):
    barrier = Barrier(8)

    def submit():
        barrier.wait()
        return workspace.submit(JobKind.ASK, {"question": "Synthetic fact?"}, "same-request")

    with ThreadPoolExecutor(max_workers=8) as pool:
        jobs = list(pool.map(lambda _: submit(), range(8)))
    assert len({job["id"] for job in jobs}) == 1
    assert len(workspace.jobs()) == 1
    with pytest.raises(ValueError, match="different operation"):
        workspace.submit(JobKind.ASK, {"question": "A different question?"}, "same-request")
    assert workspace.jobs()[0]["params"] == {"question": "Synthetic fact?"}


def test_concurrent_claims_never_return_same_job(workspace):
    submitted = [workspace.submit(JobKind.ASK, {"index": index}) for index in range(8)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        claimed = list(pool.map(lambda _: workspace.claim(), range(8)))
    assert {job["id"] for job in claimed} == {job["id"] for job in submitted}
    assert workspace.claim() is None
    assert all(job["status"] == "running" for job in workspace.jobs())


def test_import_snapshot_hash_matches_extracted_content_when_input_changes(
    workspace, tmp_path, monkeypatch
):
    incoming = tmp_path / "chapter.txt"
    snapshot = "The original synthetic observation.\n"
    incoming.write_text(snapshot)
    extract = sources.extract_source

    def change_input_before_extraction(path):
        incoming.write_text("The input changed while the import was in progress.\n")
        return extract(path)

    monkeypatch.setattr(sources, "extract_source", change_input_before_extraction)
    source = workspace.add_source(incoming)
    stored = (workspace.path / source["original"]).read_bytes()
    extracted = "".join(unit["text"] for unit in workspace.units([source["id"]]))
    assert source["hash"] == hashlib.sha256(stored).hexdigest()
    assert stored.decode() == extracted == snapshot
    assert incoming.read_text() != snapshot


def test_import_deduplicates_bytes_and_keeps_same_named_sources_separate(workspace, tmp_path):
    first = tmp_path / "first" / "chapter.txt"
    second = tmp_path / "second" / "chapter.txt"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_text("Synthetic fact one.\n")
    second.write_text("Synthetic fact two.\n")
    a = workspace.add_source(first)
    b = workspace.add_source(second)
    assert a["id"] != b["id"]
    assert a["original"] != b["original"]
    second.write_bytes(first.read_bytes())
    assert workspace.add_source(second)["id"] == a["id"]
    reopened = Workspace(workspace.path)
    assert len(reopened.sources()) == 2
    assert "two" in reopened.units([b["id"]])[0]["text"]
    assert all(not Path(source["original"]).is_absolute() for source in reopened.sources())


def test_concurrent_same_source_import_has_one_original_and_unit_set(workspace, tmp_path):
    incoming = tmp_path / "chapter.txt"
    incoming.write_text("A shared synthetic source.\n")
    with ThreadPoolExecutor(max_workers=6) as pool:
        imported = list(pool.map(lambda _: workspace.add_source(incoming), range(6)))
    assert len({source["id"] for source in imported}) == 1
    assert len(workspace.sources()) == len(workspace.units()) == 1
    assert len(list((workspace.path / "originals").iterdir())) == 1


def test_failed_import_is_not_published_and_staging_file_is_removed(workspace, tmp_path):
    incoming = tmp_path / "empty.txt"
    incoming.write_text(" \n\t")
    with pytest.raises(ValueError, match="No text"):
        workspace.add_source(incoming)
    assert workspace.sources() == workspace.units() == []
    assert not list((workspace.path / "originals").glob("*"))


def test_import_uses_same_source_size_limit(workspace, tmp_path, monkeypatch):
    incoming = tmp_path / "chapter.txt"
    incoming.write_text("x" * 21)
    monkeypatch.setattr(sources, "MAX_SOURCE_BYTES", 20)
    monkeypatch.setattr(
        sources, "extract_source", lambda _: pytest.fail("Oversize file was parsed")
    )
    with pytest.raises(ValueError, match="limit|MiB"):
        workspace.add_source(incoming)
    assert workspace.sources() == []


def test_cancel_and_resume_keep_progress_and_clear_failure(workspace):
    queued = workspace.submit(JobKind.ASK, {})
    assert workspace.cancel(queued["id"])["status"] == "cancelled"
    assert workspace.claim() is None
    assert workspace.resume(queued["id"])["status"] == "queued"
    running = workspace.claim()
    workspace.update_job(running["id"], progress={"stage": "reading", "completed": 3})
    cancelled = workspace.cancel(running["id"])
    assert cancelled["status"] == "running"
    assert cancelled["cancel_requested"] == 1
    workspace.update_job(
        running["id"], status=JobStatus.CANCELLED, error="Stopped during generation"
    )
    resumed = workspace.resume(running["id"])
    assert resumed["status"] == "queued"
    assert resumed["cancel_requested"] == 0
    assert resumed["error"] is None
    assert resumed["progress"] == {"stage": "reading", "completed": 3}


def test_cancel_before_success_commit_wins_and_resume_can_complete(workspace):
    submitted = workspace.submit(JobKind.ASK, {})
    workspace.claim()
    # The worker's last callback observed no cancellation, then another client
    # cancelled before it committed success. Finalization must use current state.
    assert workspace.job(submitted["id"])["cancel_requested"] == 0
    Workspace(workspace.path).cancel(submitted["id"])
    workspace.update_job(submitted["id"], status=JobStatus.SUCCEEDED, progress={"completed": 3})
    cancelled = workspace.job(submitted["id"])
    assert cancelled["status"] == "cancelled"
    assert cancelled["progress"] == {"completed": 3}
    workspace.resume(submitted["id"])
    workspace.claim()
    workspace.update_job(submitted["id"], status=JobStatus.SUCCEEDED)
    assert workspace.job(submitted["id"])["status"] == "succeeded"


@pytest.mark.parametrize("status", ["queued", "running", "succeeded"])
def test_only_resumable_statuses_can_resume(workspace, status):
    job = workspace.submit(JobKind.ASK, {})
    workspace.update_job(job["id"], status=status)
    with pytest.raises(ValueError, match="Only"):
        workspace.resume(job["id"])
    assert workspace.job(job["id"])["status"] == status


def test_revision_conflict_retains_manual_edits_and_history(workspace):
    job = workspace.submit(JobKind.SLIDES, {})
    first = workspace.save_draft(job["id"], {"title": "Generated title"})
    edited = workspace.save_draft(job["id"], {"title": "Author's title"}, first["revision"])
    with pytest.raises(ValueError, match="Draft changed"):
        workspace.save_draft(job["id"], {"title": "Stale overwrite"}, first["revision"])
    assert workspace.draft(job["id"])["data"] == {"title": "Author's title"}
    assert workspace.draft(job["id"], 1)["data"] == {"title": "Generated title"}
    assert edited["revision"] == 2
    workspace.update_job(job["id"], status=JobStatus.FAILED)
    workspace.resume(job["id"])
    assert workspace.draft(job["id"])["data"] == {"title": "Author's title"}


def test_concurrent_revision_edits_have_one_winner(workspace):
    job = workspace.submit(JobKind.SLIDES, {})
    workspace.save_draft(job["id"], {"title": "Initial"})
    barrier = Barrier(2)

    def edit(title):
        barrier.wait()
        try:
            return workspace.save_draft(job["id"], {"title": title}, 1)
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(edit, ["First editor", "Second editor"]))
    winners = [result for result in outcomes if result is not None]
    assert len(winners) == 1
    assert workspace.draft(job["id"])["data"] == winners[0]["data"]
    assert workspace.draft(job["id"], 1)["data"] == {"title": "Initial"}


def test_artifacts_stay_inside_workspace_and_unknown_schema_is_rejected(workspace, tmp_path):
    job = workspace.submit(JobKind.SLIDES, {})
    with pytest.raises(ValueError):
        workspace.add_artifact(job["id"], tmp_path / "outside.pptx", ArtifactKind.PPTX, {})
    artifact = workspace.path / "jobs" / job["id"] / "draft.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("{}")
    workspace.add_artifact(job["id"], artifact, ArtifactKind.JSON, {"revision": 1})
    assert workspace.artifacts(job["id"])[0]["path"] == f"jobs/{job['id']}/draft.json"
    with sqlite3.connect(workspace.path / "workspace.sqlite3") as db:
        db.execute("PRAGMA user_version=999")
    with pytest.raises(ValueError, match="Unsupported workspace schema"):
        Workspace(workspace.path)
