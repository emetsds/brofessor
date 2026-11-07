"""Named projects are existing self-contained workspace directories."""

import re
import sqlite3
from pathlib import Path

from brofessor.contracts.jobs import ACTIVE_JOB_STATUSES
from brofessor.infrastructure.storage import preferences
from brofessor.infrastructure.storage.workspace import DATABASE_FILENAME, Workspace


def directory() -> Path:
    return (
        Path(
            preferences.read().get("projects_directory")
            or preferences.data_directory() / "projects"
        )
        .expanduser()
        .resolve()
    )


def _entries(values: dict) -> list[dict]:
    entries = values.get("projects", [])
    if not isinstance(entries, list) or any(
        not isinstance(item, dict)
        or not isinstance(item.get("name"), str)
        or not isinstance(item.get("path"), str)
        for item in entries
    ):
        raise ValueError("Project list in user preferences is invalid")
    return entries


def list_projects() -> list[dict]:
    values = preferences.read()
    return [
        {
            **item,
            "selected": item["path"] == values.get("last_project"),
            "available": (Path(item["path"]) / DATABASE_FILENAME).is_file(),
        }
        for item in _entries(values)
    ]


def selected() -> dict | None:
    return next((item for item in list_projects() if item["selected"]), None)


def deleted_projects() -> list[dict]:
    return _entries({"projects": preferences.read().get("deleted_projects", [])})


def delete(name_or_path: str) -> dict:
    """Remove a project from navigation without erasing its directory."""
    with preferences.edit() as values:
        entries = _entries(values)
        project = next((p for p in entries if name_or_path in (p["name"], p["path"])), None)
        if project is None:
            raise ValueError("Unknown project. Use project list or project open PATH")
        if (Path(project["path"]) / DATABASE_FILENAME).is_file():
            if any(j["status"] in ACTIVE_JOB_STATUSES for j in Workspace(project["path"]).jobs()):
                raise ValueError("Cancel active operations in this project before deleting it")
        values["projects"] = [p for p in entries if p is not project]
        removed = _entries({"projects": values.get("deleted_projects", [])})
        values["deleted_projects"] = [
            project,
            *(p for p in removed if p["path"] != project["path"]),
        ]
        values["recent_tasks"] = [
            r
            for r in values.get("recent_tasks", [])
            if isinstance(r, dict) and r.get("workspace_path") != project["path"]
        ]
        if values.get("last_project") == project["path"]:
            values.pop("last_project", None)
        return {**project, "deleted": True, "files_preserved": True}


def _name(value: str) -> str:
    value = value.strip()
    if not value or len(value) > 120 or any(ord(char) < 32 for char in value):
        raise ValueError("Project name must contain 1–120 printable characters")
    return value


def _register(path: Path, name: str | None = None, root: Path | None = None) -> dict:
    with preferences.edit() as values:
        entries = _entries(values)
        existing = next((item for item in entries if item["path"] == str(path)), None)
        if existing is None:
            removed = _entries({"projects": values.get("deleted_projects", [])})
            remembered = next((item for item in removed if item["path"] == str(path)), None)
            name = name or (remembered["name"] if remembered else None)
            label = _name(name or path.name)
            names = {item["name"] for item in entries}
            if name is None and label in names:
                suffix = 2
                while f"{label} ({suffix})" in names:
                    suffix += 1
                label = f"{label} ({suffix})"
            if label in names:
                raise ValueError("A project with this name already exists; choose another name")
            existing = {"name": label, "path": str(path)}
        values["projects"] = [existing, *(item for item in entries if item is not existing)]
        values["deleted_projects"] = [
            p
            for p in _entries({"projects": values.get("deleted_projects", [])})
            if p["path"] != str(path)
        ]
        values["last_project"] = str(path)
        if root is not None:
            values["projects_directory"] = str(root)
        return dict(existing)


def create(name: str, *, root: Path | str | None = None) -> dict:
    name = _name(name)
    if any(item["name"] == name for item in list_projects()):
        raise ValueError("A project with this name already exists; choose another name")
    root = Path(root).expanduser().resolve() if root is not None else directory()
    slug = re.sub(r"[^\w-]+", "-", name).strip("-").lower()
    if not slug:
        raise ValueError("Project name must contain a letter or number")
    root.mkdir(parents=True, exist_ok=True)
    destination = root / slug
    # Never adopt or overwrite an existing folder through the create operation.
    destination.mkdir()
    Workspace(destination)
    return _register(destination, name, root)


def open_project(path: Path | str, *, name: str | None = None) -> dict:
    path = Path(path).expanduser().resolve()
    database = path / DATABASE_FILENAME
    if not database.is_file():
        raise ValueError("This folder has no brofessor project (workspace.sqlite3 is missing)")
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    if not {"sources", "units", "jobs", "drafts", "artifacts"} <= tables:
        raise ValueError("This folder is not a brofessor project")
    Workspace(path)
    return _register(path, name)


def use(name_or_path: str) -> dict:
    project = next(
        (
            item
            for item in list_projects()
            if item["name"] == name_or_path or item["path"] == name_or_path
        ),
        None,
    )
    if project is None:
        raise ValueError("Unknown project. Use project list or project open PATH")
    return open_project(project["path"], name=project["name"])


def restore(name_or_path: str) -> dict:
    project = next((p for p in deleted_projects() if name_or_path in (p["name"], p["path"])), None)
    if project is None:
        raise ValueError("Unknown deleted project")
    return open_project(project["path"], name=project["name"])
