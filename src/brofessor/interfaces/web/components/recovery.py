"""Local recovery copies. They are separate from saved revisions and job inputs."""

import hashlib
import json
import uuid
from importlib.resources import files
from pathlib import Path
from typing import Final, TypedDict

import streamlit as st

from brofessor.infrastructure.storage.workspace import atomic_json
from brofessor.interfaces.web.state_keys import EditorSuffix

RECOVERY_DIRECTORY: Final = "recovery"
CLOSING_FIELD_STORAGE_PREFIX: Final = "brofessor:closing-field:"
RECOVER_TRIGGER_NAME: Final = "recover"


class ClosingFieldEvent(TypedDict):
    id: str
    revision: int
    content: str | dict
    path: list[str | int]
    lines: bool
    text: str


def copies(folder):
    found = []
    for path in folder.glob("*.json"):
        try:
            found.append((path.stat().st_mtime_ns, path))
        except FileNotFoundError:
            continue  # Another editor saved or changed this recovery copy.
    return [path for _, path in sorted(found, reverse=True)]


def restore(key, path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    owner = st.session_state.setdefault(key + EditorSuffix.RECOVERY_OWNER, uuid.uuid4().hex)
    try:
        owned = write_copy(
            path.parent, value["revision"], value["content"], item=value.get("item"), owner=owner
        )
    except OSError as error:
        st.session_state[key + EditorSuffix.PROTECTION_ERROR] = str(error)
        owned = path
    st.session_state[key + EditorSuffix.ORIGIN_COPY] = path
    st.session_state[key + EditorSuffix.COPY] = owned
    st.session_state[key + EditorSuffix.RECOVERED] = True
    return value


def forget(key, *, retire_origin=True):
    previous = st.session_state.get(key + EditorSuffix.COPY)
    if previous is not None:
        previous.unlink(missing_ok=True)
    if retire_origin:
        origin = st.session_state.pop(key + EditorSuffix.ORIGIN_COPY, None)
        if origin is not None:
            origin.unlink(missing_ok=True)
    st.session_state.pop(key + EditorSuffix.COPY, None)
    st.session_state.pop(key + EditorSuffix.RECOVERED, None)


def write_copy(folder, revision, content, *, item=None, owner=None):
    # Independent browser edits can start from the same copy. Retiring that
    # immutable snapshot must never remove the other editor's new contents.
    snapshot = {"revision": revision, "content": content}
    if item is not None:
        snapshot["item"] = item
    digest = hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()
    target = Path(folder) / f"{owner or uuid.uuid4().hex}-{digest}.json"
    if not target.is_file():
        atomic_json(target, snapshot)
    return target


def protect(key, folder, revision, content, *, item=None):
    try:
        owner = st.session_state.setdefault(key + EditorSuffix.RECOVERY_OWNER, uuid.uuid4().hex)
        target = write_copy(folder, revision, content, item=item, owner=owner)
    except OSError as error:
        st.session_state[key + EditorSuffix.PROTECTION_ERROR] = str(error)
        return
    st.session_state.pop(key + EditorSuffix.PROTECTION_ERROR, None)
    if st.session_state.get(key + EditorSuffix.COPY) == target:
        return
    forget(key, retire_origin=False)
    st.session_state[key + EditorSuffix.COPY] = target


def other_copies(key, folder, load, t):
    if error := st.session_state.get(key + EditorSuffix.PROTECTION_ERROR):
        st.error(t("Could not protect unsaved edits: {error}", error=error))
    current = {
        st.session_state.get(key + EditorSuffix.COPY),
        st.session_state.get(key + EditorSuffix.ORIGIN_COPY),
    }
    others = [path for path in copies(folder) if path not in current]
    if others:
        with st.expander(t("Other unsaved copies")):
            for path in others:
                try:
                    snapshot = json.loads(path.read_text(encoding="utf-8"))
                except FileNotFoundError:
                    continue
                st.text(f"r{snapshot['revision']} · {str(snapshot['content'])[:140]}")
                st.button(
                    t("Restore this copy"),
                    key=key + ":restore:" + path.stem,
                    on_click=load,
                    args=(path,),
                )


def patch_field(content, path, value):
    parent = content
    for part in path[:-1]:
        parent = parent[part]
    parent[path[-1]] = value
    if len(path) == 4 and path[0] == "slides" and path[-1] == "headers":
        width = len(value)
        parent["rows"] = [(row + [""] * width)[:width] for row in parent["rows"]]
    return content


closing_field = st.components.v2.component(
    "brofessor_closing_field",
    js=files("brofessor.interfaces.web")
    .joinpath("assets", "closing_field.js")
    .read_text(encoding="utf-8"),
)


def watch_closing_field(key, folder, revision, content, fields, load):
    component_key = key + ":closing-field"
    received = st.session_state.setdefault(key + ":received", [])

    def recover():
        event: ClosingFieldEvent = st.session_state[component_key].recover
        if event["id"] in received:
            return
        base = event["content"]
        value = event["text"]
        if event["path"]:
            data = json.loads(base) if isinstance(base, str) else dict(base)
            if event["lines"]:
                value = (
                    value.split("\n")
                    if "rows" in event["path"]
                    else [line.strip() for line in value.splitlines() if line.strip()]
                )
            value = patch_field(data, event["path"], value)
            if isinstance(base, str):
                value = json.dumps(value, ensure_ascii=False, indent=2)
        parts = event["path"]
        item = parts[1] if parts and parts[0] in ("slides", "turns", "blocks") else None
        path = write_copy(folder, event["revision"], value, item=item)
        if revision == event["revision"] and content == base:
            if st.session_state.get(key + EditorSuffix.COPY) != path:
                forget(key)
        load(path)
        received.append(event["id"])

    closing_field(
        key=component_key,
        data=dict(
            key=key,
            received=received,
            revision=revision,
            content=content,
            fields=fields,
            storage_prefix=CLOSING_FIELD_STORAGE_PREFIX,
            trigger_name=RECOVER_TRIGGER_NAME,
        ),
        on_recover_change=recover,
        height=0,
    )


def note_buffer(workspace, key, note_id, data, revision, t):
    folder = workspace.path / RECOVERY_DIRECTORY / ("note-" + note_id)

    def load(path):
        copy = restore(key, path)
        if copy is None:
            return False
        content = copy["content"]
        st.session_state[key + EditorSuffix.REVISION] = copy["revision"]
        for name in ("title", "text", "citations"):
            st.session_state[key + ":" + name] = content[name]
        st.session_state[key + EditorSuffix.EDITING] = True
        return True

    if key + EditorSuffix.REVISION not in st.session_state:
        available = copies(folder)
        if not available or not load(available[0]):
            st.session_state[key + EditorSuffix.REVISION] = revision
            for name in ("title", "text", "citations"):
                st.session_state[key + ":" + name] = data[name]
    if st.session_state.get(key + EditorSuffix.RECOVERED):
        st.info(t("Recovered unsaved changes."))
    other_copies(key, folder, load, t)

    def content():
        return {name: st.session_state[key + ":" + name] for name in ("title", "text", "citations")}

    def changed():
        value = content()
        if value == data and revision == st.session_state[key + EditorSuffix.REVISION]:
            forget(key)
        else:
            protect(key, folder, st.session_state[key + EditorSuffix.REVISION], value)

    fields = {
        key + ":" + name: dict(path=[name], value=value, lines=False)
        for name, value in content().items()
        if name in ("title", "text")
    }
    watch_closing_field(
        key, folder, st.session_state[key + EditorSuffix.REVISION], content(), fields, load
    )
    return changed
