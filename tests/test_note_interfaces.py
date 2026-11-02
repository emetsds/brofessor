import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest
from streamlit.testing.v1.util import patch_config_options
from typer.testing import CliRunner

from brofessor import service, worker
from brofessor.cli import app
from brofessor.workspace import Workspace


@pytest.fixture(autouse=True)
def local_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    with patch_config_options({"browser.gatherUsageStats": False}):
        yield


def open_ui(w, monkeypatch):
    monkeypatch.setattr("sys.argv", ["ui.py", "--workspace", str(w.path)])
    return AppTest.from_file(
        str(Path(__file__).parents[1] / "src/brofessor/ui.py"), default_timeout=10
    ).run()


def make_answer(tmp_path):
    w = Workspace(tmp_path / "workspace")
    path = tmp_path / "report.md"
    path.write_text("The bridge carried 1200 kilograms.")
    source = w.add_source(path)
    job = service.submit(
        w,
        "ask",
        focus="What load?",
        source_ids=[source["id"]],
        provider="ollama",
        model="local-test",
        ollama_port=11435,
        language="en",
        start_worker=False,
    )
    w.save_draft(
        job["id"],
        {
            "answer": "1200 kilograms.",
            "citations": [w.units()[0]["id"]],
            "quotes": [
                {"citation": w.units()[0]["id"], "text": "The bridge carried 1200 kilograms."}
            ],
            "evidence_status": "supported",
        },
    )
    w.update_job(job["id"], status="succeeded")
    return w, job


def test_cli_note_ui_edit_conflict_reload_and_revision_history(tmp_path, monkeypatch):
    w = Workspace(tmp_path / "workspace")
    path = tmp_path / "note.md"
    path.write_text("Первая мысль.\nВторая строка.")
    runner = CliRunner()
    result = runner.invoke(app, ["-w", str(w.path), "note", "create", "Мои мысли", str(path)])
    assert result.exit_code == 0, result.output
    note = json.loads(result.output)
    key = f"note:{w.path}:{note['id']}"
    ui = open_ui(w, monkeypatch)
    assert not ui.exception
    ui.text_area(key=key + ":text").set_value("Unsaved UI wording.").run()
    ui.selectbox(key="ui_language").select("en").run()
    assert not ui.exception and ui.text_area(key=key + ":text").value == "Unsaved UI wording."
    data = {**note["data"], "text": "Saved from CLI."}
    path.write_text(json.dumps(data))
    saved = runner.invoke(app, ["-w", str(w.path), "note", "save", note["id"], str(path), "1"])
    assert saved.exit_code == 0, saved.output
    ui.run()
    assert ui.text_area(key=key + ":text").value == "Unsaved UI wording."
    ui.button(key=key + ":save").click().run()
    assert any("Note changed" in e.value for e in ui.error)
    assert w.note(note["id"])["data"]["text"] == "Saved from CLI."
    ui.button(key=key + ":reload").click().run()
    assert ui.text_area(key=key + ":text").value == "Saved from CLI."
    ui.text_area(key=key + ":text").set_value("Edited from UI.")
    ui.button(key=key + ":save").click().run()
    assert not ui.exception and w.note(note["id"])["revision"] == 3
    old = runner.invoke(app, ["-w", str(w.path), "note", "show", note["id"], "--revision", "1"])
    assert (
        old.exit_code == 0
        and json.loads(old.output)["data"]["text"] == "Первая мысль.\nВторая строка."
    )


def test_ui_creates_note_and_clears_inputs_without_repeating_it(tmp_path, monkeypatch):
    w = Workspace(tmp_path / "workspace")
    ui = open_ui(w, monkeypatch)
    key = f"note:{w.path}:new"
    ui.text_input(key=key + ":title").set_value("Моя заметка")
    ui.text_area(key=key + ":text").set_value("Размышление об источнике.")
    ui.button(key=key + ":create").click().run()
    assert not ui.exception and len(w.notes()) == 1
    assert ui.text_area(key=key + ":text").value == ""
    ui.button(key=key + ":create").click().run()
    assert not ui.exception and len(w.notes()) == 1


def test_ui_answer_note_and_cli_follow_up_share_pinned_inputs(tmp_path, monkeypatch):
    w, parent = make_answer(tmp_path)
    monkeypatch.setattr(worker, "ensure_worker", lambda *_: None)
    ui = open_ui(w, monkeypatch)
    ui.button(key=f"answer-note-{parent['id']}").click().run()
    assert not ui.exception and len(w.notes()) == 1
    ui.button(key=f"answer-note-{parent['id']}").click().run()
    assert len(w.notes()) == 1
    note = w.notes()[0]
    result = CliRunner().invoke(
        app, ["-w", str(w.path), "note", "from-answer", parent["id"], "--revision", "1"]
    )
    assert result.exit_code == 0 and json.loads(result.output)["id"] == note["id"]
    editor = f"editor:{w.path}:{parent['id']}:text"
    dirty = {**w.draft(parent["id"])["data"], "answer": "Unsaved wording."}
    ui.text_area(key=editor).set_value(json.dumps(dirty)).run()
    assert ui.button(key=f"answer-note-{parent['id']}").disabled
    assert ui.button(key=f"follow-submit-{parent['id']}").disabled
    ui.button(key=f"reload-{parent['id']}").click().run()
    follow_key = f"editor:{w.path}:{parent['id']}:follow-up"
    ui.text_area(key=follow_key).set_value("А это максимум?").run()
    ui.selectbox(key="provider").select("claude").run()
    ui.button(key=f"follow-submit-{parent['id']}").click().run()
    assert not ui.exception and len(w.jobs()) == 2
    child = w.jobs()[0]
    assert child["params"]["provider"] == "ollama" and child["params"]["ollama_port"] == 11435
    assert child["params"]["conversation"] == [{"job_id": parent["id"], "revision": 1}]
    ui.button(key=f"follow-submit-{parent['id']}").click().run()
    assert len(w.jobs()) == 2
    result = CliRunner().invoke(
        app,
        [
            "-w",
            str(w.path),
            "ask",
            "А это максимум?",
            "--reply-to",
            parent["id"],
            "--revision",
            "1",
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["params"] == child["params"]


@pytest.mark.parametrize(
    "flags", [["--provider", "codex"], ["--model", "other"], ["--ollama-port", "11436"]]
)
def test_follow_up_cli_rejects_silent_provider_overrides(tmp_path, monkeypatch, flags):
    w, parent = make_answer(tmp_path)
    monkeypatch.setattr(worker, "ensure_worker", lambda *_: None)
    result = CliRunner().invoke(
        app, ["-w", str(w.path), "ask", "Why?", "--reply-to", parent["id"], *flags]
    )
    assert result.exit_code != 0 and "inherit" in result.output
    assert len(w.jobs()) == 1


def test_cli_draft_shows_frozen_conversation_and_original_evidence(tmp_path, monkeypatch):
    w, parent = make_answer(tmp_path)
    monkeypatch.setattr(worker, "ensure_worker", lambda *_: None)
    result = CliRunner().invoke(app, ["-w", str(w.path), "ask", "Why?", "--reply-to", parent["id"]])
    assert result.exit_code == 0, result.output
    child = json.loads(result.output)
    w.save_draft(child["id"], w.draft(parent["id"])["data"])
    w.update_job(child["id"], status="succeeded")
    shown = CliRunner().invoke(app, ["-w", str(w.path), "draft", "show", child["id"]])
    assert shown.exit_code == 0, shown.output
    data = json.loads(shown.output)
    assert data["conversation"]["turns"][0]["revision"] == 1
    assert data["evidence"][0]["source"] == "report.md"
    invalid = CliRunner().invoke(app, ["-w", str(w.path), "ask", "Why?", "--revision", "1"])
    assert invalid.exit_code != 0 and "requires" in invalid.output
