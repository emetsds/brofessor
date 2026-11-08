"""Pinned local speech models and a shared user cache; no inference during setup."""

import copy
import hashlib
import io
import json
import os
import platform
import shutil
import threading
import time
from importlib.resources import files
from importlib.util import find_spec
from pathlib import Path
from typing import cast


from brofessor.contracts.jobs import StageId
from brofessor.infrastructure.speech.contracts import (
    MODEL_CATALOGUE_FILENAME,
    SpeechModelSpec,
)
from brofessor.infrastructure.storage import preferences
from brofessor.infrastructure.storage.workspace import atomic_json
from brofessor.infrastructure.text.runners import CancelledError

CATALOG: list[SpeechModelSpec] = json.loads(
    files(__package__).joinpath(MODEL_CATALOGUE_FILENAME).read_text(encoding="utf-8")
)
DEFAULT_ID = "qwen3-base"


def _saved_spec(reference: str) -> Path:
    key = hashlib.sha256(reference.encode()).hexdigest()
    return cache_directory().parent / "specs" / f"{key}.json"


def get(model: str | dict | SpeechModelSpec) -> SpeechModelSpec:
    if isinstance(model, dict):
        return cast(SpeechModelSpec, copy.deepcopy(model))
    for item in CATALOG:
        if model in (item["id"], item.get("repo"), _reference(item)):
            return copy.deepcopy(item)
    if "@" in model:
        saved = _saved_spec(model)
        if saved.is_file():
            return json.loads(saved.read_text(encoding="utf-8"))
    raise ValueError("Unknown TTS model. Run tts list to see supported models")


def cache_directory() -> Path:
    return preferences.data_directory() / "models" / "hub"


def snapshot(model: SpeechModelSpec, cache: Path | None = None) -> Path:
    return (
        (cache or cache_directory())
        / ("models--" + model["repo"].replace("/", "--"))
        / "snapshots"
        / model["revision"]
    )


def _valid_bytes(model: SpeechModelSpec, path: Path) -> int:
    total = 0
    for name, size in model["files"].items():
        file = path / name
        try:
            if file.is_file() and file.stat().st_size == size:
                total += size
        except OSError:
            pass
    return total


def installed_path(model: str | dict | SpeechModelSpec) -> Path | None:
    item = get(model)
    if any(installed_path(dependency) is None for dependency in item.get("dependencies", [])):
        return None
    path = snapshot(item)
    if _valid_bytes(item, path) != item["download_bytes"]:
        return None
    return path


def qwen_runtime_available() -> bool:
    """Check the optional local speech extra without loading the model."""
    return find_spec("mlx_audio") is not None


def list_models() -> list[dict]:
    apple_silicon = platform.system() == "Darwin" and platform.machine() == "arm64"
    return [
        {
            **{key: value for key, value in item.items() if key != "files"},
            "download_bytes": total_bytes(item),
            "installed": installed_path(item["id"]) is not None,
            "compatible": apple_silicon,
        }
        for item in CATALOG
    ]


def selected() -> str:
    choice = preferences.read().get("tts_model", DEFAULT_ID)
    supported = {item["id"] for item in CATALOG}
    return choice if choice in supported else DEFAULT_ID


def reference(model: str | dict | SpeechModelSpec | None = None) -> str:
    return _reference(get(model or selected()))


def _reference(item: SpeechModelSpec) -> str:
    return f"{item.get('repo', item['id'])}@{item['revision']}"


def _external_caches() -> list[Path]:
    paths = [Path.home() / ".cache" / "huggingface" / "hub"]
    if value := os.environ.get("HF_HOME"):
        paths.insert(0, Path(value).expanduser() / "hub")
    if value := os.environ.get("HF_HUB_CACHE"):
        paths.insert(0, Path(value).expanduser())
    return paths


def _snapshot_download(**kwargs):
    try:
        from huggingface_hub import snapshot_download
    except ImportError as error:
        raise RuntimeError(
            "Install speech support first: uv sync --extra ui --extra speech"
        ) from error
    return snapshot_download(**kwargs)


def download(
    model: str | dict | SpeechModelSpec, *, cancelled=lambda: False, progress=lambda value: None
) -> dict:
    from brofessor.infrastructure.storage.locks import models_lock

    def check():
        if cancelled():
            raise CancelledError("TTS model download cancelled; completed files are preserved")

    with models_lock(check=check):
        return _download_models(model, cancelled=cancelled, progress=progress)


def _download_models(model, *, cancelled, progress):
    item = get(model)
    total, completed = total_bytes(item), 0
    for component in [*item.get("dependencies", []), item]:

        def report(value):
            progress(
                {
                    **value,
                    "model": item["id"],
                    "completed": completed + value["completed"],
                    "total": total,
                }
            )

        result = _download_one(component, cancelled=cancelled, progress=report)
        completed += component["download_bytes"]
    return result


def total_bytes(item):
    return item["download_bytes"] + sum(
        dep["download_bytes"] for dep in item.get("dependencies", [])
    )


def _download_one(
    model: str | dict | SpeechModelSpec, *, cancelled=lambda: False, progress=lambda value: None
) -> dict:
    item = get(model)
    target = snapshot(item)

    def check():
        if cancelled():
            raise CancelledError("TTS model download cancelled; completed files are preserved")

    def report(completed):
        check()
        if not completed:
            return  # Keep saved progress while the Hub discovers its resume offset.
        progress(
            {
                "stage": StageId.DOWNLOADING_MODEL,
                "model": item["id"],
                "completed": completed,
                "total": item["download_bytes"],
            }
        )

    cached = _valid_bytes(item, target)
    report(cached)
    if installed_path(item) is None:
        # Reuse exact pinned weights from external Hugging Face caches.
        for cache in _external_caches():
            external = snapshot(item, cache)
            if external == target or _valid_bytes(item, external) != item["download_bytes"]:
                continue
            for name, size in item["files"].items():
                check()
                output = target / name
                if output.is_file() and output.stat().st_size == size:
                    continue
                output.parent.mkdir(parents=True, exist_ok=True)
                temporary = output.with_name(output.name + ".importing")
                try:
                    try:
                        os.link((external / name).resolve(), temporary)
                    except OSError:
                        shutil.copyfile(external / name, temporary)
                    temporary.replace(output)
                finally:
                    temporary.unlink(missing_ok=True)
                report(_valid_bytes(item, target))
            break
    if installed_path(item) is None:
        try:
            from huggingface_hub.utils import tqdm
        except ImportError as error:
            raise RuntimeError(
                "Install speech support first: uv sync --extra ui --extra speech"
            ) from error

        lock = threading.Lock()
        last_update = 0.0

        class DownloadProgress(tqdm):
            def __init__(self, *args, **kwargs):
                self.download_name = kwargs.pop("name", "")
                kwargs.update(disable=True, file=io.StringIO())
                super().__init__(*args, **kwargs)

            def update(self, n=1):
                self.n += n or 0
                self.refresh()

            def refresh(self, *args, **kwargs):
                nonlocal last_update
                check()
                if self.download_name != "huggingface_hub.snapshot_download":
                    return
                with lock:
                    if time.monotonic() - last_update >= 0.25:
                        last_update = time.monotonic()
                        report(min(item["download_bytes"], max(self.n, _valid_bytes(item, target))))

        _snapshot_download(
            repo_id=item["repo"],
            revision=item["revision"],
            cache_dir=cache_directory(),
            token=False,
            allow_patterns=list(item["files"]),
            tqdm_class=DownloadProgress,
        )
    check()
    if installed_path(item) is None:
        raise RuntimeError("TTS model download is incomplete; retry the download to continue")
    report(item["download_bytes"])
    atomic_json(_saved_spec(_reference(item)), item)
    return {
        "id": item["id"],
        "repo": item["repo"],
        "revision": item["revision"],
        "path": str(target),
    }
