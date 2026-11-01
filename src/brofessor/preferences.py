"""Small user settings shared by the CLI and local UI."""

import fcntl
import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path

from .workspace import atomic_json


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


def read() -> dict:
    try:
        value = json.loads(path().read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


@contextmanager
def edit():
    destination = path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.with_suffix(".lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        values = read()
        yield values
        atomic_json(destination, values)


def update(**values):
    with edit() as current:
        current.update(values)
