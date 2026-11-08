import json
import re

import pytest

from brofessor.application import pipeline, service, worker
from brofessor.contracts.jobs import JobKind
from brofessor.features.podcasts import writer as podcasts
from brofessor.infrastructure.storage.workspace import Workspace


def dialogue(citation, words, language):
    # Synthetic model contract output, never a quality fixture.
    word = "факт" if language == "ru" else "fact"
    turns = []
    while words:
        size = min(words, 40)
        turns.append(
            {
                "speaker": "host" if len(turns) % 2 == 0 else "guest",
                "text": " ".join([word] * size),
                "citations": [citation],
            }
        )
        words -= size
    return {"title": "Facts", "language": language, "turns": turns}


@pytest.fixture
def workspace(tmp_path):
    w = Workspace(tmp_path / "workspace")
    source = tmp_path / "source.md"
    source.write_text("A bridge carried 1200 kilograms. Flood resistance is unknown.")
    w.add_source(source)
    return w


@pytest.mark.parametrize(
    "language,minutes",
    [
        ("ru", 20),
        ("en", 20),
        ("ru", 60),
        ("en", 60),
    ],
)
def test_long_episode_has_plan_bounded_sections_and_reusable_checkpoints(
    workspace, monkeypatch, language, minutes
):
    citation = workspace.units()[0]["id"]
    calls = []
    parts = minutes // 5

    def generate(prompt, schema, *a, **kw):
        calls.append((prompt, schema["title"]))
        if schema["title"] == "Outline":
            return {
                "title": "Learning",
                "sections": [
                    {
                        "title": f"Section {i}",
                        "brief": f"Distinct purpose {i}",
                        "citations": [citation],
                    }
                    for i in range(parts)
                ],
            }
        assert "DIALOGUE VOICES" in prompt
        assert "EPISODE OUTLINE" in prompt
        assert f"Write section {len(calls) - 1} of {parts}" in prompt
        return dialogue(citation, int(re.search(r"Write (\d+) spoken words", prompt)[1]), language)

    monkeypatch.setattr("brofessor.infrastructure.text.runners.generate", generate)
    job = service.submit(
        workspace, JobKind.PODCAST, language=language, minutes=minutes, start_worker=False
    )
    pipeline.execute(workspace, job)
    draft = workspace.draft(job["id"])
    actual_words = podcasts.word_count(draft["data"]["turns"])
    assert abs(actual_words - job["params"]["target_words"]) <= parts / 2
    observed_pace = 117.92 if language == "ru" else 151.56
    estimated_minutes = actual_words / observed_pace
    assert max(20, minutes * 0.9) <= estimated_minutes <= min(60, minutes * 1.1)
    assert max(len(t["text"]) for t in draft["data"]["turns"]) <= (300 if language == "ru" else 400)
    artifacts = workspace.artifacts(job["id"])
    outline = next(a for a in artifacts if a["metadata"].get("role") == "episode_outline")
    assert len(json.loads((workspace.path / outline["path"]).read_text())["sections"]) == parts
    monkeypatch.setattr(
        "brofessor.infrastructure.text.runners.generate",
        lambda *a, **kw: pytest.fail("Must use checkpoint"),
    )
    pipeline.execute(workspace, job)
    assert len(calls) == parts + 1


def test_failed_editorial_correction_is_retried_without_repeating_good_sections(
    workspace, monkeypatch
):
    citation = workspace.units()[0]["id"]
    failed = False
    calls = []

    def generate(prompt, schema, *a, **kw):
        nonlocal failed
        calls.append(prompt)
        if schema["title"] == "Outline":
            return {
                "title": "Facts",
                "sections": [
                    {"title": f"Part {i}", "brief": "Evidence", "citations": [citation]}
                    for i in range(4)
                ],
            }
        section = int(re.search(r"Write section (\d)", prompt)[1])
        if section == 2 and "First version" not in prompt:
            return dialogue(citation, 80, "ru")
        if section == 2 and not failed:
            failed = True
            return dialogue(citation, 100, "ru")
        target = int(re.search(r"Write (\d+) spoken words", prompt)[1])
        return dialogue(citation, target, "ru")

    monkeypatch.setattr("brofessor.infrastructure.text.runners.generate", generate)
    job = service.submit(workspace, JobKind.PODCAST, minutes=20, start_worker=False)
    worker.run(workspace, once=True)
    assert workspace.job(job["id"])["status"] == "failed"
    assert "section 2 has 100 words" in workspace.job(job["id"])["error"]
    assert workspace.draft(job["id"]) is None
    workspace.resume(job["id"])
    worker.run(workspace, once=True)
    assert workspace.job(job["id"])["status"] == "succeeded"
    assert sum("Write section 1" in p for p in calls) == 1
    assert sum("First version" in p for p in calls) == 2


@pytest.mark.parametrize("titles", [["Same"] * 4, ["One", "Two"]])
def test_invalid_outline_is_not_accepted(workspace, monkeypatch, titles):
    citation = workspace.units()[0]["id"]
    monkeypatch.setattr(
        "brofessor.infrastructure.text.runners.generate",
        lambda *a, **kw: {
            "title": "Facts",
            "sections": [
                {"title": title, "brief": "Evidence", "citations": [citation]} for title in titles
            ],
        },
    )
    job = service.submit(workspace, JobKind.PODCAST, minutes=20, start_worker=False)
    with pytest.raises(ValueError, match="outline"):
        pipeline.execute(workspace, job)
    assert not list((workspace.path / "jobs" / job["id"]).glob("checkpoints/*.json"))


def test_split_turns_preserves_words_roles_and_citations():
    original = [
        {
            "speaker": "host",
            "text": ("Some precise fact. " * 30).strip(),
            "citations": ["original:4"],
        }
    ]
    split = podcasts.split_turns(original, 100)
    assert " ".join(t["text"] for t in split).split() == original[0]["text"].split()
    assert all(
        len(t["text"]) <= 100 and t["speaker"] == "host" and t["citations"] == ["original:4"]
        for t in split
    )


def test_speech_split_prefers_complete_sentences_even_after_a_short_opening():
    turns = [
        {"speaker": "guest", "text": "They learn. " + "More context " * 10, "citations": ["u:1"]}
    ]
    split = podcasts.split_turns(turns, 100)
    assert split[0]["text"] == "They learn."
    assert " ".join(t["text"] for t in split).split() == turns[0]["text"].split()


@pytest.mark.parametrize(
    "minutes,seconds,matches",
    [
        (25, 1500, True),
        (25, 1300, False),
        (20, 1150, False),
        (60, 3700, False),
        (60, 3450, True),
        (3, 180, True),
    ],
)
def test_duration_feedback_uses_actual_audio_and_episode_range(minutes, seconds, matches):
    result = podcasts.duration_feedback(dialogue("source:1", 100, "en"), minutes, seconds)
    assert result["duration_matches"] is matches
    assert result["script_words"] == 100
    assert result["suggested_word_count"] == round(100 * minutes * 60 / seconds)


def test_audio_sidecar_and_registered_metadata_agree(preset_voices, workspace, monkeypatch):
    citation = workspace.units()[0]["id"]
    job = service.submit(workspace, JobKind.PODCAST, minutes=25, start_worker=False)
    workspace.save_draft(job["id"], dialogue(citation, 80, "en"))
    render = service.render(workspace, job["id"], model="qwen3-base", start_worker=False)

    def fake_render(plan, output, **kwargs):
        # Metadata boundary only; these bytes do not represent real speech.
        output.write_bytes(b"fake audio")
        return {"path": str(output), "duration_seconds": 1500}

    monkeypatch.setattr("brofessor.infrastructure.formats.audio.render_audio", fake_render)
    pipeline.execute(workspace, render)
    artifact = workspace.artifacts(render["id"])[0]
    saved = json.loads((workspace.path / "jobs" / render["id"] / "podcast.audio.json").read_text())
    assert saved == artifact["metadata"]
    assert saved["duration_matches"] is True
    assert saved["script_words"] == 80


def test_episode_budget_compensates_underruns_and_preserves_prior_checkpoints(
    workspace, monkeypatch
):
    citation = workspace.units()[0]["id"]
    job = service.submit(
        workspace, JobKind.PODCAST, minutes=20, request_key="budget", start_worker=False
    )
    calls = []

    def generate(prompt, schema, *args, **kwargs):
        calls.append(prompt)
        if schema["title"] == "Outline":
            return {
                "title": "Evidence",
                "sections": [
                    {
                        "title": f"Scope {n}",
                        "brief": "Source-backed detail",
                        "citations": [citation],
                    }
                    for n in range(4)
                ],
            }
        target = int(re.search(r"Write (\d+) spoken words", prompt)[1])
        return dialogue(
            citation, target if "First version:" in prompt else round(target * 0.9), "ru"
        )

    monkeypatch.setattr("brofessor.infrastructure.text.runners.generate", generate)
    pipeline.execute(workspace, job)
    value = workspace.draft(job["id"])["data"]
    written = podcasts.word_count(value["turns"])
    assert abs(written - job["params"]["target_words"]) <= job["params"]["target_words"] * 0.02
    assert sum("First version:" in prompt for prompt in calls) == 1
    frozen = service.submit(
        workspace, JobKind.PODCAST, minutes=20, request_key="budget", start_worker=False
    )
    assert frozen["id"] == job["id"] and frozen["params"] == job["params"]
    monkeypatch.setattr(
        "brofessor.infrastructure.text.runners.generate",
        lambda *a, **kw: pytest.fail("Accepted sections must be reused"),
    )
    pipeline.execute(workspace, frozen)
    assert workspace.draft(job["id"])["data"] == value
