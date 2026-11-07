"""Small user settings shared by the CLI and local UI."""

import fcntl
import json
import os
import shutil
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path

from brofessor.contracts.content import InterfaceLanguage
from brofessor.contracts.text import (
    DEFAULT_OLLAMA_ADDRESS,
    TEXT_PROVIDERS,
    SettingsSnapshot,
    TextConnection,
    TextProvider,
)
from brofessor.infrastructure.storage.workspace import atomic_json
from brofessor.infrastructure.text.runners import normalize_ollama_address, validate_ollama_model


def path() -> Path:
    if configured := os.environ.get("XDG_CONFIG_HOME"):
        base = Path(configured).expanduser()
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path.home() / ".config"
    return base / "brofessor" / "preferences.json"


def data_directory() -> Path:
    if configured := os.environ.get("XDG_DATA_HOME"):
        base = Path(configured).expanduser()
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path.home() / ".local" / "share"
    return base / "brofessor"


def _read() -> dict:
    try:
        value = json.loads(path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    if not isinstance(value, dict):
        raise ValueError("Settings must contain a JSON object")
    return value


def read() -> dict:
    try:
        return _read()
    except (OSError, ValueError):
        return {}


@contextmanager
def edit(*, repair=False):
    destination = path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.with_suffix(".lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            values = _read()
        except ValueError as error:
            if not repair:
                raise OSError(f"Repair the settings file first: {destination}") from error
            backup = destination.with_name(f"preferences-{uuid.uuid4().hex}.invalid.json")
            shutil.copy2(destination, backup)
            values = {}
        yield values
        atomic_json(destination, values)


def update(**values):
    with edit() as current:
        current.update(values)


def text_connection(provider: str | None = None, *, for_edit=False) -> TextConnection:
    try:
        values = _read()
    except (OSError, ValueError) as error:
        if not for_edit:
            raise ValueError(
                f"Cannot read {path()}. Choose a text provider in Settings."
            ) from error
        values = {"text_provider": None}
    if provider is None:
        provider = values.get(
            "text_provider", None if "text_models" in values else TextProvider.CODEX
        )
    if provider not in TEXT_PROVIDERS:
        if for_edit:
            return {"provider": None, "model": None}
        raise ValueError("Choose codex, claude or ollama")
    models = values.get("text_models", {})
    model = models.get(provider) if isinstance(models, dict) else None
    if not isinstance(models, dict) or model is not None and not isinstance(model, str):
        if not for_edit:
            raise ValueError("Choose the text model again in Settings")
        model = None
    result: TextConnection = {"provider": str(provider), "model": model}
    if provider == TextProvider.OLLAMA:
        address = values.get("ollama_address", DEFAULT_OLLAMA_ADDRESS)
        if for_edit:
            result["ollama_address"] = address if isinstance(address, str) else ""
        else:
            result["ollama_address"] = normalize_ollama_address(address)
    return result


def save_text_connection(provider: str, model: str | None = None, *, ollama_address=None):
    if provider not in TEXT_PROVIDERS:
        raise ValueError("Choose codex, claude or ollama")
    if ollama_address is not None:
        if provider != TextProvider.OLLAMA:
            raise ValueError("Only Ollama uses a server address")
        ollama_address = normalize_ollama_address(ollama_address)
    if model and provider == TextProvider.OLLAMA:
        try:
            validate_ollama_model(model.strip())
        except RuntimeError as error:
            raise ValueError(str(error)) from error
    with edit(repair=True) as values:
        values["text_provider"] = provider
        if not isinstance(values.get("text_models"), dict):
            values["text_models"] = {}
        models = values["text_models"]
        if model and model.strip():
            models[provider] = model.strip()
        else:
            models.pop(provider, None)
        if ollama_address is not None:
            values["ollama_address"] = ollama_address


def settings(*, for_edit=False) -> SettingsSnapshot:
    """Application defaults; a task receives its own copy when it is created."""
    from brofessor.infrastructure.speech.catalogue import selected

    values = read()
    language = values.get("ui_language", InterfaceLanguage.RU)
    return {
        **text_connection(for_edit=for_edit),
        "language": str(language)
        if language in (InterfaceLanguage.RU, InterfaceLanguage.EN)
        else str(InterfaceLanguage.RU),
        "speech_model": selected(),
    }


def save_settings(provider, model=None, *, ollama_address=None, language, speech_model):
    """Validate all fields before one atomic preferences update."""
    from brofessor.infrastructure.speech.catalogue import CATALOG, get

    if language not in (InterfaceLanguage.RU, InterfaceLanguage.EN):
        raise ValueError("UI language must be ru or en")
    if provider not in (None, TextProvider.CODEX, TextProvider.CLAUDE, TextProvider.OLLAMA):
        raise ValueError("Choose codex, claude or ollama")
    if model is not None and not isinstance(model, str):
        raise ValueError("Model must be a name or empty")
    model = model.strip() or None if model is not None else None
    if provider is None and model:
        raise ValueError("Choose a provider before a model")
    if provider == TextProvider.OLLAMA:
        ollama_address = normalize_ollama_address(ollama_address or DEFAULT_OLLAMA_ADDRESS)
        if model:
            try:
                validate_ollama_model(model)
            except RuntimeError as error:
                raise ValueError(str(error)) from error
    elif ollama_address is not None:
        raise ValueError("Only Ollama uses a server address")
    speech = get(speech_model)
    if speech["id"] not in {item["id"] for item in CATALOG if not item.get("legacy")}:
        raise ValueError("Choose a supported speech model")
    with edit(repair=True) as values:
        values.update(text_provider=provider, ui_language=language, tts_model=speech["id"])
        if not isinstance(values.get("text_models"), dict):
            values["text_models"] = {}
        if provider is not None and model:
            values["text_models"][provider] = model
        elif provider is not None:
            values["text_models"].pop(provider, None)
        if provider == TextProvider.OLLAMA:
            values["ollama_address"] = ollama_address
    return settings(for_edit=True)
