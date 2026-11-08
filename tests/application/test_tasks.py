import shutil
from contextlib import contextmanager

import pytest

from brofessor.application import service, tasks
from brofessor.contracts.content import ArtifactKind, ContentLanguage
from brofessor.contracts.jobs import JobKind, JobStatus
from brofessor.infrastructure.speech import catalogue as speech_models
from brofessor.infrastructure.storage import preferences
from brofessor.infrastructure.storage.workspace import Workspace


@pytest.fixture
def workspace(tmp_path):
    w = Workspace(tmp_path / "workspace")
    source = tmp_path / "source.txt"
    source.write_text("A bridge supports eighty kilograms.")
    w.add_source(source)
    return w


def answer(w, model="first", **kwargs):
    j = service.submit(w, JobKind.ASK, focus="Capacity?", model=model, start_worker=False, **kwargs)
    w.save_draft(j["id"], {"answer": "Eighty kilograms.", "citations": [w.units()[0]["id"]]})
    w.update_job(j["id"], status=JobStatus.SUCCEEDED)
    return w.job(j["id"])


def test_models_are_portable_future_choices_not_mutable_job_inputs(workspace, tmp_path):
    w = workspace
    parent = answer(w)
    original = parent["params"].copy()
    preferences.save_settings(
        "claude", "global", language=ContentLanguage.EN, speech_model="qwen3-base"
    )
    initial = tasks.models(w, parent["id"])
    assert initial["data"]["model"] == "first"
    changed = tasks.save_models(
        w, parent["id"], {"provider": "claude", "model": "second"}, initial["revision"]
    )
    assert w.job(parent["id"])["params"] == original
    child = service.follow_up(w, parent["id"], "Why?", request_key="follow", start_worker=False)
    assert child["params"]["provider"] == "claude" and child["params"]["model"] == "second"
    tasks.apply_defaults(w, parent["id"], changed["revision"])
    assert tasks.models(w, child["id"])["data"]["model"] == "second"
    assert (
        service.follow_up(w, parent["id"], "Why?", request_key="follow", start_worker=False)["id"]
        == child["id"]
    )
    with pytest.raises(ValueError, match="different operation"):
        service.follow_up(w, parent["id"], "Different?", request_key="follow", start_worker=False)
    copied = tmp_path / "moved"
    shutil.copytree(w.path, copied)
    moved = Workspace(copied)
    assert tasks.models(moved, parent["id"])["data"]["model"] == "global"
    assert moved.job(parent["id"])["params"] == original
    assert moved.draft(parent["id"], 1) is not None


def test_regeneration_stays_in_task_preserving_edits_and_first_retry_snapshot(workspace):
    w = workspace
    parent = answer(w)
    original = w.draft(parent["id"])
    prefs = tasks.models(w, parent["id"])
    saved = tasks.save_models(
        w, parent["id"], {"provider": "claude", "model": "other"}, prefs["revision"]
    )
    child = tasks.regenerate(w, parent["id"], request_key="regen", start_worker=False)
    assert child["params"]["regeneration"] == {"job_id": parent["id"], "revision": 1}
    assert child["params"]["model"] == "other"
    assert w.draft(parent["id"]) == original
    assert len(tasks.list_tasks(w)) == 1
    assert tasks.root_job(child, {j["id"]: j for j in w.jobs()}) == parent["id"]
    tasks.apply_defaults(w, parent["id"], saved["revision"])
    assert (
        tasks.regenerate(w, parent["id"], request_key="regen", start_worker=False)["id"]
        == child["id"]
    )
    w.update_job(child["id"], status=JobStatus.FAILED)
    assert w.resume(child["id"])["params"]["model"] == "other"


def test_stale_task_model_save_and_irrelevant_fields_are_rejected(workspace):
    parent = answer(workspace)
    prefs = tasks.models(workspace, parent["id"])
    tasks.save_models(
        workspace, parent["id"], {"provider": "claude", "model": "x"}, prefs["revision"]
    )
    with pytest.raises(ValueError, match="changed"):
        tasks.apply_defaults(workspace, parent["id"], prefs["revision"])
    with pytest.raises(ValueError, match="do not apply"):
        tasks.save_models(
            workspace,
            parent["id"],
            {"provider": "codex", "model": None, "speech_model": "qwen3-base"},
            2,
        )


def test_defaults_save_is_atomic_and_keeps_models_for_other_providers():
    preferences.save_settings(
        "codex", "first", language=ContentLanguage.RU, speech_model="qwen3-base"
    )
    before = preferences.read()
    with pytest.raises(ValueError):
        preferences.save_settings(
            "ollama",
            "local",
            ollama_address="bad",
            language=ContentLanguage.EN,
            speech_model="qwen3-base",
        )
    assert preferences.read() == before
    preferences.save_settings(
        "claude", "second", language=ContentLanguage.EN, speech_model="qwen3-base"
    )
    assert preferences.text_connection("codex")["model"] == "first"
    assert preferences.settings()["model"] == "second"


def test_recent_reads_are_stable_validate_children_and_never_create_missing_projects(
    workspace, tmp_path
):
    first = answer(workspace)
    second = service.submit(workspace, JobKind.SLIDES, focus="Other topic", start_worker=False)
    missing = tmp_path / "missing"
    preferences.update(
        recent_tasks=[
            {
                "workspace_path": str(workspace.path),
                "root_id": first["id"],
                "child_id": second["id"],
            },
            {"workspace_path": str(missing), "root_id": "none", "child_id": "none"},
        ]
    )
    before = preferences.read()
    rows = tasks.recent_tasks()
    assert rows[0]["child_id"] == first["id"] and rows[0]["available"]
    assert not rows[1]["available"] and not missing.exists()
    assert preferences.read() == before
    assert tasks.recent_tasks() == rows
    tasks.record_open(workspace, second["id"])
    assert tasks.recent_tasks()[0]["root_id"] == second["id"]


def test_failed_recent_write_does_not_fail_saved_job(workspace, monkeypatch):
    @contextmanager
    def read_only():
        raise OSError("read only")
        yield

    monkeypatch.setattr(preferences, "edit", read_only)
    job = service.submit(workspace, JobKind.ASK, focus="Saved?", start_worker=False)
    assert workspace.job(job["id"])["status"] == "queued"
    assert "recent" in job["notice"]


def test_prefix_filter_finds_related_briefs_without_splitting_or_reopening_tasks(workspace):
    parent = answer(workspace)
    child = service.follow_up(
        workspace, parent["id"], "Сравнение голосов моста", start_worker=False
    )
    workspace.update_job(child["id"], status=JobStatus.SUCCEEDED)
    answer(workspace, model="unrelated")
    before = preferences.read()["recent_tasks"]
    rows = tasks.list_tasks(workspace, query="СРА ГОЛ")
    assert [row["root_id"] for row in rows] == [parent["id"]]
    assert (
        rows[0]["match_id"] == child["id"] and rows[0]["match_title"] == "Сравнение голосов моста"
    )
    assert not tasks.list_tasks(workspace, query="олос")
    assert not tasks.list_tasks(workspace, query="гол", kind="podcast")
    parent_row = next(
        row for row in tasks.list_tasks(workspace, query="CAP") if row["root_id"] == parent["id"]
    )
    assert parent_row["match_id"] == parent["id"] and parent_row["child_id"] == child["id"]
    assert preferences.read()["recent_tasks"] == before
    tasks.delete(workspace, parent["id"])
    assert not tasks.list_tasks(workspace, query="гол")


def test_delete_hides_whole_task_and_restore_preserves_sources_versions_and_files(
    workspace, tmp_path
):
    parent = answer(workspace)
    child = service.follow_up(workspace, parent["id"], "Why?", start_worker=False)
    workspace.update_job(child["id"], status=JobStatus.SUCCEEDED)
    other = answer(workspace, model="unrelated")
    artifact = workspace.path / "artifacts" / "answer.md"
    artifact.parent.mkdir()
    artifact.write_text("Saved result")
    workspace.add_artifact(child["id"], artifact, ArtifactKind.MARKDOWN, {"revision": 1})
    recovery = workspace.path / "recovery" / "unsaved.json"
    recovery.parent.mkdir()
    recovery.write_text('{"text":"Unfinished edits"}')
    before = (
        workspace.jobs(),
        workspace.sources(),
        workspace.draft(parent["id"]),
        workspace.artifacts(child["id"]),
    )
    tasks.delete(workspace, child["id"])
    assert [r["root_id"] for r in tasks.list_tasks(workspace)] == [other["id"]]
    assert [r["root_id"] for r in tasks.list_tasks(workspace, deleted=True)] == [parent["id"]]
    assert [r["root_id"] for r in tasks.recent_tasks()] == [other["id"]]
    assert {j["id"] for j in tasks.visible_jobs(workspace)} == {other["id"]}
    assert (
        workspace.jobs(),
        workspace.sources(),
        workspace.draft(parent["id"]),
        workspace.artifacts(child["id"]),
    ) == before
    assert artifact.read_text() == "Saved result" and "Unfinished edits" in recovery.read_text()
    copied = tmp_path / "copied"
    shutil.copytree(workspace.path, copied)
    moved = Workspace(copied)
    assert tasks.deleted_roots(moved) == {parent["id"]}
    tasks.restore(moved, child["id"])
    assert {r["root_id"] for r in tasks.list_tasks(moved)} == {parent["id"], other["id"]}
    assert moved.draft(parent["id"]) == workspace.draft(parent["id"])
    assert tasks.deleted_roots(workspace) == {parent["id"]}


def test_delete_blocks_active_descendants_and_new_work_until_restore(workspace):
    parent = answer(workspace)
    child = service.follow_up(workspace, parent["id"], "Why?", start_worker=False)
    with pytest.raises(ValueError, match="Cancel active"):
        tasks.delete(workspace, parent["id"])
    workspace.update_job(child["id"], status=JobStatus.RUNNING)
    with pytest.raises(ValueError, match="Cancel active"):
        tasks.delete(workspace, child["id"])
    workspace.update_job(child["id"], status=JobStatus.INTERRUPTED)
    tasks.delete(workspace, parent["id"])
    with pytest.raises(ValueError, match="Restore this task"):
        workspace.resume(child["id"])
    with pytest.raises(ValueError, match="Restore this task"):
        service.follow_up(workspace, parent["id"], "Another question?", start_worker=False)
    tasks.restore(workspace, parent["id"])
    assert workspace.resume(child["id"])["status"] == "queued"


def test_speech_choice_is_copied_and_render_override_does_not_change_default(
    workspace, monkeypatch
):
    catalog = [
        dict(
            id=name,
            name=name,
            repo="example/" + name,
            revision="a" * 40,
            languages=["ru", "en"],
            engine="qwen3-mlx",
        )
        for name in ("voice-a", "voice-b")
    ]
    monkeypatch.setattr(speech_models, "CATALOG", catalog)
    preferences.update(tts_model="voice-a")
    job = service.submit(workspace, JobKind.PODCAST, start_worker=False)
    cite = workspace.units()[0]["id"]
    workspace.save_draft(
        job["id"],
        {
            "title": "Audio",
            "language": "ru",
            "turns": [
                {"speaker": "host", "text": "One", "citations": [cite]},
                {"speaker": "guest", "text": "Two", "citations": [cite]},
            ],
        },
    )
    preferences.update(tts_model="voice-b")
    first = service.render(workspace, job["id"], start_worker=False)
    assert first["params"]["model"].startswith("example/voice-a@")
    explicit = service.render(workspace, job["id"], model="voice-b", start_worker=False)
    assert explicit["params"]["model"].startswith("example/voice-b@")
    assert tasks.models(workspace, job["id"])["data"]["speech_model"] == "voice-a"
    assert preferences.read()["tts_model"] == "voice-b"
