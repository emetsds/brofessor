"""Preset voice installation, portable job inputs and Qwen ICL adapter contracts."""

import hashlib
import io
import json
import shlex
import shutil
import sys
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from brofessor.application import service, worker
from brofessor.contracts.jobs import JobKind, JobStatus
from brofessor.infrastructure.formats import audio as media
from brofessor.infrastructure.speech import catalogue as speech_models
from brofessor.infrastructure.speech import engines as speech
from brofessor.infrastructure.speech import references as speech_references
from brofessor.infrastructure.storage.workspace import Workspace
from brofessor.interfaces.cli.app import app
from tests.helpers.ui import UI_APP


def wav(value):
    stream = io.BytesIO()
    with wave.open(stream, "wb") as audio:
        audio.setparams((1, 2, 24000, 0, "NONE", "none"))
        audio.writeframes(value.to_bytes(2, "little", signed=True) * 72000)
    return stream.getvalue()


@pytest.fixture
def presets(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setattr(speech_models, "_legacy_caches", lambda: [])
    spec = speech_models.get("qwen3-base")
    spec["files"], spec["download_bytes"] = {"config.json": 2}, 2
    pack = spec["dependencies"][0]
    contents = {}
    for language, refs in spec["preset_references"].items():
        for role, ref in refs.items():
            content = wav(len(contents) + 1)
            contents[ref["file"]] = content
            ref["sha256"] = hashlib.sha256(content).hexdigest()
            ref["text"] = f"{language} {role} reference."
    pack["files"] = {name: len(content) for name, content in contents.items()}
    pack["download_bytes"] = sum(pack["files"].values())
    catalog = [spec if m["id"] == spec["id"] else m for m in speech_models.CATALOG]
    monkeypatch.setattr(speech_models, "CATALOG", catalog)

    def download(**options):
        item = pack if options["repo_id"] == pack["repo"] else spec
        target = speech_models.snapshot(item)
        target.mkdir(parents=True, exist_ok=True)
        for name in options["allow_patterns"]:
            (target / name).write_bytes(contents[name] if item is pack else b"{}")

    monkeypatch.setattr(speech_models, "_snapshot_download", download)
    monkeypatch.setattr("brofessor.application.worker.ensure_worker", lambda *_: None)
    return spec


def draft(tmp_path, language="ru"):
    workspace = Workspace(tmp_path / "project")
    source = tmp_path / "source.txt"
    source.write_text("Synthetic evidence.")
    workspace.add_source(source)
    unit = workspace.units()[0]["id"]
    original = service.submit(
        workspace, JobKind.PODCAST, language=language, auto_audio=False, start_worker=False
    )
    workspace.save_draft(
        original["id"],
        {
            "title": "Test",
            "language": language,
            "turns": [
                {"speaker": "host", "text": "Вопрос?", "citations": [unit]},
                {"speaker": "guest", "text": "Ответ.", "citations": [unit]},
            ],
        },
    )
    workspace.update_job(original["id"], status=JobStatus.SUCCEEDED)
    return workspace, original


@pytest.mark.parametrize("preview", [False, True])
def test_cli_first_use_commands_download_and_continue_pinned_revision(presets, tmp_path, preview):
    workspace, original = draft(tmp_path / "folder with spaces")
    runner = CliRunner()
    cli = ["-w", str(workspace.path)]
    action = ["preview-turn", original["id"], "1"] if preview else ["render", original["id"]]
    missing = runner.invoke(app, [*cli, "draft", *action])
    assert missing.exit_code != 0 and "GB" in missing.output
    commands = [
        shlex.split(line)[1:]
        for line in missing.output.splitlines()
        if line.startswith("brofessor ")
    ]
    download, resume = commands
    assert download == [*cli, "tts", "download", "--wait"]
    assert resume == [*cli, "draft", *action, "--revision", "1", "--wait"]
    newer = workspace.draft(original["id"])["data"]
    newer["title"] = "Later edits"
    service.edit_draft(workspace, original["id"], newer, 1)
    shown = runner.invoke(app, [*cli, "draft", "show", original["id"], "--revision", "1"])
    assert json.loads(shown.output)["data"]["title"] == "Test"
    assert runner.invoke(app, download[:-1]).exit_code == 0
    worker.run(workspace, once=True)
    queued = runner.invoke(app, resume[:-1])
    assert queued.exit_code == 0, queued.output
    assert workspace.jobs()[0]["params"]["revision"] == 1
    assert workspace.jobs()[0]["kind"] == ("preview_turn" if preview else "render_podcast")


@pytest.mark.parametrize("language", ["ru", "en"])
def test_default_download_and_cli_render_freeze_native_preset_voices(presets, tmp_path, language):
    workspace, original = draft(tmp_path, language)
    assert speech_models.selected() == "qwen3-base"
    download = service.download_model(workspace, "qwen3-base", start_worker=False)
    worker.run(workspace, once=True)
    assert workspace.job(download["id"])["status"] == "succeeded"
    assert speech_models.installed_path("qwen3-base") is not None
    result = CliRunner().invoke(app, ["-w", str(workspace.path), "draft", "render", original["id"]])
    assert result.exit_code == 0, result.output
    submitted = next(job for job in workspace.jobs() if job["kind"] == "render_podcast")
    frozen = submitted["params"]["model_spec"]
    assert frozen["engine"] == "qwen3-base-mlx"
    assert "preset_references" not in frozen
    assert frozen["dependencies"] == []
    for role, ref in frozen["references"].items():
        assert ref["text"] == f"{language} {role} reference."
        assert (
            hashlib.sha256((workspace.path / ref["path"]).read_bytes()).hexdigest() == ref["sha256"]
        )
    assert speech_references.list_references(language) == {}


def test_frozen_preset_render_survives_missing_pack_and_project_move(
    presets, tmp_path, monkeypatch
):
    workspace, original = draft(tmp_path)
    speech_models.download(presets)
    render = service.render(workspace, original["id"], start_worker=False)
    shutil.rmtree(speech_models.snapshot(presets["dependencies"][0]))
    moved = tmp_path / "moved"
    shutil.copytree(workspace.path, moved)
    relocated = Workspace(moved)
    seen = []

    class Model:
        def synthesize(self, text, voice, language, cancelled):
            import numpy as np

            return np.full(2400, 0.1), 24000

    def load(spec, location):
        for ref in spec["references"].values():
            assert Path(ref["path"]).is_relative_to(moved)
            assert hashlib.sha256(Path(ref["path"]).read_bytes()).hexdigest() == ref["sha256"]
        seen.append(spec["id"])
        return Model()

    monkeypatch.setattr(speech, "load", load)
    monkeypatch.setattr(media, "_ffmpeg", lambda: None)
    worker.run(relocated, once=True)
    assert relocated.job(render["id"])["status"] == "succeeded"
    assert seen == ["qwen3-base"]


def test_changing_one_preset_invalidates_only_its_speech_segments(presets, tmp_path, monkeypatch):
    workspace, original = draft(tmp_path)
    speech_models.download(presets)
    calls = []

    class Model:
        def synthesize(self, text, voice, language, cancelled):
            import numpy as np

            calls.append(voice)
            return np.full(2400, 0.1), 24000

    monkeypatch.setattr(speech, "load", lambda *_: Model())
    monkeypatch.setattr(media, "_ffmpeg", lambda: None)
    first = service.render(workspace, original["id"], start_worker=False)
    worker.run(workspace, once=True)
    host = presets["preset_references"]["ru"]["host"]
    content = wav(100)
    pack = speech_models.snapshot(presets["dependencies"][0])
    (pack / host["file"]).write_bytes(content)
    host["sha256"] = hashlib.sha256(content).hexdigest()
    second = service.render(workspace, original["id"], start_worker=False)
    assert first["id"] != second["id"]
    worker.run(workspace, once=True)
    metadata = workspace.artifacts(second["id"])[0]["metadata"]
    assert [s["reused"] for s in metadata["segments"]] == [False, True]
    assert calls == ["host", "guest", "host"]


def test_current_voice_compares_frozen_inputs_even_without_installed_pack(
    presets, tmp_path, monkeypatch
):
    workspace, original = draft(tmp_path)
    speech_models.download(presets)
    jobs = [
        service.render(workspace, original["id"], turn=turn, start_worker=False)
        for turn in (None, 2)
    ]
    monkeypatch.setattr(
        speech_models,
        "installed_path",
        lambda *_: pytest.fail("Catalog comparison consulted the installation"),
    )
    presets["notes"] = "Updated text in the catalog"
    assert all(service.uses_current_voice(job, "ru") for job in jobs)
    assert not any(service.uses_current_voice(job, "en") for job in jobs)
    # Same weights, WAV and recorded voice. A corrected transcript still changes inference.
    ref = presets["preset_references"]["ru"]["guest"]
    old_text = ref["text"]
    ref["text"] = "Corrected transcript"
    assert not any(service.uses_current_voice(job, "ru") for job in jobs)
    ref["text"] = old_text
    presets["settings"]["temperature"] = 0.12
    assert not any(service.uses_current_voice(job, "ru") for job in jobs)


def test_damaged_bundled_sample_does_not_enqueue_audio(presets, tmp_path):
    workspace, original = draft(tmp_path)
    speech_models.download(presets)
    ref = presets["preset_references"]["ru"]["host"]
    target = speech_models.snapshot(presets["dependencies"][0]) / ref["file"]
    target.write_bytes(wav(999))
    with pytest.raises(ValueError, match="Voice sample changed"):
        service.render(workspace, original["id"], start_worker=False)
    assert not any(j["kind"] == "render_podcast" for j in workspace.jobs())


@pytest.mark.parametrize("failure", [None, "limit", "empty_second_part"])
def test_base_adapter_uses_exact_local_reference_and_preserves_long_text(
    presets, tmp_path, monkeypatch, failure
):
    np = pytest.importorskip("numpy")
    speech_models.download(presets)
    spec = speech_references.preset_snapshot(presets, "ru")
    ref = spec["references"]["guest"]
    calls = []
    model = SimpleNamespace(
        sample_rate=24000,
        config=SimpleNamespace(tts_model_type="base"),
        speech_tokenizer=SimpleNamespace(has_encoder=True),
    )

    def generate(**options):
        calls.append(options)
        if failure == "empty_second_part" and len(calls) == 2:
            return
        yield SimpleNamespace(audio=np.ones(2400), token_count=600 if failure == "limit" else 4)

    model.generate = generate
    mx = SimpleNamespace(
        set_memory_limit=lambda _: None,
        set_wired_limit=lambda _: None,
        set_cache_limit=lambda _: None,
        clear_cache=lambda: None,
        random=SimpleNamespace(seed=lambda _: None),
    )
    monkeypatch.setitem(sys.modules, "mlx", SimpleNamespace(core=mx))
    monkeypatch.setitem(sys.modules, "mlx.core", mx)
    monkeypatch.setitem(
        sys.modules, "mlx_audio.tts.utils", SimpleNamespace(load_model=lambda _: model)
    )
    engine = speech.load(spec, tmp_path)
    text = " ".join(["Сначала читаем предложение.", "Потом проверяем следующее."] * 18)
    if failure:
        message = "generation limit" if failure == "limit" else "returned no audio"
        with pytest.raises(speech.SpeechError, match=message):
            engine.synthesize(text, "guest", "ru", lambda: False)
    else:
        audio, rate = engine.synthesize(text, "guest", "ru", lambda: False)
        assert rate == 24000 and len(audio) == 2400 * len(calls)
        assert " ".join(c["text"] for c in calls).split() == text.split()
        for c in calls:
            assert c["lang_code"] == "russian"
            assert c["ref_audio"] == ref["path"] and c["ref_text"] == ref["text"]
            assert c["stream"] is False


def test_direct_audio_entry_point_uses_bundled_default(presets, tmp_path, monkeypatch):
    speech_models.download(presets)
    received = []

    class Model:
        def synthesize(self, text, voice, language, cancelled):
            import numpy as np

            return np.full(2400, 0.1), 24000

    def load(spec, location):
        received.append(spec)
        assert spec["engine"] == "qwen3-base-mlx"
        assert spec["references"]["host"]["text"] == "ru host reference."
        return Model()

    monkeypatch.setattr(speech, "load", load)
    monkeypatch.setattr(media, "_ffmpeg", lambda: None)
    media.render_audio(
        {"language": "ru", "turns": [{"speaker": "host", "text": "Речь."}]},
        tmp_path / "preview.wav",
        segment_dir=tmp_path / "segments",
    )
    assert received[0]["id"] == "qwen3-base"


@pytest.fixture
def qwen_ui_runtime(monkeypatch):
    models = speech_models.list_models
    monkeypatch.setattr(
        speech_models, "list_models", lambda: [{**model, "compatible": True} for model in models()]
    )
    monkeypatch.setattr(speech_models, "qwen_runtime_available", lambda: True)


def test_ui_first_use_downloads_only_in_settings_and_renders_same_saved_result(
    presets, qwen_ui_runtime, tmp_path, monkeypatch
):
    from streamlit.testing.v1 import AppTest
    from streamlit.testing.v1.util import patch_config_options

    from brofessor.application import maintenance

    workspace, script = draft(tmp_path)
    monkeypatch.setattr(sys, "argv", ["ui.py", "--workspace", str(workspace.path)])
    with patch_config_options({"browser.gatherUsageStats": False}):
        ui = AppTest.from_file(UI_APP, default_timeout=30).run()
        assert not ui.exception
        assert not any(w.key == "tts_model" for w in ui.selectbox)
        assert not any(w.key == "download_tts_model" for w in ui.button)
        assert maintenance.jobs() == []
        ui.button(key="voice-settings:" + speech_models.reference(presets)).click().run()
        assert not ui.exception and maintenance.jobs() == []
        ui.button(key=f"settings:download:{presets['id']}").click().run()
        queue = maintenance.workspace()
        download = queue.jobs()[0]
        assert download["params"]["model_spec"] == presets
        assert maintenance.download_speech(presets["id"])["id"] == download["id"]
        assert len(workspace.jobs()) == 1
        queue.update_job(
            download["id"],
            status=JobStatus.RUNNING,
            progress={"completed": 5_000_000, "total": 10_000_000},
        )
        ui.button(key="settings:cancel").click().run()
        ui.button(key="settings-open").click().run()
        ui.radio(key="settings:section").set_value("models").run()
        ui.run()
        assert any("5" in bar.proto.text and "10" in bar.proto.text for bar in ui.get("progress"))
        queue.update_job(download["id"], status=JobStatus.FAILED, error="Transfer interrupted")
        ui.run()
        assert any("Transfer interrupted" in e.value for e in ui.error)
        ui.button(key=f"maintenance:resume:{queue.path}:{download['id']}").click().run()
        worker.run(queue, once=True)
        assert queue.job(download["id"])["status"] == "succeeded"
        ui.run()
        assert any("Установлена" in item.value for item in ui.caption)
        ui.button(key="settings:cancel").click().run()
        assert not any(b.key == "download_tts_model" for b in ui.button)
        ui.button(key=f"render-{script['id']}").click().run()
        assert not ui.exception
        audio = workspace.jobs()[0]
        assert audio["kind"] == "render_podcast"
        assert audio["params"]["revision"] == 1
        assert audio["params"]["draft_job_id"] == script["id"]


def test_single_turn_preview_and_updated_episode_share_frozen_audio(presets, tmp_path, monkeypatch):
    import numpy as np

    workspace, original = draft(tmp_path)
    speech_models.download(presets)
    spoken = []

    class Model:
        def synthesize(self, text, voice, language, cancelled):
            spoken.append(text)
            return np.full(2400, 0.1), 24000

    monkeypatch.setattr(speech, "load", lambda *_: Model())
    monkeypatch.setattr(media, "_ffmpeg", lambda: None)
    job_id = original["id"]
    service.render(workspace, job_id, revision=1, start_worker=False)
    worker.run(workspace, once=True)
    data = workspace.draft(job_id)["data"]
    data["turns"][1]["text"] = "Исправленный ответ."
    service.edit_draft(workspace, job_id, data, 1)

    for bad_turn in (0, 3, True):
        with pytest.raises(ValueError, match="turn number"):
            service.render(workspace, job_id, revision=2, turn=bad_turn)
    preview = service.render(workspace, job_id, revision=2, turn=2, start_worker=False)
    assert service.render(workspace, job_id, revision=2, turn=2)["id"] == preview["id"]
    # An edit before worker execution must affect neither the preview nor the chosen episode.
    data["turns"][1]["text"] = "Третья редакция."
    service.edit_draft(workspace, job_id, data, 2)
    worker.run(workspace, once=True)
    probe = workspace.artifacts(preview["id"])[0]["metadata"]
    assert probe["turn"] == 2 and probe["revision"] == 2
    assert "duration_matches" not in probe and len(probe["segments"]) == 1
    assert spoken == ["Вопрос?", "Ответ.", "Исправленный ответ."]
    updated = service.render(workspace, job_id, revision=2, start_worker=False)
    worker.run(workspace, once=True)
    final = workspace.artifacts(updated["id"])[0]["metadata"]
    assert all(segment["reused"] for segment in final["segments"])
    assert [segment["speaker"] for segment in final["segments"]] == ["host", "guest"]
    assert final["segments"][1]["key"] == probe["segments"][0]["key"]
    assert spoken == ["Вопрос?", "Ответ.", "Исправленный ответ."]
    # If the separately copied preview file is missing, a normal retry rebuilds
    # it from the accepted segment and keeps the original job in history.
    (workspace.path / workspace.artifacts(preview["id"])[0]["path"]).unlink()
    replacement = service.render(workspace, job_id, turn=2, revision=2)
    assert replacement["id"] != preview["id"]
    worker.run(workspace, once=True)
    assert service.render(workspace, job_id, turn=2, revision=2)["id"] == replacement["id"]
    assert workspace.artifacts(replacement["id"])[0]["metadata"]["segments"][0]["reused"]
    shutil.rmtree(speech_models.snapshot(presets["dependencies"][0]))
    for action, expected in (
        (["preview-turn", job_id, "2"], replacement),
        (["render", job_id], updated),
    ):
        result = CliRunner().invoke(
            app, ["-w", str(workspace.path), "draft", *action, "--revision", "2"]
        )
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["id"] == expected["id"]
    with pytest.raises(speech_references.MissingVoicePack):
        service.render(workspace, job_id, revision=3, start_worker=False)


def test_ui_preview_stays_on_the_corrected_turn_and_out_of_episode_history(
    presets, qwen_ui_runtime, tmp_path, monkeypatch
):
    import numpy as np
    from streamlit.testing.v1 import AppTest

    workspace, original = draft(tmp_path)
    job_id = original["id"]
    speech_models.download(presets)
    spoken = []

    class Model:
        def synthesize(self, text, voice, language, cancelled):
            spoken.append(text)
            return np.full(2400, 0.1), 24000

    monkeypatch.setattr(speech, "load", lambda *_: Model())
    monkeypatch.setattr(media, "_ffmpeg", lambda: None)
    monkeypatch.setattr("sys.argv", ["ui.py", "--workspace", str(workspace.path)])
    ui = AppTest.from_file(UI_APP, default_timeout=30).run()
    ui.button(key=f"edit-{job_id}").click().run()
    next(w for w in ui.selectbox if w.label == "Реплика").select(1).run()
    next(w for w in ui.text_area if w.label == "Текст реплики").set_value("Исправление.").run()
    assert not any(b.key == f"preview-{job_id}" for b in ui.button)
    ui = AppTest.from_file(UI_APP, default_timeout=30).run()
    assert next(w for w in ui.text_area if w.label == "Текст реплики").value == "Исправление."
    ui.button(key=f"save-{job_id}").click().run()
    assert ui.button(key=f"preview-{job_id}").label == "Прослушать реплику 2"
    ui.button(key=f"preview-{job_id}").click().run()
    worker.run(workspace, once=True)
    ui.run()
    assert not ui.exception and spoken == ["Исправление."]
    assert len(ui.get("audio")) == 1
    assert not any(w.label == "Версия готового файла" for w in ui.selectbox)
    assert not any(j["kind"] == "render_podcast" for j in workspace.jobs())
