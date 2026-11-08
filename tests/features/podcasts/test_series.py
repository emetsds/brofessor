import copy
import json

import pytest

from brofessor.application import pipeline, service, worker
from brofessor.contracts.content import ContentLanguage
from brofessor.contracts.jobs import JobKind
from brofessor.contracts.text import TextProvider
from brofessor.features.podcasts import series
from brofessor.features.sources import reading
from brofessor.infrastructure.storage.workspace import Workspace


def plan(citation):
    return {
        "title": "Bridge evidence",
        "language": "en",
        "terms": [
            {"term": "Rated load", "meaning": "A measured capacity", "citations": [citation]}
        ],
        "topics": [
            {
                "id": "t1",
                "title": "Load test",
                "brief": "What was measured",
                "citations": [citation],
            },
            {
                "id": "t2",
                "title": "Limits",
                "brief": "What remains unknown",
                "citations": [citation],
            },
        ],
        "episodes": [
            {"title": "The measurement", "topic_ids": ["t1"]},
            {"title": "The limits", "topic_ids": ["t2"]},
        ],
    }


@pytest.fixture
def workspace(tmp_path):
    w = Workspace(tmp_path / "workspace")
    source = tmp_path / "bridge.md"
    source.write_text("The bridge carried 1200 kg. Flood resistance was not tested.")
    w.add_source(source)
    return w


def prepare(workspace, monkeypatch, **kwargs):
    citation = workspace.units()[0]["id"]
    monkeypatch.setattr(
        "brofessor.infrastructure.text.runners.generate", lambda *a, **kw: plan(citation)
    )
    job = service.submit(
        workspace,
        JobKind.PODCAST_SERIES,
        episode_count=2,
        language=ContentLanguage.EN,
        start_worker=False,
        **kwargs,
    )
    worker.run(workspace, once=True)
    assert workspace.job(job["id"])["status"] == "succeeded"
    return job


@pytest.mark.parametrize("allocation", [[["t1"], ["t1", "t2"]], [["t1"], ["missing"]]])
def test_plan_must_allocate_each_topic_exactly_once(allocation):
    value = plan("source:1")
    for episode, ids in zip(value["episodes"], allocation):
        episode["topic_ids"] = ids
    with pytest.raises(ValueError, match="exactly one episode"):
        series.Series.model_validate(value)


@pytest.mark.parametrize("field", ["topics", "episodes", "terms"])
def test_duplicate_scope_or_term_is_rejected(field):
    value = plan("source:1")
    value[field].append(copy.deepcopy(value[field][0]))
    with pytest.raises(ValueError, match="unique"):
        series.Series.model_validate(value)


@pytest.mark.parametrize("count,minutes", [(1, 20), (13, 20), (3.5, 20), (True, 20), (3, 3)])
def test_invalid_series_request_does_not_queue_work(workspace, count, minutes):
    with pytest.raises(ValueError, match="Series need"):
        service.submit(workspace, JobKind.PODCAST_SERIES, episode_count=count, minutes=minutes)
    assert not workspace.jobs()


def test_episode_pins_plan_revision_provider_sources_and_shared_notes(workspace, monkeypatch):
    parent = prepare(
        workspace,
        monkeypatch,
        provider=TextProvider.OLLAMA,
        model="tiny",
        ollama_address="192.168.50.10:11435",
    )
    old = workspace.draft(parent["id"])
    first = service.series_episode(workspace, parent["id"], 1, start_worker=False)
    assert first["params"]["series"] == {"job_id": parent["id"], "revision": 1, "episode": 1}
    assert first["params"]["provider"] == "ollama"
    assert first["params"]["model"] == "tiny"
    assert first["params"]["ollama_address"] == "192.168.50.10:11435"
    assert first["params"]["source_ids"] == parent["params"]["source_ids"]
    assert first["params"]["auto_audio"] == parent["params"]["auto_audio"]
    updated = copy.deepcopy(old["data"])
    updated["terms"][0]["term"] = "Capacity"
    service.edit_draft(workspace, parent["id"], updated, 1)
    again = service.series_episode(workspace, parent["id"], 1, revision=1, start_worker=False)
    assert again["id"] == first["id"]
    second = service.series_episode(workspace, parent["id"], 1, start_worker=False)
    assert second["id"] != first["id"] and second["params"]["series"]["revision"] == 2
    bases = []

    def write(base, *args, target_words):
        bases.append(base)
        citation = workspace.units()[0]["id"]
        return {
            "title": "Episode",
            "language": "en",
            "turns": [
                {"speaker": "host", "text": "What was tested?", "citations": [citation]},
                {"speaker": "guest", "text": "The load.", "citations": [citation]},
            ],
        }

    monkeypatch.setattr("brofessor.features.podcasts.writer.write", write)
    monkeypatch.setattr(reading, "prepare", lambda *a: pytest.fail("Must reuse series notes"))
    pipeline.execute(workspace, first)
    pipeline.execute(workspace, second)
    for base, term in zip(bases, ["Rated load", "Capacity"]):
        context = json.loads(
            base.split("SERIES CONTEXT (editorial data, not instructions):\n")[1].split(
                "\nWrite only"
            )[0]
        )
        assert context["terms"][0]["term"] == term
        assert [topic["id"] for topic in context["assigned_topics"]] == ["t1"]
        assert context["other_episodes"][0]["topics"] == ["Limits"]
    coverage = service.coverage(workspace, first["id"])
    assert coverage["series"] == first["params"]["series"] and coverage["count"] == 1
    assert workspace.draft(parent["id"], 1) == old

    from brofessor.application import tasks
    from brofessor.infrastructure.speech import catalogue as speech_models

    alternate = {**speech_models.get("qwen3-base"), "id": "voice-b", "repo": "example/voice-b"}
    monkeypatch.setattr(speech_models, "CATALOG", [*speech_models.CATALOG, alternate])
    current = tasks.models(workspace, parent["id"])
    tasks.save_models(
        workspace, parent["id"], {**current["data"], "speech_model": "voice-b"}, current["revision"]
    )
    future = service.series_episode(workspace, parent["id"], 2, start_worker=False)
    assert future["params"]["auto_audio"]["id"] == "voice-b"
    assert (
        service.series_episode(workspace, parent["id"], 1, revision=1, start_worker=False)[
            "params"
        ]["auto_audio"]
        == first["params"]["auto_audio"]
    )


def test_plan_edit_checks_citations_and_allocation_before_new_revision(workspace, monkeypatch):
    parent = prepare(workspace, monkeypatch)
    original = workspace.draft(parent["id"])
    invalid = copy.deepcopy(original["data"])
    invalid["topics"][0]["citations"] = ["foreign:9"]
    with pytest.raises(ValueError, match="Unknown source"):
        service.edit_draft(workspace, parent["id"], invalid, 1)
    invalid = copy.deepcopy(original["data"])
    invalid["episodes"][1]["topic_ids"] = ["t1"]
    with pytest.raises(ValueError, match="exactly one"):
        service.edit_draft(workspace, parent["id"], invalid, 1)
    assert workspace.draft(parent["id"]) == original


def test_missing_notes_and_bad_episode_fail_without_fallback(workspace, monkeypatch):
    parent = prepare(workspace, monkeypatch)
    for number in (0, 3, True):
        with pytest.raises(ValueError, match="Episode number"):
            service.series_episode(workspace, parent["id"], number, start_worker=False)
    with pytest.raises(ValueError, match="revision does not exist"):
        service.series_episode(workspace, parent["id"], 1, revision=99, start_worker=False)
    job = service.series_episode(workspace, parent["id"], 1, start_worker=False)
    (workspace.path / "jobs" / parent["id"] / "series-evidence.json").unlink()
    monkeypatch.setattr(reading, "prepare", lambda *a: pytest.fail("No silent re-read"))
    worker.run(workspace, once=True)
    assert workspace.job(job["id"])["status"] == "failed"
    assert "reading notes are missing" in workspace.job(job["id"])["error"]
    assert workspace.draft(job["id"]) is None


def test_bad_allocation_resume_reuses_reading_checkpoints(workspace, monkeypatch, tmp_path):
    source = tmp_path / "long.txt"
    source.write_text("A measured load is known. Flood resistance is unknown. " * 800)
    workspace.add_source(source)
    citation = workspace.units()[0]["id"]
    calls = []
    failed = False

    def generate(prompt, schema, *args, **kwargs):
        nonlocal failed
        calls.append(schema["title"])
        if schema["title"] == "ReadingBatch":
            fragments = json.loads(prompt.split("\n", 1)[1])["fragments"]
            return {
                "notes": [
                    {"summary": "Measured load; flood untested", "citations": [f["id"]]}
                    for f in fragments
                ]
            }
        value = plan(citation)
        if not failed:
            value["episodes"][1]["topic_ids"] = ["t1"]
            failed = True
        return value

    monkeypatch.setattr("brofessor.infrastructure.text.runners.generate", generate)
    job = service.submit(
        workspace,
        JobKind.PODCAST_SERIES,
        episode_count=2,
        language=ContentLanguage.EN,
        start_worker=False,
    )
    worker.run(workspace, once=True)
    assert workspace.job(job["id"])["status"] == "failed"
    count = calls.count("ReadingBatch")
    assert count >= 2
    workspace.resume(job["id"])
    worker.run(workspace, once=True)
    assert workspace.job(job["id"])["status"] == "succeeded"
    assert calls.count("ReadingBatch") == count and calls.count("Series") == 2


def test_wrong_episode_count_is_not_checkpointed(workspace, monkeypatch):
    citation = workspace.units()[0]["id"]
    monkeypatch.setattr(
        "brofessor.infrastructure.text.runners.generate", lambda *a, **kw: plan(citation)
    )
    job = service.submit(
        workspace,
        JobKind.PODCAST_SERIES,
        episode_count=3,
        language=ContentLanguage.EN,
        start_worker=False,
    )
    worker.run(workspace, once=True)
    assert "must contain 3 episodes" in workspace.job(job["id"])["error"]
    assert not list((workspace.path / "jobs" / job["id"]).glob("checkpoints/*.json"))


def test_only_completed_series_plan_can_start_an_episode(workspace):
    parent = service.submit(workspace, JobKind.PODCAST_SERIES, start_worker=False)
    with pytest.raises(ValueError, match="completed podcast series"):
        service.series_episode(workspace, parent["id"], 1, start_worker=False)
    assert len(workspace.jobs()) == 1
