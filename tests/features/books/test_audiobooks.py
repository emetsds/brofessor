"""Narration preserves source order, frozen translations and reusable local speech."""

import copy
import json
import re
import subprocess
import wave

import pytest
from streamlit.testing.v1 import AppTest
from typer.testing import CliRunner

from brofessor.application import pipeline, service, tasks, worker
from brofessor.contracts.content import ContentLanguage
from brofessor.features.books import audiobooks
from brofessor.infrastructure.formats import audio as media
from brofessor.infrastructure.storage.workspace import Workspace
from brofessor.interfaces.cli.app import app
from tests.helpers.books import translated_book
from tests.helpers.ui import UI_APP, create, new_key


pytestmark = pytest.mark.usefixtures("preset_voices")


def original(tmp_path):
    path = tmp_path / "book.md"
    path.write_text(
        "# First chapter\nKeep every original sentence.\n\n"
        "# Second; #chapter=2\\test\nRead the final sentence too.\n"
    )
    workspace = Workspace(tmp_path / "workspace")
    source = workspace.add_source(path)
    return workspace, source


def prepare(workspace, source):
    job = audiobooks.submit(
        workspace,
        source["id"],
        language=ContentLanguage.EN,
        speech_model="qwen3-base",
        start_worker=False,
    )
    worker.run(workspace, once=True)
    assert workspace.job(job["id"])["status"] == "succeeded"
    return job


@pytest.fixture
def speech(monkeypatch):
    if not media._ffmpeg():
        pytest.skip("FFmpeg is required for the M4B file contract")
    calls = []
    monkeypatch.setattr(media, "_load_speech_model", lambda _: object())

    def synth(model, text, voice, language, output, cancelled):
        calls.append(text)
        with wave.open(str(output), "wb") as stream:
            stream.setparams((1, 2, 24000, 0, "NONE", "none"))
            stream.writeframes(b"\x01\x00" * 24000)

    monkeypatch.setattr(media, "_synthesize", synth)
    return calls


def test_original_narration_preserves_all_words_in_order_without_text_inference(
    tmp_path, monkeypatch
):
    workspace, source = original(tmp_path)
    monkeypatch.setattr(
        "brofessor.infrastructure.text.runners.generate",
        lambda *a, **kw: pytest.fail("Narration needs no text model"),
    )
    job = prepare(workspace, source)
    value = workspace.draft(job["id"])["data"]
    # Compare against extracted originals, not another copy of the narration implementation.
    expected = " ".join(
        re.sub(r"(?m)^# ", "", "\n".join(u["text"] for u in workspace.units())).split()
    )
    assert (
        " ".join(p["text"] for c in value["chapters"] for p in c["passages"]).split()
        == expected.split()
    )
    assert [c["title"] for c in value["chapters"]] == ["First chapter", "Second; #chapter=2\\test"]
    assert all(
        u["cited"] and u["status"] == "read"
        for u in service.coverage(workspace, job["id"])["units"]
    )
    assert set(tasks.models(workspace, job["id"])["data"]) == {"speech_model", "origin"}


def test_m4b_has_real_chapters_and_editing_one_passage_reuses_other_audio(
    preset_voices, tmp_path, speech
):
    workspace, source = original(tmp_path)
    job = prepare(workspace, source)
    render = service.render(workspace, job["id"], start_worker=False)
    worker.run(workspace, once=True)
    assert workspace.job(render["id"])["status"] == "succeeded", workspace.job(render["id"])[
        "error"
    ]
    first = service.rendered_file(workspace, workspace.job(render["id"]))
    content = first.read_bytes()
    metadata = subprocess.check_output(
        [media._ffmpeg(), "-v", "error", "-i", str(first), "-f", "ffmetadata", "-"], text=True
    )
    saved = workspace.draft(job["id"])
    assert "title=First chapter" in metadata
    assert r"title=Second\; \#chapter\=2\\test" in metadata
    artifact = next(a for a in workspace.artifacts(render["id"]) if a["kind"] == "audiobook")
    assert [int(v) / 1000 for v in re.findall(r"^START=(\d+)$", metadata, re.M)] == pytest.approx(
        [c["start_seconds"] for c in artifact["metadata"]["chapters"]], abs=0.005
    )
    calls = len(speech)
    changed = copy.deepcopy(saved["data"])
    changed["chapters"][0]["passages"][0]["text"] = "A corrected opening sentence."
    service.edit_draft(workspace, job["id"], changed, saved["revision"])
    second = service.render(workspace, job["id"], start_worker=False)
    worker.run(workspace, once=True)
    assert workspace.job(second["id"])["status"] == "succeeded"
    assert len(speech) == calls + 1
    assert first.read_bytes() == content
    assert workspace.draft(job["id"])["data"]["user_edited"]
    assert service.uses_current_voice(workspace.job(second["id"]), "en", model="qwen3-base")


def test_translation_narration_pins_the_saved_text_and_hides_its_derived_source(
    tmp_path, monkeypatch
):
    workspace, source, translation, model = translated_book(tmp_path, monkeypatch)
    calls = len(model.calls)
    job = audiobooks.submit(
        workspace,
        source["id"],
        language=ContentLanguage.RU,
        translation={"job_id": translation["id"], "revision": 1},
        start_worker=False,
    )
    saved = workspace.draft(translation["id"])
    changed = copy.deepcopy(saved["data"])
    changed["blocks"][0]["text"] = "A later manual edit."
    service.edit_draft(workspace, translation["id"], changed, 1)
    pipeline.execute(workspace, job)
    text = " ".join(t["text"] for t in audiobooks.turns(workspace.draft(job["id"])["data"]))
    assert "журнал" in text and "бревно" in text and "later manual" not in text
    assert len(model.calls) == calls
    derived = next(s for s in workspace.sources() if s["id"] == job["params"]["source_ids"][0])
    assert derived["hidden"] and derived["id"] != source["id"]


def test_epub_narration_keeps_spine_order_table_and_footnote_and_reports_empty_chapter(tmp_path):
    from tests.helpers.sources import make_epub

    path = make_epub(
        tmp_path / "ordered.epub",
        entries={
            "OPS/z.xhtml": "<html><body><h1>First chapter</h1><p>Observation 1.</p>"
            "<table><tr><th>Quantity</th><th>Value</th></tr><tr><td>Mass</td><td>2 kg</td>"
            "</tr></table><aside><p>1. The scale was calibrated.</p></aside></body></html>"
        },
    )
    workspace = Workspace(tmp_path / "workspace")
    source = workspace.add_source(path)
    job = prepare(workspace, source)
    value = workspace.draft(job["id"])["data"]
    text = " ".join(p["text"] for p in audiobooks.turns(value))
    assert (
        text.index("Quantity Value")
        < text.index("Mass 2 kg")
        < text.index("scale was calibrated")
        < text.index("Second chapter")
    )
    assert (
        text.split()
        == " ".join(u["text"] for u in workspace.units() if u["status"] == "ready").split()
    )
    assert any(
        u["status"] == "excluded" and u["reason"] == "empty"
        for u in service.coverage(workspace, job["id"])["units"]
    )


def test_markdown_extraction_boundaries_do_not_create_extra_chapters(tmp_path):
    source = tmp_path / "long.md"
    source.write_text(
        "# First chapter\n"
        + "".join(f"Original line {i}.\n" for i in range(230))
        + "# Final chapter\nThe end.\n"
    )
    workspace = Workspace(tmp_path / "workspace")
    imported = workspace.add_source(source)
    job = prepare(workspace, imported)
    value = workspace.draft(job["id"])["data"]
    assert [c["title"] for c in value["chapters"]] == ["First chapter", "Final chapter"]
    narrated = " ".join(p["text"] for p in audiobooks.turns(value))
    assert narrated.split() == re.sub(r"(?m)^# ", "", source.read_text()).split()


def test_cancel_after_a_saved_segment_resumes_without_synthesizing_it_again(
    tmp_path, monkeypatch, speech
):
    workspace, source = original(tmp_path)
    job = prepare(workspace, source)
    render = service.render(workspace, job["id"], start_worker=False)
    update = workspace.update_job

    def cancel(job_id, **changes):
        result = update(job_id, **changes)
        progress = changes.get("progress", {})
        if progress.get("stage") == "speech" and progress.get("completed") == 1:
            workspace.cancel(job_id)
        return result

    monkeypatch.setattr(workspace, "update_job", cancel)
    worker.run(workspace, once=True)
    assert workspace.job(render["id"])["status"] == "cancelled"
    assert workspace.artifacts(render["id"]) == []
    monkeypatch.setattr(workspace, "update_job", update)
    workspace.resume(render["id"])
    worker.run(workspace, once=True)
    assert workspace.job(render["id"])["status"] == "succeeded"
    assert len(speech) == len(set(speech))


def test_ui_prepares_local_narration_and_cli_reads_the_same_draft(tmp_path, monkeypatch):
    workspace, _ = original(tmp_path)
    monkeypatch.setattr("brofessor.application.worker.ensure_worker", lambda _: None)
    monkeypatch.setattr("sys.argv", ["ui.py", "--workspace", str(workspace.path)])
    ui = AppTest.from_file(UI_APP, default_timeout=30).run()
    create(ui)
    ui.selectbox(key=new_key(ui, "kind")).select("audiobook").run()
    assert not ui.exception
    assert not any(w.key and w.key.endswith(":new:provider") for w in ui.selectbox)
    ui.selectbox(key=new_key(ui, "output_language")).select("en").run()
    ui.button(key="prepare").click().run()
    assert not ui.exception
    job = workspace.jobs()[0]
    worker.run(workspace, once=True)
    ui.run()
    assert not ui.exception
    shown = CliRunner().invoke(app, ["-w", str(workspace.path), "draft", "show", job["id"]])
    assert shown.exit_code == 0, shown.output
    assert json.loads(shown.output)["data"] == workspace.draft(job["id"])["data"]
