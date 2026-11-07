"""Navigate the public UI in behavioral tests; no model or service behavior is mocked here."""

from importlib.resources import files

UI_APP = str(files("brofessor.interfaces.web").joinpath("app.py"))


def section(ui, name):
    if name == "settings":
        if not any(button.key == "settings:cancel" for button in ui.button):
            ui.button(key="settings-open").click().run()
    else:
        if any(button.key == "settings:cancel" for button in ui.button):
            ui.button(key="settings:cancel").click().run()
        key = {"projects": "all-projects", "search": "find-task"}.get(name, "nav:" + name)
        ui.button(key=key).click().run()
    assert not ui.exception
    return ui


def choose_language(ui, language):
    section(ui, "settings")
    ui.radio(key="settings:section").set_value("general").run()
    ui.selectbox(key="settings:language").select(language).run()
    ui.button(key="settings:save").click().run()
    assert not ui.exception
    return ui


def model_settings(ui):
    section(ui, "settings")
    ui.radio(key="settings:section").set_value("models").run()
    assert not ui.exception
    return ui


def new_key(ui, field):
    for kind in (
        "selectbox",
        "multiselect",
        "text_area",
        "select_slider",
        "number_input",
        "text_input",
    ):
        for widget in ui.get(kind):
            if widget.key and widget.key.endswith(":new:" + field):
                return widget.key
    raise AssertionError(f"Creation field is not shown: {field}")


def select_project(ui, path):
    ui.button(key="project:" + str(path)).click().run()
    assert not ui.exception
    return ui


def catalogue(ui):
    section(ui, "results")
    assert not ui.exception
    return ui


def create(ui):
    ui.button(key="create_result").click().run()
    assert not ui.exception
    return ui


def edit_json(ui, workspace, job_id):
    catalogue(ui)
    if any(b.key == f"open-{job_id}" for b in ui.button):
        ui.button(key=f"open-{job_id}").click().run()
    key = f"editor:{workspace.path}:{job_id}"
    ui.toggle(key=key + ":json").set_value(True).run()
    assert not ui.exception
    return key + ":text"
