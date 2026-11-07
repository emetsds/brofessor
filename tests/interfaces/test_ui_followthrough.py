"""Creation, background navigation and editing as visible user workflows."""

from types import SimpleNamespace

from streamlit.testing.v1 import AppTest

from brofessor.application import service, tasks
from brofessor.contracts.jobs import JobKind, JobStatus
from brofessor.infrastructure.storage.workspace import Workspace
from tests.helpers.ui import UI_APP, new_key, section


def open_ui(w, monkeypatch):
    monkeypatch.setattr("sys.argv", ["ui.py", "--workspace", str(w.path)])
    monkeypatch.setattr("brofessor.application.worker.ensure_worker", lambda *_: None)
    ui = AppTest.from_file(UI_APP, default_timeout=30).run()
    assert not ui.exception
    return ui


def test_creation_opens_task_and_background_navigation_preserves_unsubmitted_input(
    tmp_path, monkeypatch
):
    w = Workspace(tmp_path / "workspace")
    path = tmp_path / "bridge.txt"
    path.write_text("A bridge supports eighty kilograms.")
    w.add_source(path)
    ui = open_ui(w, monkeypatch)
    ui.button(key="create_result").click().run()
    ui.text_input(key=new_key(ui, "title")).set_value("My bridge task").run()
    ui.text_area(key=new_key(ui, "focus")).set_value("Explain the source in detail").run()
    ui.button(key="prepare").click().run()
    job = w.jobs()[0]
    assert tasks.title(w, job) == "My bridge task"
    assert any(s.value == "My bridge task" for s in ui.header)
    assert any(b.key == f"cancel-{job['id']}" for b in ui.button)
    assert not any(b.key == f"active-open-{job['id']}" for b in ui.button)
    ui.button(key="create_result").click().run()
    ui.text_area(key=new_key(ui, "focus")).set_value("An unsent second request").run()
    ui.button(key=f"active-open-{job['id']}").click().run()
    assert any(s.value == "My bridge task" for s in ui.header)
    ui.button(key="create_result").click().run()
    assert ui.text_area(key=new_key(ui, "focus")).value == "An unsent second request"
    section(ui, "sources")
    ui.button(key=f"active-open-{job['id']}").click().run()
    assert any(s.value == "My bridge task" for s in ui.header)
    assert any("Explain the source" in h.value for h in ui.get("html"))
    assert service.task_details(w, job["id"])["coverage"] is None
    assert not ui.exception and len(w.jobs()) == 1
    from brofessor.application import initial_audio, maintenance
    from brofessor.infrastructure.speech import catalogue as speech_models

    monkeypatch.setattr(speech_models, "installed_path", lambda *_: None)
    unit = w.units()[0]["id"]
    service.edit_draft(
        w,
        job["id"],
        {
            "title": "Generated material",
            "language": "ru",
            "turns": [
                {"speaker": "host", "text": "Question?", "citations": [unit]},
                {"speaker": "guest", "text": "A measured load.", "citations": [unit]},
            ],
        },
        0,
    )
    w.update_job(job["id"], status=JobStatus.SUCCEEDED)
    initial_audio.reconcile(w)
    ui.run()
    assert any("Файлы модели речи отсутствуют" in message.value for message in ui.warning)
    assert ui.button(key=f"render-{job['id']}").disabled
    assert ui.button(key=f"edit-{job['id']}")
    ui.button(key=f"auto-model-settings:{job['id']}").click().run()
    assert ui.button(key="settings:cancel") and maintenance.jobs() == []
    ui.button(key="settings:cancel").click().run()
    assert tasks.title(w, w.job(job["id"])) == "My bridge task" and len(w.jobs()) == 1


def test_turn_pager_navigates_selects_pages_and_clamps_revision(tmp_path, monkeypatch):
    w = Workspace(tmp_path / "workspace")
    path = tmp_path / "bridge.txt"
    path.write_text("A bridge supports eighty kilograms.")
    w.add_source(path)
    job = service.submit(w, JobKind.PODCAST, auto_audio=False, start_worker=False)
    unit = w.units()[0]["id"]
    turns = [
        {"speaker": "host" if i % 2 == 0 else "guest", "text": f"Turn {i + 1}", "citations": [unit]}
        for i in range(25)
    ]
    data = {"title": "Bridge", "language": "ru", "turns": turns}
    service.edit_draft(w, job["id"], data, 0)
    w.update_job(job["id"], status=JobStatus.SUCCEEDED)
    ui = open_ui(w, monkeypatch)
    key = f"editor:{w.path}:{job['id']}:preview-page"
    assert not next(e for e in ui.expander if e.label == "Сценарий · 25 реплик").proto.expanded
    assert ui.button(key=key + ":previous").disabled
    ui.selectbox(key=key + ":select").set_value(3).run()
    assert any("17–24" in c.value for c in ui.caption)
    section(ui, "sources")
    next(b for b in ui.button if b.key.startswith("recent:")).click().run()
    assert ui.selectbox(key=key + ":select").value == 3
    assert any("17–24" in c.value for c in ui.caption)
    ui.button(key=key + ":next").click().run()
    assert any("25–25" in c.value for c in ui.caption)
    assert ui.button(key=key + ":next").disabled
    ui.button(key=key + ":previous").click().run()
    assert ui.selectbox(key=key + ":select").value == 3
    service.edit_draft(w, job["id"], {**data, "turns": turns[:2]}, 1)
    ui.run()
    # Explicitly load the new saved revision; the existing editor buffer is preserved until then.
    ui.button(key=f"reload-{job['id']}").click().run()
    assert any("1–2" in c.value for c in ui.caption)
    assert not any(b.key in (key + ":next", key + ":previous") for b in ui.button)
    assert not ui.exception


def test_source_dialog_preserves_partial_success_and_closes_after_retry(tmp_path, monkeypatch):
    w = Workspace(tmp_path / "workspace")
    uploads = [
        SimpleNamespace(name=name, getvalue=lambda data=data: data)
        for name, data in (
            ("bridge.md", b"Bridge evidence"),
            ("same.txt", b"Bridge evidence"),
            ("broken.pdf", b"not a pdf"),
        )
    ]
    monkeypatch.setattr("streamlit.file_uploader", lambda *_a, **_kw: uploads)
    ui = open_ui(w, monkeypatch)
    ui.button(key="header-add-source").click().run()
    ui.button(key="import_sources").click().run()
    assert len(w.sources()) == 1
    assert any("broken.pdf" in e.value for e in ui.error)
    assert any("Уже есть" in item.value for item in ui.success)
    assert any(b.key == "import_sources" for b in ui.button)
    uploads.pop()
    # Replacing an already successful row with new bytes must import that revision.
    uploads[0] = SimpleNamespace(name="bridge.md", getvalue=lambda: b"New bridge evidence")
    ui.button(key="import_sources").click().run()
    assert not any(b.key == "import_sources" for b in ui.button)
    assert any(s.value == "Источники" for s in ui.header)
    assert len(w.sources()) == 2 and not w.jobs()
    assert {unit["text"] for unit in w.units()} == {"Bridge evidence", "New bridge evidence"}
    ui.button(key="sources-add-source").click().run()
    ui.radio(key=f"ui:{w.path}:source-import:mode").set_value("folder").run()
    ui.text_input(key=f"directory:{w.path}").set_value(str(tmp_path / "missing")).run()
    ui.button(key="connect_directory").click().run()
    assert ui.text_input(key=f"directory:{w.path}").value == str(tmp_path / "missing")
    assert ui.error and not w.jobs()


def test_cancelled_render_keeps_its_stage_and_resume_in_the_main_panel(tmp_path, monkeypatch):
    w = Workspace(tmp_path / "workspace")
    path = tmp_path / "source.txt"
    path.write_text("A bridge carries a load.")
    w.add_source(path)
    job = service.submit(w, JobKind.SLIDES, title="Bridge slides", start_worker=False)
    unit = w.units()[0]["id"]
    service.edit_draft(
        w,
        job["id"],
        {
            "title": "Material",
            "language": "ru",
            "slides": [
                {"title": "Load", "bullets": ["A load"], "notes": "Evidence", "citations": [unit]}
            ],
        },
        0,
    )
    w.update_job(job["id"], status=JobStatus.SUCCEEDED)
    render = service.render(w, job["id"], start_worker=False)
    w.cancel(render["id"])
    ui = open_ui(w, monkeypatch)
    assert any("Отменено · Этап остановки" in m.value for m in ui.warning)
    assert ui.button(key=f"resume-{render['id']}")
    ui.button(key=f"resume-{render['id']}").click().run()
    assert w.job(render["id"])["status"] == "queued"
    assert len([j for j in w.jobs() if j["kind"] == "render_slides"]) == 1
