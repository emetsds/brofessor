"""Settings dialogs and future task model choices; execution stays in services."""

import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import streamlit as st

from brofessor.application import tasks
from brofessor.contracts.content import InterfaceLanguage
from brofessor.contracts.jobs import (
    ACTIVE_JOB_STATUSES,
    PODCAST_JOB_KINDS,
    RESUMABLE_JOB_STATUSES,
    JobKind,
    JobStatus,
)
from brofessor.contracts.text import TextProvider
from brofessor.infrastructure.speech import catalogue as speech_models
from brofessor.infrastructure.storage import preferences
from brofessor.infrastructure.storage.workspace import DATABASE_FILENAME
from brofessor.interfaces.web.components import language as ui_language
from brofessor.interfaces.web.components import layout as ui_layout
from brofessor.interfaces.web.state_keys import (
    MAINTENANCE_STATUS_KEY,
    OLLAMA_MODELS_ADDRESS_KEY,
    OLLAMA_MODELS_KEY,
    SETTINGS_ADDRESS_KEY,
    SETTINGS_MODEL_KEY,
    SETTINGS_OPEN_KEY,
    SETTINGS_PREFIX,
    SETTINGS_PROVIDER_KEY,
    SETTINGS_SECTION_KEY,
    SETTINGS_SPEECH_KEY,
    ProjectKey,
    SettingsSection,
    project_key,
    widget_options,
    widget_value,
)


def _preserve(prefix):
    for key in list(st.session_state):
        if key.startswith(prefix) and key[len(prefix) :] in {
            "provider",
            "model",
            "address",
            "speech",
            "language",
            SettingsSection.MODELS,
            "shown-provider",
            "initialized",
            "section",
            "revision",
            "ollama-download-name",
            "ollama-models",
            "ollama-models-address",
            "cache-project",
        }:
            st.session_state[key] = st.session_state[key]


def _initialize(prefix, values):
    if prefix + "initialized" in st.session_state:
        return
    st.session_state[prefix + "initialized"] = True
    st.session_state[prefix + "provider"] = values.get("provider")
    st.session_state[prefix + "model"] = values.get("model") or ""
    st.session_state[prefix + "address"] = (
        values.get("ollama_address")
        or preferences.text_connection(TextProvider.OLLAMA, for_edit=True)["ollama_address"]
    )
    st.session_state[prefix + "speech"] = values.get("speech_model") or speech_models.DEFAULT_ID
    st.session_state[prefix + "language"] = widget_value(
        values.get("language", InterfaceLanguage.RU)
    )
    st.session_state[prefix + SettingsSection.MODELS] = {
        values.get("provider"): values.get("model") or ""
    }
    st.session_state[prefix + "shown-provider"] = values.get("provider")


def _provider_changed(prefix):
    old = st.session_state[prefix + "shown-provider"]
    models = st.session_state[prefix + SettingsSection.MODELS]
    models[old] = st.session_state[prefix + "model"]
    current = st.session_state[prefix + "provider"]
    if current not in models:
        models[current] = preferences.text_connection(current, for_edit=True)["model"] or ""
    st.session_state[prefix + "model"] = models[current]
    st.session_state[prefix + "shown-provider"] = current


def text_fields(prefix, t):
    provider = st.selectbox(
        t("Provider"),
        widget_options([TextProvider.CODEX, TextProvider.CLAUDE, TextProvider.OLLAMA]),
        index=None,
        key=prefix + "provider",
        on_change=_provider_changed,
        args=(prefix,),
    )
    if provider == TextProvider.OLLAMA:
        st.text_input(t("Ollama address (IP:port)"), key=prefix + "address")
    model = st.text_input(
        t(
            "Installed Ollama model"
            if provider == TextProvider.OLLAMA
            else "Model (leave empty for the provider default)"
        ),
        key=prefix + "model",
    )
    destination = {
        TextProvider.CODEX: "OpenAI (Codex)",
        TextProvider.CLAUDE: "Anthropic (Claude)",
        TextProvider.OLLAMA: f"Ollama ({st.session_state[prefix + 'address']})",
    }.get(provider)
    if destination:
        st.caption(t("Selected source text goes to {destination}.", destination=destination))
    return {
        "provider": provider,
        "model": model.strip() or None,
        **(
            {"ollama_address": st.session_state[prefix + "address"]}
            if provider == TextProvider.OLLAMA
            else {}
        ),
    }


def speech_field(prefix, t, language=None):
    current = st.session_state[prefix + "speech"]
    catalog = speech_models.list_models()
    options = [
        item
        for item in catalog
        if item["compatible"] and (language is None or language in item["languages"])
    ]
    known = {item["id"] for item in catalog}
    if current not in known:
        try:
            old = speech_models.get(current)
            if language is None or language in old["languages"]:
                options.insert(0, {**old, "id": current})
        except ValueError:
            pass
    if len(catalog) > 1 or current not in known:
        st.selectbox(
            t("Speech model"),
            [item["id"] for item in options],
            index=None,
            key=prefix + "speech",
            format_func=lambda value: speech_models.get(value)["name"],
        )
        return st.session_state[prefix + "speech"]
    try:
        spec = speech_models.get(current)
        ui_layout.heading(t("Speech model: {model}", model=spec["name"]), level=4)
        if language and language not in spec["languages"]:
            st.warning(t("The speech model does not support this task's language."))
    except ValueError:
        st.warning(t("Choose a supported speech model."))
    return current


def _close():
    st.session_state[SETTINGS_OPEN_KEY] = False
    st.session_state.pop(SETTINGS_SPEECH_KEY, None)
    for key in list(st.session_state):
        if key.startswith(SETTINGS_PREFIX) and key != SETTINGS_SECTION_KEY:
            del st.session_state[key]


def dialog(t, *, language, address_override=None):
    st.dialog(t("Settings"), width="medium", on_dismiss=_close)(_dialog)(
        t, language=language, address_override=address_override
    )


def _dialog(t, *, language, address_override=None):
    prefix = SETTINGS_PREFIX
    _preserve(prefix)
    values = preferences.settings(for_edit=True)
    if address_override and not st.session_state.get("address_edited"):
        values["ollama_address"] = address_override
    _initialize(prefix, {**values, "language": language})
    section = st.radio(
        t("Settings section"),
        widget_options([SettingsSection.GENERAL, SettingsSection.MODELS, SettingsSection.STORAGE]),
        horizontal=True,
        key=prefix + "section",
        label_visibility="collapsed",
        format_func=lambda value: t(
            {
                SettingsSection.GENERAL: "General",
                SettingsSection.MODELS: "Models",
                SettingsSection.STORAGE: "Storage",
            }[value]
        ),
    )
    with st.container(key="settings-content"):
        model_progress(t)
        if section == SettingsSection.GENERAL:
            st.selectbox(
                "Язык интерфейса / Interface language",
                widget_options(list(ui_language.LANGUAGE_NAMES)),
                format_func=ui_language.LANGUAGE_NAMES.__getitem__,
                key=prefix + "language",
            )
            st.caption(t("Interface language does not change the language of your tasks."))
        elif section == SettingsSection.MODELS:
            ui_layout.heading(t("Default models"))
            st.caption(t("Used by new tasks. Existing tasks keep their own models."))
            text_fields(prefix, t)
            if st.button(t("Check connection"), key=prefix + "check"):
                from brofessor.infrastructure.text.runners import doctor

                try:
                    choice = _connection(prefix)
                    report = doctor(
                        choice["provider"],
                        choice["model"],
                        **(
                            {"ollama_address": choice["ollama_address"]}
                            if "ollama_address" in choice
                            else {}
                        ),
                    )
                    if report["available"]:
                        st.success(t("Connection ready"))
                    else:
                        st.error(report.get("diagnostic") or t("Connection unavailable"))
                    with st.expander(t("Connection details")):
                        st.json(report)
                except (OSError, ValueError, RuntimeError) as error:
                    st.error(t("Could not check the connection: {error}", error=error))
            ui_layout.rule()
            speech_field(prefix, t)
            storage(t, models_only=True, selected=st.session_state[prefix + "speech"])
        else:
            storage(t)

    with st.container(key="settings-actions"):
        save, cancel = st.columns(2)
        if save.button(t("Save settings"), key=prefix + "save", type="primary", width="stretch"):
            try:
                preferences.save_settings(
                    **_connection(prefix),
                    language=st.session_state[prefix + "language"],
                    speech_model=st.session_state[prefix + "speech"],
                )
                st.session_state.ui_language = st.session_state[prefix + "language"]
                if st.session_state[prefix + "provider"] == TextProvider.OLLAMA:
                    st.session_state.address_edited = True
                _close()
                st.rerun()
            except (OSError, ValueError, RuntimeError) as error:
                st.error(t("Could not save settings: {error}", error=error))
        if cancel.button(t("Cancel"), key=prefix + "cancel", width="stretch"):
            _close()
            st.rerun()


def _connection(prefix):
    provider = st.session_state[prefix + "provider"]
    return {
        "provider": provider,
        "model": st.session_state[prefix + "model"].strip() or None,
        **(
            {"ollama_address": st.session_state[prefix + "address"]}
            if provider == TextProvider.OLLAMA
            else {}
        ),
    }


def task_models(workspace, job, t):
    record = tasks.models(workspace, job["id"])
    data = record["data"]
    with ui_layout.section(t("Task models"), job["id"] + ":models"):
        st.caption(t("For future runs. Saving models does not start generation."))
        prefix = project_key(workspace.path, ProjectKey.TASK_MODELS, job["id"], "")
        _initialize(prefix, data)
        if prefix + "revision" not in st.session_state:
            st.session_state[prefix + "revision"] = record["revision"]
        if job["kind"] != JobKind.AUDIOBOOK:
            text_fields(prefix, t)
        if job["kind"] in (JobKind.PODCAST, JobKind.PODCAST_SERIES, JobKind.AUDIOBOOK):
            draft = workspace.draft(job["id"])
            speech_field(
                prefix, t, draft["data"]["language"] if draft else job["params"]["language"]
            )
        origin = {
            tasks.ModelOrigin.APPLICATION: "Copied from application defaults",
            tasks.ModelOrigin.CUSTOM: "Chosen for this task",
            tasks.ModelOrigin.PARENT: "Copied from the parent task",
        }.get(data.get("origin"), "Kept from the saved operation")
        st.caption(t(origin))
        save, defaults = st.columns(2)
        try:
            if save.button(t("Save task models"), key="task-model-save:" + prefix, width="stretch"):
                choice = {} if job["kind"] == JobKind.AUDIOBOOK else _connection(prefix)
                if job["kind"] in (JobKind.PODCAST, JobKind.PODCAST_SERIES, JobKind.AUDIOBOOK):
                    choice["speech_model"] = st.session_state[prefix + "speech"]
                tasks.save_models(
                    workspace, job["id"], choice, st.session_state[prefix + "revision"]
                )
                _clear(prefix)
                st.rerun()
            if defaults.button(
                t("Apply current default models"),
                key="task-model-defaults:" + prefix,
                width="stretch",
            ):
                tasks.apply_defaults(workspace, job["id"], st.session_state[prefix + "revision"])
                _clear(prefix)
                st.rerun()
        except (OSError, ValueError) as error:
            st.error(t("Could not save task models: {error}", error=error))
            if st.button(t("Load current model settings"), key="task-model-reload:" + prefix):
                _clear(prefix)
                st.rerun()
    return data


def _clear(prefix):
    for key in list(st.session_state):
        if key.startswith(prefix):
            del st.session_state[key]


def regenerate_controls(workspace, job, draft, saved, t, on_created):
    if not st.button(t("Regenerate text"), key=f"regenerate:{job['id']}", disabled=not saved):
        return
    try:
        model_revision = tasks.models(workspace, job["id"])["revision"]
        key = project_key(
            workspace.path, ProjectKey.REGENERATE, job["id"], draft["revision"], model_revision
        )
        request_key = st.session_state.setdefault(key, uuid.uuid4().hex)
        result = tasks.regenerate(
            workspace,
            job["id"],
            revision=draft["revision"],
            request_key=request_key,
        )
        on_created(result["id"])
        st.rerun()
    except (OSError, ValueError) as error:
        st.error(t("Could not submit the job: {error}", error=error))


def new_task_models(workspace, kind, t, *, address_override=None):
    defaults = preferences.settings(for_edit=True)
    if address_override and not st.session_state.get("address_edited"):
        defaults["ollama_address"] = address_override
    prefix = project_key(workspace.path, ProjectKey.NEW_MODELS, "")
    with st.expander(t("Task models")):
        own = st.toggle(t("Choose models for this task"), key=prefix + "custom")
        if kind == JobKind.AUDIOBOOK:
            if own:
                _initialize(prefix, defaults)
                return {"speech_model": speech_field(prefix, t)}
            st.caption(
                t(
                    "Speech model: {model}",
                    model=speech_models.get(defaults["speech_model"])["name"],
                )
            )
            return {"speech_model": defaults["speech_model"]}
        if own:
            _initialize(prefix, defaults)
            values = text_fields(prefix, t)
            if kind in PODCAST_JOB_KINDS:
                values["speech_model"] = speech_field(prefix, t)
            return values
        st.caption(t("New tasks copy the current application defaults."))
        if defaults.get("provider"):
            st.caption(
                t("Text provider: {provider}", provider=defaults["provider"])
                + " · "
                + (defaults.get("model") or t("Provider default"))
            )
        if kind in PODCAST_JOB_KINDS:
            st.caption(
                t(
                    "Speech model: {model}",
                    model=speech_models.get(defaults["speech_model"])["name"],
                )
            )
    return {
        key: value
        for key, value in defaults.items()
        if key != "language"
        and (key != "speech_model" or kind in PODCAST_JOB_KINDS)
        and (key != "ollama_address" or defaults.get("provider") == TextProvider.OLLAMA)
    }


@st.fragment(run_every=2)
def model_progress(t):
    from brofessor.application import maintenance

    if not st.session_state.get(SETTINGS_OPEN_KEY):
        return
    current = maintenance.latest_jobs()
    status_key = MAINTENANCE_STATUS_KEY
    snapshot = [
        (
            job["workspace_path"],
            job["id"],
            job["status"],
            job["cancel_requested"],
            job["worker_running"],
        )
        for job in current
    ]
    previous = st.session_state.get(status_key)
    st.session_state[status_key] = snapshot
    if previous is not None and snapshot != previous:
        st.rerun()
    shown = [job for job in current if job["status"] != JobStatus.SUCCEEDED]
    if shown:
        ui_layout.heading(t("Model downloads"))
    for job in shown:
        folder = job.get("workspace_path")
        if folder and not (Path(folder) / DATABASE_FILENAME).is_file():
            st.caption(t("Project folder unavailable"))
            continue
        if folder:
            from brofessor.infrastructure.storage.workspace import Workspace

            target = Workspace(folder)
        else:
            target = maintenance.workspace()
        operation_key = str(target.path) + ":" + job["id"]
        name = job["params"].get("model_spec", {}).get("name") or job["params"].get(
            "model", job["kind"]
        )
        status = {
            JobStatus.QUEUED: "Queued",
            JobStatus.RUNNING: "Running",
            JobStatus.FAILED: "Failed",
            JobStatus.INTERRUPTED: "Interrupted",
            JobStatus.CANCELLED: "Cancelled",
            JobStatus.SUCCEEDED: "Ready",
        }[job["status"]]
        st.caption(str(name) + " · " + t(status))
        progress = job["progress"]
        if progress.get("total"):
            st.progress(
                min(1.0, progress.get("completed", 0) / progress["total"]),
                text=t(
                    "Downloaded {completed} of {total} MB",
                    completed=f"{progress.get('completed', 0) / 1e6:.1f}",
                    total=f"{progress['total'] / 1e6:.1f}",
                ),
            )
        if job.get("error"):
            st.error(job["error"])
        if job["status"] in RESUMABLE_JOB_STATUSES:
            st.caption(
                t(
                    "Resume reuses downloaded files and continues incomplete files when supported by the server."
                )
            )
        try:
            if job["status"] in ACTIVE_JOB_STATUSES:
                if job["cancel_requested"]:
                    st.caption(t("Cancelling download…"))
                if st.button(
                    t("Cancel download"),
                    key=f"maintenance:cancel:{operation_key}",
                    disabled=bool(job["cancel_requested"]),
                ):
                    maintenance.cancel(job["id"], workspace_path=target.path)
                    st.rerun()
                if job["status"] == JobStatus.QUEUED and not job["worker_running"]:
                    st.caption(t("Background processing is stopped"))
                    if st.button(t("Resume"), key=f"maintenance:resume:{operation_key}"):
                        maintenance.resume(job["id"], workspace_path=target.path)
                        st.rerun()
            elif job["status"] in RESUMABLE_JOB_STATUSES:
                if st.button(t("Resume"), key=f"maintenance:resume:{operation_key}"):
                    maintenance.resume(job["id"], workspace_path=target.path)
                    st.rerun()
        except (OSError, ValueError, RuntimeError) as error:
            st.error(t("Storage operation failed: {error}", error=error))


def storage(t, *, models_only=False, selected=None):
    from brofessor.application import maintenance, projects
    from brofessor.infrastructure.storage.workspace import Workspace

    if not models_only:
        ui_layout.heading(t("Models on this computer"))
        st.caption(
            t("Codex and Claude models run through their tools; their weights are not stored here.")
        )
    try:
        downloads = maintenance.latest_jobs()
        inventory = maintenance.speech_inventory()
        focus = selected or st.session_state.get(SETTINGS_SPEECH_KEY)
        if focus and not any(
            item.get("reference") == speech_models.reference(focus) for item in inventory
        ):
            item = maintenance.speech_inventory(focus)[0]
            inventory = [row for row in inventory if row["id"] != item["id"]] + [item]
        for item in inventory:
            focused = bool(focus and item.get("reference") == speech_models.reference(focus))
            if models_only and not focused:
                continue
            with st.container(border=not models_only):
                spec = speech_models.get(item.get("reference", item["id"]))
                if not models_only:
                    ui_layout.heading(item["name"], level=4)
                st.caption(
                    t("Installed" if item["installed"] else "Not installed")
                    + f" · {item.get('stored_bytes', 0) / 1e9:.2f} GB"
                )
                st.caption(
                    t("Download size: {size} GB", size=f"{item['download_bytes'] / 1e9:.2f}")
                )
                if not models_only:
                    st.caption(
                        t(
                            "Languages: {languages}",
                            languages=", ".join(
                                ui_language.LANGUAGE_NAMES.get(value, value)
                                for value in spec["languages"]
                            ),
                        )
                    )
                if not item["compatible"]:
                    st.caption(t("This speech model is not compatible with this computer."))
                unfinished = any(
                    job["kind"] == JobKind.DOWNLOAD_MODEL
                    and job["status"] != JobStatus.SUCCEEDED
                    and (
                        speech_models.reference(job["params"]["model_spec"])
                        == item.get("reference")
                        if job["params"].get("model_spec")
                        else job["params"].get("model") == item["id"]
                    )
                    for job in downloads
                )
                if (
                    not item["installed"]
                    and item["compatible"]
                    and not unfinished
                    and st.button(
                        t("Download model"), key=(SETTINGS_PREFIX + f"download:{item['id']}")
                    )
                ):
                    maintenance.download_speech(item.get("reference", item["id"]))
                    st.rerun()
                if models_only:
                    continue
                with st.expander(t("Storage details")):
                    st.caption(item.get("reference") or speech_models.reference(spec))
                    if spec.get("requirements"):
                        requirement = spec["requirements"]
                        st.caption(
                            t(
                                "Requirements: {requirements} · License: {license}",
                                requirements=t(requirement)
                                if requirement in ui_language.RUSSIAN
                                else requirement,
                                license=spec.get("license", ""),
                            )
                        )
                    if item.get("path"):
                        st.caption(str(item["path"]))
                    if item.get("partial_bytes"):
                        st.caption(
                            t(
                                "Incomplete download: {size} MB",
                                size=f"{item['partial_bytes'] / 1e6:.1f}",
                            )
                        )
                    for dependency in item.get("dependencies", []):
                        st.caption(
                            t(
                                "Shared component: {name} · {size} GB",
                                name=dependency["id"],
                                size=f"{dependency['stored_bytes'] / 1e9:.2f}",
                            )
                        )
                        st.caption(dependency["path"])
                    if item.get("dependencies"):
                        st.caption(
                            t("Shared voice components are kept when removing model weights.")
                        )
                    st.caption(
                        t("Removing weights may require a download before future synthesis.")
                    )
                    if item.get("stored_bytes", 0) or item.get("partial_bytes", 0):
                        confirm = st.checkbox(
                            t("Remove these model files"),
                            key=(SETTINGS_PREFIX + f"confirm-model:{item['id']}"),
                        )
                        remove, partial = st.columns(2)
                        if remove.button(
                            t("Remove model"),
                            key=(SETTINGS_PREFIX + f"remove:{item['id']}"),
                            disabled=not confirm or not item.get("stored_bytes"),
                        ):
                            maintenance.remove_speech(item["id"])
                            st.rerun()
                        if partial.button(
                            t("Clear incomplete download"),
                            key=(SETTINGS_PREFIX + f"partial:{item['id']}"),
                            disabled=not confirm or not item.get("partial_bytes"),
                        ):
                            maintenance.clear_partial(item["id"])
                            st.rerun()
        if not models_only:
            with ui_layout.section(t("Download history"), "settings-download-history"):
                st.caption(
                    t("These are past download attempts. Installed models are listed above.")
                )
                try:
                    zone = ZoneInfo(getattr(st.context, "timezone", None) or "UTC")
                except ZoneInfoNotFoundError:
                    zone = ZoneInfo("UTC")
                history = []
                for job in maintenance.jobs():
                    name = job["params"].get("model_spec", {}).get("name") or job["params"].get(
                        "model"
                    )
                    history.append(
                        {
                            t("Started"): datetime.fromtimestamp(job["created"], zone).strftime(
                                "%d.%m.%Y %H:%M"
                            ),
                            t("Model"): str(name),
                            t("Result"): t(
                                "Download completed"
                                if job["status"] == JobStatus.SUCCEEDED
                                else {
                                    JobStatus.QUEUED: "Queued",
                                    JobStatus.RUNNING: "Running",
                                    JobStatus.FAILED: "Failed",
                                    JobStatus.CANCELLED: "Cancelled",
                                    JobStatus.INTERRUPTED: "Interrupted",
                                }[job["status"]]
                            ),
                        }
                    )
                if history:
                    st.dataframe(history, hide_index=True, width="stretch")
    except (OSError, ValueError, RuntimeError) as error:
        st.error(t("Storage operation failed: {error}", error=error))

    if models_only:
        return

    if st.session_state.get(SETTINGS_PROVIDER_KEY) == TextProvider.OLLAMA:
        address = st.session_state[SETTINGS_ADDRESS_KEY]
        st.divider()
        ui_layout.heading(t("Ollama server models"))
        st.caption(address)
        st.caption(
            t("These actions affect the selected Ollama server, which may be on another computer.")
        )
        try:
            if st.button(t("Refresh server models"), key="settings:ollama-refresh"):
                st.session_state[OLLAMA_MODELS_KEY] = maintenance.ollama_models(address)
                st.session_state[OLLAMA_MODELS_ADDRESS_KEY] = address
            if st.session_state.get(OLLAMA_MODELS_ADDRESS_KEY) == address:
                for item in st.session_state.get(OLLAMA_MODELS_KEY, []):
                    name = item.get("name", item.get("model"))
                    ui_layout.heading(str(name), level=4)
                    st.caption(f"{item.get('size', 0) / 1e9:.2f} GB")
                    if st.button(
                        t("Use for new tasks"),
                        key=(SETTINGS_PREFIX + f"ollama-use:{name}"),
                        disabled=st.session_state[SETTINGS_MODEL_KEY] == name,
                    ):
                        st.session_state[SETTINGS_MODEL_KEY] = name
                        st.success(t("Selected for new tasks. Save settings to apply."))
                    with st.popover(t("Remove model") + " · " + str(name)):
                        st.caption(address + " · " + str(name))
                        if st.button(
                            t("Confirm removal"), key=(SETTINGS_PREFIX + f"ollama-remove:{name}")
                        ):
                            maintenance.remove_ollama(address, name)
                            st.session_state.pop(OLLAMA_MODELS_KEY, None)
                            st.rerun()
            requested = st.text_input(t("Model to download"), key="settings:ollama-download-name")
            if st.button(
                t("Download model"), key="settings:ollama-download", disabled=not requested.strip()
            ):
                maintenance.download_ollama(address, requested.strip())
                st.rerun()
        except (OSError, ValueError, RuntimeError) as error:
            st.error(t("Storage operation failed: {error}", error=error))

    st.divider()
    ui_layout.heading(t("Speech segment cache"))
    available = [item for item in projects.list_projects() if item["available"]]
    if not available:
        st.caption(t("Open a project to manage its speech cache."))
        return
    names = {item["path"]: item["name"] for item in available}
    path = st.selectbox(
        t("Project"),
        list(names),
        format_func=names.__getitem__,
        key="settings:cache-project",
    )
    try:
        target = Workspace(path)
        info = maintenance.audio_cache_info(target)
        st.caption(f"{info['bytes'] / 1e9:.2f} GB · {info['files']} " + t("files"))
        st.caption(
            t(
                "Clearing segments keeps sources, edits and finished files. A future rebuild may synthesize speech again."
            )
        )
        confirm = st.checkbox(
            t("Clear this project's speech cache"), key=(SETTINGS_PREFIX + f"cache-confirm:{path}")
        )
        if st.button(
            t("Clear cache"), key="settings:cache-clear", disabled=not confirm or not info["files"]
        ):
            maintenance.clear_audio_cache(target)
            st.rerun()
    except (OSError, ValueError, RuntimeError) as error:
        st.error(t("Storage operation failed: {error}", error=error))
