"""First narration follows a saved policy across failures and client lifetimes."""

import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from typer.testing import CliRunner

from brofessor.application import initial_audio, pipeline, service, worker
from brofessor.contracts.content import ContentLanguage
from brofessor.contracts.jobs import JobKind, JobStatus
from brofessor.infrastructure.speech import catalogue as speech_models
from brofessor.infrastructure.storage.workspace import Workspace
from brofessor.interfaces.cli.app import app


@pytest.fixture
def setup(tmp_path, monkeypatch):
    w = Workspace(tmp_path / "workspace")
    source = tmp_path / "source.txt"
    source.write_text("A bridge supports eighty kilograms.")
    w.add_source(source)
    # A small pinned, reference-free catalog profile isolates the expensive speech boundary.
    spec = speech_models.get("qwen3-base")
    spec.pop("preset_references")
    spec.pop("voice_pack")
    spec["dependencies"] = []
    monkeypatch.setattr(speech_models, "CATALOG", [spec])
    monkeypatch.setattr(speech_models, "installed_path", lambda *_: tmp_path)
    monkeypatch.setattr(speech_models, "qwen_runtime_available", lambda: True)
    monkeypatch.setattr(worker, "ensure_worker", lambda *_: None)
    unit = w.units()[0]["id"]
    value = {
        "title": "Bridge",
        "language": "en",
        "turns": [
            {"speaker": "host", "text": "What supports the load?", "citations": [unit]},
            {
                "speaker": "guest",
                "text": "The bridge supports eighty kilograms.",
                "citations": [unit],
            },
        ],
    }
    calls = []

    def generate(*args, **kwargs):
        calls.append(args)
        return value

    monkeypatch.setattr("brofessor.infrastructure.text.runners.generate", generate)
    return w, value, calls


def podcast(w):
    return service.submit(
        w,
        JobKind.PODCAST,
        minutes=3,
        language=ContentLanguage.EN,
        title="Load test",
        start_worker=False,
    )


def test_worker_handoff_pins_first_revision_and_model_without_a_browser(setup, monkeypatch):
    w, value, calls = setup
    job = podcast(w)
    worker.run(w, once=True)
    current = initial_audio.state(w, job["id"])
    assert w.job(job["id"])["status"] == "succeeded"
    assert current["revision"] == 1 and current["render"]["status"] == "queued"
    assert (
        current["render"]["params"]["model_spec"]["revision"]
        == job["params"]["auto_audio"]["revision"]
    )
    service.edit_draft(w, job["id"], {**value, "title": "Later edit"}, 1)
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(
            pool.map(
                lambda _: initial_audio.continue_audio(w, job["id"], start_worker=False), range(3)
            )
        )
    assert len([j for j in w.jobs() if j["kind"] == "render_podcast"]) == 1
    assert initial_audio.state(Workspace(w.path), job["id"])["revision"] == 1
    assert len(calls) == 1


@pytest.mark.parametrize("missing", ["weights", "runtime"])
def test_missing_model_cancel_and_resume_never_repeat_text(setup, monkeypatch, missing):
    w, value, calls = setup
    if missing == "weights":
        monkeypatch.setattr(speech_models, "installed_path", lambda *_: None)
    else:
        monkeypatch.setattr(speech_models, "qwen_runtime_available", lambda: False)
    job = podcast(w)
    worker.run(w, once=True)
    assert initial_audio.state(w, job["id"])["state"] == "blocked"
    assert w.draft(job["id"])["data"] == value
    initial_audio.cancel(w, job["id"])
    monkeypatch.setattr(speech_models, "installed_path", lambda *_: w.path)
    monkeypatch.setattr(speech_models, "qwen_runtime_available", lambda: True)
    initial_audio.reconcile(Workspace(w.path))
    assert not [j for j in w.jobs() if j["kind"] == "render_podcast"]
    initial_audio.resume(w, job["id"], start_worker=False)
    child = initial_audio.state(w, job["id"])["render"]
    w.cancel(child["id"])
    initial_audio.reconcile(w)
    assert initial_audio.state(w, job["id"])["state"] == "cancelled"
    initial_audio.resume(w, job["id"], start_worker=False)
    assert w.job(child["id"])["status"] == "queued"
    assert len(calls) == 1
    assert w.draft(job["id"])["revision"] == 1


@pytest.mark.parametrize("fault", ["before_enqueue", "after_enqueue"])
def test_recovery_at_handoff_preserves_saved_text_and_single_audio(setup, monkeypatch, fault):
    w, value, calls = setup
    job = podcast(w)
    claimed = w.claim()
    pipeline.execute(w, claimed)
    # Simulate a stop after accepting the script, on either side of the enqueue.
    if fault == "after_enqueue":
        w.update_job(job["id"], status=JobStatus.SUCCEEDED)
        original = service.render

        def die_after_enqueue(*args, **kwargs):
            original(*args, **kwargs)
            raise KeyboardInterrupt

        monkeypatch.setattr(service, "render", die_after_enqueue)
        with pytest.raises(KeyboardInterrupt):
            initial_audio.continue_audio(w, job["id"], start_worker=False)
        monkeypatch.setattr(service, "render", original)
    else:
        w.recover()
        w.resume(job["id"])
        worker.run(w, once=True)
    initial_audio.reconcile(Workspace(w.path))
    pending = initial_audio.state(w, job["id"])
    assert pending["render"]["params"]["revision"] == 1
    assert len([j for j in w.jobs() if j["kind"] == "render_podcast"]) == 1
    assert len(calls) == 1
    assert w.draft(job["id"])["data"] == value


def test_old_podcast_has_no_automatic_side_effect_and_cli_can_control_policy(setup):
    w, _, _ = setup
    with pytest.raises(ValueError, match="true or false"):
        service.submit(w, JobKind.PODCAST, auto_audio="false", start_worker=False)
    assert not w.jobs()
    job = service.submit(
        w,
        JobKind.PODCAST,
        minutes=3,
        language=ContentLanguage.EN,
        auto_audio=False,
        start_worker=False,
    )
    worker.run(w, once=True)
    initial_audio.reconcile(w)
    assert initial_audio.state(w, job["id"]) is None
    assert not [j for j in w.jobs() if j["kind"] == "render_podcast"]
    current = podcast(w)
    result = CliRunner().invoke(
        app, ["-w", str(w.path), "task", "audio", current["id"], "--cancel"]
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["state"] == "cancelled"


def test_manual_and_automatic_events_share_one_frozen_render(setup):
    w, value, calls = setup
    job = podcast(w)
    w.save_draft(job["id"], value)
    w.update_job(job["id"], status=JobStatus.SUCCEEDED)
    with ThreadPoolExecutor(max_workers=4) as pool:
        events = [
            pool.submit(initial_audio.continue_audio, w, job["id"], start_worker=False)
            for _ in range(2)
        ]
        events += [pool.submit(service.render, w, job["id"], start_worker=False) for _ in range(2)]
        for event in events:
            event.result()
    children = [j for j in w.jobs() if j["kind"] == "render_podcast"]
    assert len(children) == 1
    assert initial_audio.state(w, job["id"])["render_id"] == children[0]["id"]
    assert not calls


def test_cli_wait_reports_unavailable_audio_without_repeating_the_script(setup, monkeypatch):
    w, _, calls = setup
    monkeypatch.setattr(speech_models, "installed_path", lambda *_: None)
    job = podcast(w)
    worker.run(w, once=True)
    result = CliRunner().invoke(
        app,
        [
            "-w",
            str(w.path),
            "podcast",
            "--minutes",
            "3",
            "--language",
            "en",
            "--title",
            "Load test",
            "--request-key",
            job["request_key"],
            "--wait",
        ],
    )
    assert result.exit_code == 1, result.output
    returned = json.loads(result.output)
    assert returned["status"] == "succeeded"  # the saved script remains ready
    assert returned["initial_audio"]["state"] == "blocked"
    assert len(calls) == 1 and w.draft(job["id"])["revision"] == 1


def test_cli_wait_returns_playable_artifact_for_the_pinned_first_revision(setup, monkeypatch):
    import wave

    import numpy as np

    from brofessor.infrastructure.formats import audio as media
    from brofessor.infrastructure.speech import engines as speech

    w, _, calls = setup

    class Model:
        def synthesize(self, text, voice, language, cancelled):
            return np.full(2400, 0.1), 24000

    monkeypatch.setattr(speech, "load", lambda *_: Model())
    monkeypatch.setattr(speech, "runtime", lambda *_: {"fixture": "waveform"})
    monkeypatch.setattr(media, "_ffmpeg", lambda: None)

    def process(store):
        worker.run(store, once=True)
        worker.run(store, once=True)

    monkeypatch.setattr(worker, "ensure_worker", process)
    result = CliRunner().invoke(
        app,
        [
            "-w",
            str(w.path),
            "podcast",
            "--minutes",
            "3",
            "--language",
            "en",
            "--title",
            "Load test",
            "--wait",
        ],
    )
    assert result.exit_code == 0, result.output
    audio = json.loads(result.output)["initial_audio"]
    artifact = next(a for a in audio["artifacts"] if a["kind"] == "audio")
    assert audio["render"]["params"]["revision"] == 1
    with wave.open(str(w.path / artifact["path"]), "rb") as stream:
        assert stream.getnframes() > 0 and stream.getframerate() == 24000
    assert len(calls) == 1
