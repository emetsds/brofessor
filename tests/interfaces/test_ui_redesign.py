"""User workflows introduced by the project workspace UI."""

import json

import pytest
from streamlit.testing.v1 import AppTest
from streamlit.testing.v1.util import patch_config_options
from typer.testing import CliRunner

from brofessor.application import maintenance, projects, service, tasks
from brofessor.contracts.content import ContentLanguage
from brofessor.contracts.jobs import JobKind, JobStatus
from brofessor.contracts.text import TextProvider
from brofessor.infrastructure.speech import catalogue as speech_models
from brofessor.infrastructure.storage import preferences
from brofessor.infrastructure.storage.workspace import Workspace
from brofessor.interfaces.cli.app import app
from tests.helpers.ui import UI_APP, catalogue, choose_language, create, edit_json, new_key, section


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setattr("brofessor.application.worker.ensure_worker", lambda *_: None)
    with patch_config_options({"browser.gatherUsageStats": False}):
        yield


@pytest.fixture
def workspace(tmp_path):
    w = Workspace(tmp_path / "workspace")
    source = tmp_path / "source.md"
    source.write_text("A bridge carries a measured load.")
    w.add_source(source)
    return w


def saved(w, kind="slides", *, focus="Evidence", **params):
    job = service.submit(w, kind, focus=focus, start_worker=False, auto_audio=False, **params)
    citation = w.units()[0]["id"]
    if kind == "slides":
        data = {
            "title": "Measured evidence",
            "language": "en",
            "slides": [
                {
                    "title": "Original heading",
                    "bullets": ["Measured load"],
                    "notes": "Original notes",
                    "citations": [citation],
                }
            ],
        }
    elif kind == "podcast":
        data = {
            "title": "Evidence dialogue",
            "language": "en",
            "turns": [
                {"speaker": "host", "text": "What was measured?", "citations": [citation]},
                {"speaker": "guest", "text": "A load was measured.", "citations": [citation]},
            ],
        }
    else:
        data = {
            "answer": "A measured load.",
            "citations": [citation],
            "quotes": [{"citation": citation, "text": "A bridge carries a measured load."}],
        }
    service.edit_draft(w, job["id"], data, 0)
    w.update_job(job["id"], status=JobStatus.SUCCEEDED)
    return job


def open_ui(w, monkeypatch):
    monkeypatch.setattr("sys.argv", ["ui.py", "--workspace", str(w.path)])
    ui = AppTest.from_file(UI_APP, default_timeout=30).run()
    assert not ui.exception
    return ui


def test_dirty_render_is_blocked_and_concurrent_edit_pins_the_shown_revision(
    workspace, monkeypatch
):
    job = saved(workspace)
    ui = open_ui(workspace, monkeypatch)
    assert not any(w.key.endswith(":text") for w in ui.text_area)
    key = edit_json(ui, workspace, job["id"])
    data = json.loads(ui.text_area(key=key).value)
    data["title"] = "Unsaved title"
    ui.text_area(key=key).set_value(json.dumps(data)).run()
    assert ui.button(key=f"render-{job['id']}").disabled
    assert not [j for j in workspace.jobs() if j["kind"] == "render_slides"]
    ui.button(key=f"reload-{job['id']}").click().run()
    actual_render = service.render

    def race(w, job_id, **kwargs):
        draft = w.draft(job_id)
        updated = {**draft["data"], "title": "Concurrent title"}
        service.edit_draft(w, job_id, updated, draft["revision"])
        return actual_render(w, job_id, **kwargs)

    monkeypatch.setattr(service, "render", race)
    ui.button(key=f"render-{job['id']}").click().run()
    assert not ui.exception
    render = next(j for j in workspace.jobs() if j["kind"] == "render_slides")
    assert render["params"]["revision"] == 1
    assert workspace.draft(job["id"])["revision"] == 2
    assert any(
        "1" in c.value and "2" in c.value and "Файл из версии" in c.value for c in ui.caption
    )


def test_cli_can_render_an_explicit_saved_revision(workspace):
    from pptx import Presentation

    from brofessor.application import worker

    job = saved(workspace)
    data = workspace.draft(job["id"])["data"]
    data["slides"][0]["title"] = "Later heading"
    service.edit_draft(workspace, job["id"], data, 1)
    result = CliRunner().invoke(
        app, ["-w", str(workspace.path), "draft", "render", job["id"], "--revision", "1"]
    )
    assert result.exit_code == 0, result.output
    rendered = json.loads(result.output)
    worker.run(workspace, once=True)
    artifact = workspace.artifacts(rendered["id"])[0]
    deck = Presentation(workspace.path / artifact["path"])
    text = " ".join(shape.text for shape in deck.slides[0].shapes if shape.has_text_frame)
    assert "Original heading" in text and "Later heading" not in text


def test_structured_edits_survive_navigation_language_and_saving(workspace, monkeypatch):
    from brofessor.infrastructure.speech import catalogue as speech_models

    # Make audio generation available so only unsaved edits can block it.
    monkeypatch.setattr(speech_models, "qwen_runtime_available", lambda: True)
    available = [
        {**item, "installed": True, "compatible": True} for item in speech_models.list_models()
    ]
    monkeypatch.setattr(speech_models, "list_models", lambda: available)
    job = saved(workspace, "podcast")
    ui = open_ui(workspace, monkeypatch)
    ui.button(key=f"edit-{job['id']}").click().run()
    field = next(w for w in ui.text_area if w.label == "Текст реплики")
    field.set_value("What did the source actually measure?").run()
    assert ui.button(key=f"render-{job['id']}").disabled
    choose_language(ui, "en")
    section(ui, "results")
    ui.button(key=f"open-{job['id']}").click().run()
    assert (
        next(w for w in ui.text_area if w.label == "Spoken text").value
        == "What did the source actually measure?"
    )
    ui.button(key=f"save-{job['id']}").click().run()
    assert not ui.exception
    draft = workspace.draft(job["id"])
    assert draft["revision"] == 2
    assert draft["data"]["turns"][0]["text"] == "What did the source actually measure?"
    assert workspace.draft(job["id"], 1)["data"]["turns"][0]["text"] == "What was measured?"


def test_blank_slide_can_be_added_edited_and_revisited(workspace, monkeypatch):
    job = saved(workspace)
    ui = open_ui(workspace, monkeypatch)
    ui.button(key=f"edit-{job['id']}").click().run()
    key = f"editor:{workspace.path}:{job['id']}"
    ui.button(key=key + ":slides:add:0").click().run()
    assert not ui.exception
    selector = next(w for w in ui.selectbox if w.label == "Слайд")
    selector.select(1).run()
    assert not ui.exception
    field = next(w for w in ui.text_input if w.label == "Заголовок слайда")
    field.set_value("A new slide").run()
    next(w for w in ui.selectbox if w.label == "Слайд").select(0).run()
    next(w for w in ui.selectbox if w.label == "Слайд").select(1).run()
    assert next(w for w in ui.text_input if w.label == "Заголовок слайда").value == "A new slide"
    ui.button(key=f"save-{job['id']}").click().run()
    assert (
        not ui.exception
        and workspace.draft(job["id"])["data"]["slides"][1]["title"] == "A new slide"
    )


@pytest.mark.parametrize("value", [[], {"turns": None}])
def test_invalid_intermediate_podcast_json_keeps_recovery_and_reload(workspace, monkeypatch, value):
    job = saved(workspace, "podcast")
    original = workspace.draft(job["id"])
    ui = open_ui(workspace, monkeypatch)
    key = edit_json(ui, workspace, job["id"])
    ui.text_area(key=key).set_value(json.dumps(value)).run()
    assert not ui.exception
    assert list((workspace.path / "recovery" / job["id"]).glob("*.json"))
    ui.button(key=f"save-{job['id']}").click().run()
    assert not ui.exception and ui.error
    assert workspace.draft(job["id"]) == original
    ui.button(key=f"reload-{job['id']}").click().run()
    assert not ui.exception
    assert json.loads(ui.text_area(key=key).value) == original["data"]


def test_first_file_does_not_reset_the_open_material_on_progress_rerun(workspace, monkeypatch):
    from brofessor.application import pipeline

    job = saved(workspace)
    ui = open_ui(workspace, monkeypatch)
    assert next(e for e in ui.expander if e.label == "План слайдов").proto.expanded
    render = service.render(workspace, job["id"], start_worker=False)
    pipeline.execute(workspace, render)
    workspace.update_job(render["id"], status=JobStatus.SUCCEEDED)
    ui.run()
    assert not ui.exception
    assert next(e for e in ui.expander if e.label == "План слайдов").proto.expanded
    fresh = open_ui(workspace, monkeypatch)
    assert not next(e for e in fresh.expander if e.label == "План слайдов").proto.expanded


def test_related_navigation_and_search_reach_followups(workspace, monkeypatch):
    parent = saved(workspace, "ask", focus="Initial question")
    child = service.follow_up(workspace, parent["id"], "Specific follow-up", start_worker=False)
    service.edit_draft(workspace, child["id"], workspace.draft(parent["id"])["data"], 0)
    workspace.update_job(child["id"], status=JobStatus.SUCCEEDED)
    ui = open_ui(workspace, monkeypatch)
    group_key = f"ui:{workspace.path}:related:{parent['id']}"
    for _ in range(2):
        ui.selectbox(key=group_key).select(child["id"]).run()
        assert not ui.exception
        assert any(s.value == "Specific follow-up" for s in ui.header)
        ui.selectbox(key=group_key).select(parent["id"]).run()
        assert not ui.exception
        assert any(s.value == "Initial question" for s in ui.header)
    catalogue(ui)
    ui.text_input(key=f"ui:{workspace.path}:find-result").set_value("Specific follow-up").run()
    ui.button(key=f"open-{parent['id']}").click().run()
    assert not ui.exception
    assert any(s.value == "Specific follow-up" for s in ui.header)


def test_search_and_filter_include_series_episodes(workspace, monkeypatch):
    parent = service.submit(workspace, JobKind.PODCAST_SERIES, start_worker=False)
    episode = saved(workspace, "podcast")
    from brofessor.application.tasks import initial_models

    # Episode submission pins its series relationship through the normal job contract.
    linked = workspace.submit(
        JobKind.PODCAST,
        {**episode["params"], "series": {"job_id": parent["id"], "revision": 1, "episode": 1}},
        task_models=initial_models(JobKind.PODCAST, episode["params"]),
    )
    service.edit_draft(workspace, linked["id"], workspace.draft(episode["id"])["data"], 0)
    workspace.update_job(linked["id"], status=JobStatus.SUCCEEDED)
    ui = open_ui(workspace, monkeypatch)
    catalogue(ui)
    ui.selectbox(key=f"ui:{workspace.path}:filter").select("podcast").run()
    ui.text_input(key=f"ui:{workspace.path}:find-result").set_value("Evidence dialogue").run()
    ui.button(key=f"open-{parent['id']}").click().run()
    assert not ui.exception
    assert any(s.value == "Evidence dialogue" for s in ui.header)


def test_reopen_restores_distinct_edits_without_publishing_or_clobbering(workspace, monkeypatch):
    job = saved(workspace, "podcast")
    job_id = job["id"]
    first = open_ui(workspace, monkeypatch)
    second = open_ui(workspace, monkeypatch)
    for ui, wording in [(first, "From the first tab."), (second, "From the second tab.")]:
        ui.button(key=f"edit-{job_id}").click().run()
        field = next(w for w in ui.text_area if w.label == "Текст реплики")
        field.set_value(wording).run()
        assert all(b.disabled for b in ui.button if b.key == f"render-{job_id}")
    assert not any(j["kind"] in ("render_podcast", "preview_turn") for j in workspace.jobs())
    draft = workspace.draft(job_id)
    assert draft["revision"] == 1 and draft["data"]["turns"][0]["text"] == "What was measured?"
    data = {**draft["data"], "title": "Saved by another client"}
    service.edit_draft(workspace, job_id, data, 1)
    fresh = open_ui(workspace, monkeypatch)
    assert (
        next(w for w in fresh.text_area if w.label == "Текст реплики").value
        == "From the second tab."
    )
    assert all(b.disabled for b in fresh.button if b.key == f"render-{job_id}")
    fresh.button(key=f"save-{job_id}").click().run()
    assert fresh.error and workspace.draft(job_id)["revision"] == 2
    next(b for b in fresh.button if b.key and ":restore:" in b.key).click().run()
    assert (
        next(w for w in fresh.text_area if w.label == "Текст реплики").value
        == "From the first tab."
    )
    fresh.button(key=f"reload-{job_id}").click().run()
    assert (
        next(w for w in fresh.text_area if w.label == "Текст реплики").value == "What was measured?"
    )
    assert workspace.draft(job_id)["data"]["title"] == "Saved by another client"
    assert workspace.draft(job_id, 1) == draft


def test_new_note_survives_a_fresh_session_until_explicit_creation(workspace, monkeypatch):
    key = f"note:{workspace.path}:new"
    ui = section(open_ui(workspace, monkeypatch), "notes")
    ui.text_input(key=key + ":title").set_value("Working note").run()
    ui.text_area(key=key + ":text").set_value("Work in progress.").run()
    fresh = section(open_ui(workspace, monkeypatch), "notes")
    assert fresh.text_area(key=key + ":text").value == "Work in progress."
    assert workspace.notes() == []
    fresh.button(key=key + ":create").click().run()
    assert workspace.notes()[0]["data"]["text"] == "Work in progress."
    assert (
        section(open_ui(workspace, monkeypatch), "notes").text_area(key=key + ":text").value == ""
    )


def test_identical_unsaved_copies_can_diverge_without_losing_the_restored_text(
    workspace, monkeypatch
):
    job = saved(workspace, "podcast")
    first = open_ui(workspace, monkeypatch)
    first.button(key=f"edit-{job['id']}").click().run()
    next(w for w in first.text_area if w.label == "Текст реплики").set_value(
        "Shared unfinished text."
    ).run()
    second = open_ui(workspace, monkeypatch)
    assert (
        next(w for w in second.text_area if w.label == "Текст реплики").value
        == "Shared unfinished text."
    )
    next(w for w in first.text_area if w.label == "Текст реплики").set_value(
        "First tab continued."
    ).run()
    copies = list((workspace.path / "recovery" / job["id"]).glob("*.json"))
    contents = [json.loads(path.read_text())["content"] for path in copies]
    assert any("Shared unfinished text." in content for content in contents)
    assert any("First tab continued." in content for content in contents)
    assert workspace.draft(job["id"])["revision"] == 1


def test_settings_cancel_discards_all_staged_values_and_language_saves_without_provider(
    monkeypatch,
):
    preferences.update(text_provider=None, text_models={})
    before = preferences.settings(for_edit=True)
    monkeypatch.setattr("sys.argv", ["ui.py"])
    ui = AppTest.from_file(UI_APP, default_timeout=30).run()
    assert not ui.exception
    assert not any(widget.key == "ui_language" for widget in ui.selectbox)
    section(ui, "settings")
    ui.selectbox(key="settings:language").select("en").run()
    ui.radio(key="settings:section").set_value("models").run()
    ui.selectbox(key="settings:provider").select("ollama").run()
    ui.text_input(key="settings:address").set_value("192.0.2.10:11435").run()
    ui.text_input(key="settings:model").set_value("unsaved-local-model").run()
    assert preferences.settings(for_edit=True) == before
    ui.button(key="settings:cancel").click().run()
    assert not ui.exception and preferences.settings(for_edit=True) == before
    section(ui, "settings")
    ui.radio(key="settings:section").set_value("general").run()
    assert ui.selectbox(key="settings:language").value == before["language"]
    ui.selectbox(key="settings:language").select("en").run()
    ui.button(key="settings:save").click().run()
    assert not ui.exception
    assert preferences.settings(for_edit=True) == {**before, "language": "en"}
    assert projects.list_projects() == []
    assert not (preferences.data_directory() / "maintenance" / "workspace.sqlite3").exists()


def test_task_models_change_future_runs_and_regeneration_preserves_saved_inputs(
    workspace, monkeypatch
):
    job = saved(
        workspace,
        "ask",
        provider=TextProvider.OLLAMA,
        model="original-local-model",
        ollama_address="192.0.2.10:11435",
    )
    params = workspace.job(job["id"])["params"]
    draft = workspace.draft(job["id"])
    ui = open_ui(workspace, monkeypatch)
    prefix = f"ui:{workspace.path}:task-models:{job['id']}:"
    ui.selectbox(key=prefix + "provider").select("claude").run()
    ui.text_input(key=prefix + "model").set_value("task-text-model").run()
    ui.button(key="task-model-save:" + prefix).click().run()
    assert not ui.exception
    assert tasks.models(workspace, job["id"])["data"]["model"] == "task-text-model"
    assert workspace.job(job["id"])["params"] == params
    assert len(workspace.jobs()) == 1
    assert any(
        "claude" in item.value and "Используются источники" in item.value for item in ui.caption
    )
    preferences.save_settings(
        "codex",
        "new-default-model",
        language=ContentLanguage.RU,
        speech_model=speech_models.DEFAULT_ID,
    )
    ui.run()
    assert tasks.models(workspace, job["id"])["data"]["provider"] == "claude"
    key = edit_json(ui, workspace, job["id"])
    dirty = {**draft["data"], "answer": "Unsaved answer"}
    ui.text_area(key=key).set_value(json.dumps(dirty)).run()
    assert ui.button(key=f"regenerate:{job['id']}").disabled
    ui.button(key=f"reload-{job['id']}").click().run()
    ui.button(key=f"regenerate:{job['id']}").click().run()
    assert not ui.exception
    regenerated = next(item for item in workspace.jobs() if item["id"] != job["id"])
    assert regenerated["params"]["provider"] == "claude"
    assert regenerated["params"]["model"] == "task-text-model"
    assert regenerated["params"]["regeneration"] == {"job_id": job["id"], "revision": 1}
    assert workspace.job(job["id"])["params"] == params
    assert workspace.draft(job["id"]) == draft
    assert len(tasks.list_tasks(workspace)) == 1
    prefix = f"ui:{workspace.path}:task-models:{regenerated['id']}:"
    ui.button(key="task-model-defaults:" + prefix).click().run()
    assert not ui.exception
    assert tasks.models(workspace, job["id"])["data"]["model"] == "new-default-model"
    assert workspace.job(regenerated["id"])["params"]["model"] == "task-text-model"
    assert len(workspace.jobs()) == 2


def test_recent_cli_task_opens_existing_workspace_not_yet_in_project_catalogue(
    workspace, tmp_path, monkeypatch
):
    first = saved(workspace)
    other = Workspace(tmp_path / "cli-only")
    other.add_source(tmp_path / "source.md")
    question = "Question created from CLI"
    result = CliRunner().invoke(
        app, ["-w", str(other.path), "ask", question, "--provider", "codex"]
    )
    assert result.exit_code == 0, result.output
    job = json.loads(result.output)
    assert str(other.path) not in {p["path"] for p in projects.list_projects()}
    before = workspace.draft(first["id"])
    ui = open_ui(workspace, monkeypatch)
    next(b for b in ui.button if b.key.startswith("recent:") and b.label == question).click().run()
    assert not ui.exception and not ui.error
    assert ui.session_state["ui:project-path"] == str(other.path)
    assert ui.session_state[f"ui:{other.path}:selected-job"] == job["id"]
    assert str(other.path) in {p["path"] for p in projects.list_projects()}
    assert other.job(job["id"])["status"] == "queued"
    assert workspace.draft(first["id"]) == before


def test_global_recents_restore_distinct_project_edits_and_unsubmitted_tasks(
    workspace, tmp_path, monkeypatch
):
    first = saved(workspace)
    other = Workspace(tmp_path / "other-project")
    other.add_source(tmp_path / "source.md")
    second = saved(other)
    for target, job, title in ((workspace, first, "First deck"), (other, second, "Second deck")):
        current = target.draft(job["id"])
        service.edit_draft(target, job["id"], {**current["data"], "title": title}, 1)
        projects.open_project(target.path)
    projects.use(str(workspace.path))
    recent_order = preferences.read()["recent_tasks"]
    ui = open_ui(workspace, monkeypatch)
    assert preferences.read()["recent_tasks"] == recent_order
    # A second client can change its last-project preference without moving this tab.
    projects.use(str(other.path))
    ui.run()
    assert ui.button(key=f"edit-{first['id']}")
    ui.button(key=f"edit-{first['id']}").click().run()
    next(widget for widget in ui.text_input if widget.label == "Заголовок слайда").set_value(
        "Unfinished first heading"
    ).run()
    next(
        button
        for button in ui.button
        if button.key.startswith("recent:") and button.label == "Second deck"
    ).click().run()
    assert not ui.exception
    ui.button(key=f"edit-{second['id']}").click().run()
    next(widget for widget in ui.text_input if widget.label == "Заголовок слайда").set_value(
        "Unfinished second heading"
    ).run()
    next(
        button
        for button in ui.button
        if button.key.startswith("recent:") and button.label == "First deck"
    ).click().run()
    assert not ui.exception
    assert (
        next(widget for widget in ui.text_input if widget.label == "Заголовок слайда").value
        == "Unfinished first heading"
    )
    create(ui)
    ui.selectbox(key=new_key(ui, "kind")).select("ask").run()
    ui.text_area(key=new_key(ui, "focus")).set_value("First project's unfinished question").run()
    ui.selectbox(key=new_key(ui, "kind")).select("podcast").run()
    ui.selectbox(key=new_key(ui, "kind")).select("slides").run()
    ui.selectbox(key=new_key(ui, "kind")).select("ask").run()
    assert ui.text_area(key=new_key(ui, "focus")).value == "First project's unfinished question"
    next(
        button
        for button in ui.button
        if button.key.startswith("recent:") and button.label == "Second deck"
    ).click().run()
    assert (
        next(widget for widget in ui.text_input if widget.label == "Заголовок слайда").value
        == "Unfinished second heading"
    )
    create(ui)
    ui.text_area(key=new_key(ui, "focus")).set_value("Second project's unfinished focus").run()
    next(
        button
        for button in ui.button
        if button.key.startswith("recent:") and button.label == "First deck"
    ).click().run()
    create(ui)
    assert ui.text_area(key=new_key(ui, "focus")).value == "First project's unfinished question"
    assert workspace.draft(first["id"])["revision"] == other.draft(second["id"])["revision"] == 2
    assert len(workspace.jobs()) == len(other.jobs()) == 1


def test_download_started_without_project_survives_closing_settings(monkeypatch):
    model = speech_models.DEFAULT_ID
    inventory = maintenance.speech_inventory()
    monkeypatch.setattr(
        maintenance,
        "speech_inventory",
        lambda: [{**item, "installed": False, "compatible": True} for item in inventory],
    )
    monkeypatch.setattr("sys.argv", ["ui.py"])
    ui = AppTest.from_file(UI_APP, default_timeout=30).run()
    before = preferences.settings(for_edit=True)
    section(ui, "settings")
    ui.radio(key="settings:section").set_value("storage").run()
    ui.button(key=f"settings:download:{model}").click().run()
    assert not ui.exception
    job = maintenance.workspace().jobs()[0]
    assert job["kind"] == "download_model" and job["status"] == "queued"
    ui.button(key="settings:cancel").click().run()
    assert maintenance.workspace().job(job["id"])["status"] == "queued"
    assert preferences.settings(for_edit=True) == before
    assert projects.list_projects() == []
    section(ui, "settings")
    ui.radio(key="settings:section").set_value("storage").run()
    operation = str(maintenance.workspace().path) + ":" + job["id"]
    ui.button(key="maintenance:cancel:" + operation).click().run()
    assert not ui.exception and maintenance.workspace().job(job["id"])["status"] == "cancelled"
    ui.button(key="maintenance:resume:" + operation).click().run()
    assert not ui.exception and maintenance.workspace().job(job["id"])["status"] == "queued"


def test_download_history_does_not_claim_old_models_are_installed(workspace, monkeypatch):
    spec = speech_models.get(speech_models.DEFAULT_ID)
    job = workspace.submit(JobKind.DOWNLOAD_MODEL, {"model": spec["id"], "model_spec": spec})
    workspace.update_job(job["id"], status=JobStatus.SUCCEEDED)
    old = workspace.submit(JobKind.DOWNLOAD_MODEL, {"model": "retired-profile"})
    workspace.update_job(old["id"], status=JobStatus.SUCCEEDED)
    ui = open_ui(workspace, monkeypatch)
    section(ui, "settings")
    ui.radio(key="settings:section").set_value("storage").run()
    assert not ui.exception
    assert speech_models.installed_path(spec) is None
    assert any(item.value.startswith("Не установлена") for item in ui.caption)
    assert any("прошлые попытки" in item.value for item in ui.caption)
    history = ui.dataframe[0].value
    assert set(history["Модель"]) == {spec["name"], "retired-profile"}
    assert all(history["Дата запуска"].str.len() > 0)
    assert set(history["Результат"]) == {"Загрузка завершена"}


def test_tasks_navigation_prefix_filter_and_project_creation_scope(workspace, monkeypatch):
    monkeypatch.setattr(
        "brofessor.infrastructure.text.runners.generate",
        lambda *args, **kwargs: pytest.fail("Filtering must not call a model"),
    )
    first = saved(workspace)
    current = workspace.draft(first["id"])
    service.edit_draft(workspace, first["id"], {**current["data"], "title": "Голоса моста"}, 1)
    second = saved(workspace, "podcast")
    ui = open_ui(workspace, monkeypatch)
    catalogue(ui)
    assert ui.button(key=f"open-{first['id']}") and ui.button(key=f"open-{second['id']}")
    assert not any(b.key == "create_result" for b in ui.sidebar.button)
    assert not any(b.key == "task-catalogue" for b in ui.button)
    before = preferences.read()["recent_tasks"]
    query_key = f"ui:{workspace.path}:find-result"
    for query in ("г", "го", "ГОЛ"):
        ui.text_input(key=query_key).set_value(query).run()
        assert not ui.exception
        assert ui.button(key=f"open-{first['id']}")
        assert not any(b.key == f"open-{second['id']}" for b in ui.button)
    assert preferences.read()["recent_tasks"] == before
    ui.text_input(key=query_key).set_value("олос").run()
    assert not any(b.key and b.key.startswith("open-") for b in ui.button)
    ui.text_input(key=query_key).set_value("").run()
    ui.button(key=f"open-{first['id']}").click().run()
    assert not ui.exception
    ui.button(key=f"edit-{first['id']}").click().run()
    next(w for w in ui.text_input if w.label == "Заголовок слайда").set_value(
        "Unfinished heading"
    ).run()
    ui.button(key="nav:results").click().run()
    assert ui.button(key=f"open-{first['id']}")
    ui.button(key=f"open-{first['id']}").click().run()
    assert (
        next(w for w in ui.text_input if w.label == "Заголовок слайда").value
        == "Unfinished heading"
    )
    ui.button(key="all-projects").click().run()
    assert not ui.exception and not any(b.key == "create_result" for b in ui.button)
    ui.button(key="project:" + str(workspace.path)).click().run()
    assert ui.button(key="create_result") and ui.button(key=f"open-{first['id']}")


def test_model_status_after_removal_reopening_and_new_session(workspace, monkeypatch):
    weights = b"synthetic model files"
    spec = {
        "id": speech_models.DEFAULT_ID,
        "name": "Tiny test speech",
        "engine": "qwen3-base-mlx",
        "repo": "example/weights",
        "revision": "c" * 40,
        "files": {"model.pt": len(weights)},
        "download_bytes": len(weights),
        "languages": ["ru", "en"],
    }
    monkeypatch.setattr(speech_models, "CATALOG", [spec])
    target = speech_models.snapshot(spec)
    target.mkdir(parents=True)
    (target / "model.pt").write_bytes(weights)
    saved(workspace, "podcast")
    ui = open_ui(workspace, monkeypatch)
    section(ui, "settings")
    ui.radio(key="settings:section").set_value("storage").run()
    ui.checkbox(key=f"settings:confirm-model:{spec['id']}").check().run()
    ui.button(key=f"settings:remove:{spec['id']}").click().run()
    assert not ui.exception and speech_models.installed_path(spec) is None
    ui.radio(key="settings:section").set_value("models").run()
    assert any("Не установлена" in item.value for item in ui.caption)
    ui.button(key=f"settings:download:{spec['id']}").click().run()
    queue = maintenance.workspace()
    job = queue.jobs()[0]
    queue.update_job(
        job["id"], status=JobStatus.RUNNING, progress={"completed": 4_000_000, "total": 10_000_000}
    )
    ui.button(key="settings:cancel").click().run()
    section(ui, "settings")
    assert any("4.0" in bar.proto.text and "10.0" in bar.proto.text for bar in ui.get("progress"))
    assert any("Прервано" in item.value for item in ui.caption)
    assert not any(b.key == f"settings:download:{spec['id']}" for b in ui.button)
    # A fresh browser session resolves progress from SQLite, without prior widget state.
    fresh = open_ui(workspace, monkeypatch)
    section(fresh, "settings")
    assert any("4.0" in bar.proto.text for bar in fresh.get("progress"))
    operation = str(queue.path) + ":" + job["id"]
    fresh.button(key="maintenance:resume:" + operation).click().run()
    assert not fresh.exception and queue.job(job["id"])["status"] == "queued"
    assert len(queue.jobs()) == 1
    target.mkdir(parents=True, exist_ok=True)
    (target / "model.pt").write_bytes(weights)
    queue.update_job(job["id"], status=JobStatus.SUCCEEDED)
    fresh.radio(key="settings:section").set_value("models").run()
    assert any(item.value.startswith("Установлена") for item in fresh.caption)
    assert not any(b.key == f"settings:download:{spec['id']}" for b in fresh.button)
    fresh.radio(key="settings:section").set_value("storage").run()
    fresh.checkbox(key=f"settings:confirm-model:{spec['id']}").check().run()
    fresh.button(key=f"settings:remove:{spec['id']}").click().run()
    assert any(item.value.startswith("Не установлена") for item in fresh.caption)
    assert fresh.button(key=f"settings:download:{spec['id']}")
    assert len(queue.jobs()) == 1  # Reopening/removing never starts another download.


def test_installed_base_still_requires_speech_runtime_for_new_audio(workspace, monkeypatch):
    models = speech_models.list_models()
    monkeypatch.setattr(
        speech_models,
        "list_models",
        lambda: [{**item, "installed": True, "compatible": True} for item in models],
    )
    monkeypatch.setattr(speech_models, "qwen_runtime_available", lambda: False)
    job = saved(workspace, "podcast")
    ui = open_ui(workspace, monkeypatch)
    ui.button(key=f"edit-{job['id']}").click().run()
    assert not ui.exception
    assert ui.button(key=f"render-{job['id']}").disabled
    assert not any(button.key == f"preview-{job['id']}" for button in ui.button)
    assert len(workspace.jobs()) == 1
    monkeypatch.setattr(speech_models, "qwen_runtime_available", lambda: True)
    ui.run()
    assert ui.button(key=f"render-{job['id']}") and ui.button(key=f"preview-{job['id']}")
    assert len(workspace.jobs()) == 1


def test_task_operation_details_can_cancel_and_resume_a_historical_turn_preview(
    preset_voices, workspace, monkeypatch
):
    job = saved(workspace, "podcast")
    preview = service.render(
        workspace, job["id"], model="qwen3-base", turn=1, revision=1, start_worker=False
    )
    params = workspace.job(preview["id"])["params"]
    ui = open_ui(workspace, monkeypatch)
    ui.selectbox(key=f"ui:{workspace.path}:operation:{job['id']}").select(preview["id"]).run()
    ui.button(key="operation:cancel-" + preview["id"]).click().run()
    assert not ui.exception
    assert workspace.job(preview["id"])["status"] == "cancelled"
    ui.button(key="operation:resume-" + preview["id"]).click().run()
    assert not ui.exception
    assert workspace.job(preview["id"])["status"] == "queued"
    assert workspace.job(preview["id"])["params"] == params
    assert workspace.draft(job["id"])["revision"] == 1


def test_script_check_pins_saved_wording_and_displays_review_without_editing(
    workspace, monkeypatch
):
    from brofessor.application import worker

    job = saved(workspace, "podcast")
    data = workspace.draft(job["id"])["data"]
    data["turns"][1]["text"] = "Nothing was measured."
    service.edit_draft(workspace, job["id"], data, 1)
    citation = workspace.units()[0]["id"]
    ui = open_ui(workspace, monkeypatch)
    buffer = edit_json(ui, workspace, job["id"])
    unsaved = {**data, "title": "Unpublished title"}
    ui.text_area(key=buffer).set_value(json.dumps(unsaved)).run()
    assert ui.button(key=f"script-check-start:{job['id']}").disabled
    ui.button(key=f"reload-{job['id']}").click().run()
    ui.button(key=f"script-check-start:{job['id']}").click().run()
    assert not ui.exception
    check = workspace.jobs()[0]
    assert check["kind"] == "check_podcast" and check["params"]["revision"] == 2
    ui.button(key="script-check:cancel-" + check["id"]).click().run()
    assert workspace.job(check["id"])["status"] == "cancelled"
    ui.button(key="script-check:resume-" + check["id"]).click().run()

    def assess(*args, **kwargs):
        quote = {"citation": citation, "text": "A bridge carries a measured load."}
        return {
            "assessments": [
                {
                    "turn": 1,
                    "status": "supported",
                    "explanation": "A question about measurement.",
                    "findings": [],
                    "quotes": [quote],
                },
                {
                    "turn": 2,
                    "status": "issue",
                    "explanation": "The statement conflicts with the original.",
                    "findings": [
                        {
                            "claim": "Nothing was measured.",
                            "kind": "contradiction",
                            "explanation": "The original explicitly records a measured load.",
                            "quotes": [quote],
                        }
                    ],
                    "quotes": [],
                },
            ]
        }

    monkeypatch.setattr("brofessor.infrastructure.text.runners.generate", assess)
    worker.run(workspace, once=True)
    ui.run()
    assert not ui.exception
    assert any(item.value == "Nothing was measured." for item in ui.text)
    assert any("source.md" in item.value for item in ui.caption)
    assert any("Отчёт по сохранённой версии 2" in item.value for item in ui.caption)
    assert workspace.draft(job["id"])["data"] == data
    assert len([item for item in workspace.jobs() if item["kind"] == "check_podcast"]) == 1


def test_experimental_writer_can_be_selected_for_a_new_long_podcast(workspace, monkeypatch):
    from tests.helpers.ui import new_key

    ui = open_ui(workspace, monkeypatch)
    create(ui)
    ui.selectbox(key=new_key(ui, "kind")).select("podcast").run()
    ui.toggle(key=f"ui:{workspace.path}:new:originals").set_value(True).run()
    ui.button(key="prepare").click().run()
    assert not ui.exception
    job = workspace.jobs()[0]
    assert job["params"]["writing_method"] == "originals"


def test_delete_task_cancel_and_restore_keep_unsaved_editor_and_saved_revisions(
    workspace, monkeypatch
):
    job = saved(workspace)
    before = workspace.draft(job["id"])
    ui = open_ui(workspace, monkeypatch)
    ui.button(key=f"edit-{job['id']}").click().run()
    next(w for w in ui.text_input if w.label == "Заголовок слайда").set_value(
        "Unfinished heading kept through trash"
    ).run()
    ui.button(key="delete-task").click().run()
    ui.button(key="delete:cancel").click().run()
    assert not ui.exception and not tasks.deleted_roots(workspace)
    ui.button(key="delete-task").click().run()
    ui.button(key="delete:confirm").click().run()
    assert not ui.exception
    assert tasks.list_tasks(workspace) == [] and tasks.recent_tasks() == []
    ui.run()
    assert workspace.draft(job["id"]) == before
    ui.button(key=f"restore-task:{job['id']}").click().run()
    assert not ui.exception and tasks.list_tasks(workspace)
    assert next(w for w in ui.text_input if w.label == "Заголовок слайда").value == (
        "Unfinished heading kept through trash"
    )
    assert workspace.draft(job["id"]) == before


def test_delete_project_does_not_reopen_workspace_argument_and_restores_from_catalogue(
    workspace, monkeypatch
):
    job = saved(workspace)
    before = workspace.draft(job["id"])
    ui = open_ui(workspace, monkeypatch)
    ui.button(key="delete-project").click().run()
    ui.button(key="delete:cancel").click().run()
    assert not ui.exception and projects.selected()
    ui.button(key="delete-project").click().run()
    ui.button(key="delete:confirm").click().run()
    assert not ui.exception and not projects.list_projects()
    ui.run()
    assert not projects.list_projects()
    ui.button(key=f"restore-project:{workspace.path}").click().run()
    assert not ui.exception
    assert projects.selected()["path"] == str(workspace.path)
    assert workspace.draft(job["id"]) == before
