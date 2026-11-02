"""Pinned local speech models and a shared user cache; no inference during setup."""

import copy
import fcntl
import hashlib
import io
import json
import os
import platform
import shutil
import threading
import time
from functools import lru_cache
from pathlib import Path

import httpx

from . import preferences
from .executors import CancelledError
from .workspace import atomic_json

CATALOG = json.loads(Path(__file__).with_suffix(".json").read_text(encoding="utf-8"))
DEFAULT_ID = "qwen3-0.6b"


def _saved_spec(reference: str) -> Path:
    key = hashlib.sha256(reference.encode()).hexdigest()
    return cache_directory().parent / "specs" / f"{key}.json"


def get(model: str | dict) -> dict:
    if isinstance(model, dict):
        return copy.deepcopy(model)
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


def snapshot(model: dict, cache: Path | None = None) -> Path:
    if "url" in model:
        return cache_directory().parent / "files" / model["id"] / model["revision"]
    return (
        (cache or cache_directory())
        / ("models--" + model["repo"].replace("/", "--"))
        / "snapshots"
        / model["revision"]
    )


def _valid_bytes(model: dict, path: Path) -> int:
    total = 0
    for name, size in model["files"].items():
        file = path / name
        try:
            if file.is_file() and file.stat().st_size == size:
                total += size
        except OSError:
            pass
    return total


def installed_path(model: str | dict) -> Path | None:
    item = get(model)
    if any(installed_path(dependency) is None for dependency in item.get("dependencies", [])):
        return None
    path = snapshot(item)
    if _valid_bytes(item, path) != item["download_bytes"]:
        return None
    if "sha256" in item:
        file = path / next(iter(item["files"]))
        try:
            stat = file.stat()
            digest = _file_digest(file, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
        except OSError:
            return None
        if digest != item["sha256"]:
            return None
    return path


@lru_cache(maxsize=16)
def _file_digest(path, size, mtime_ns, ctime_ns):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def list_models() -> list[dict]:
    apple_silicon = platform.system() == "Darwin" and platform.machine() == "arm64"
    return [
        {
            **{key: value for key, value in item.items() if key != "files"},
            "download_bytes": total_bytes(item),
            "installed": installed_path(item["id"]) is not None,
            "compatible": apple_silicon
            or (item.get("engine") == "silero" and platform.system() == "Linux"),
        }
        for item in CATALOG
    ]


def selected() -> str:
    return preferences.read().get("tts_model", DEFAULT_ID)


def use(model: str) -> dict:
    item = get(model)
    preferences.update(tts_model=item["id"])
    return item


def reference(model: str | None = None) -> str:
    return _reference(get(model or selected()))


def _reference(item: dict) -> str:
    return f"{item.get('repo', item['id'])}@{item['revision']}"


def _legacy_caches() -> list[Path]:
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


def _download_file(item, target, check, report):
    """One checksummed upstream file; Range resumes when the server supports it."""
    filename = next(iter(item["files"]))
    target.mkdir(parents=True, exist_ok=True)
    with (target / ".download.lock").open("a") as lock:
        while True:
            check()
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                time.sleep(0.1)
        if installed_path(item) is not None:
            return
        output = target / filename
        partial = output.with_suffix(output.suffix + ".part")
        offset = partial.stat().st_size if partial.exists() else 0
        if offset == item["download_bytes"]:
            with partial.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            if digest == item["sha256"]:
                check()
                partial.replace(output)
                report(offset)
                return
        if offset >= item["download_bytes"]:
            partial.unlink()
            offset = 0
        headers = {"Range": f"bytes={offset}-"} if offset else {}
        with httpx.stream(
            "GET", item["url"], headers=headers, follow_redirects=True, timeout=30
        ) as response:
            response.raise_for_status()
            resumed = offset and response.status_code == 206
            if response.status_code == 206 and not response.headers.get(
                "content-range", ""
            ).startswith(f"bytes {offset}-"):
                raise RuntimeError("Model server returned an invalid resume range")
            completed = offset if resumed else 0
            with partial.open("ab" if resumed else "wb") as stream:
                for chunk in response.iter_bytes(1024 * 1024):
                    check()
                    completed += len(chunk)
                    if completed > item["download_bytes"]:
                        raise RuntimeError("Model download exceeds its pinned size")
                    stream.write(chunk)
                    report(completed)
        with partial.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if completed != item["download_bytes"] or digest != item["sha256"]:
            partial.unlink()
            raise RuntimeError("Model download does not match its pinned size and SHA-256")
        check()
        partial.replace(output)


def download(model: str | dict, *, cancelled=lambda: False, progress=lambda value: None) -> dict:
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
    model: str | dict, *, cancelled=lambda: False, progress=lambda value: None
) -> dict:
    item = get(model)
    target = snapshot(item)

    def check():
        if cancelled():
            raise CancelledError("TTS model download cancelled; completed files are preserved")

    def report(completed):
        check()
        progress(
            {
                "stage": "downloading_model",
                "model": item["id"],
                "completed": completed,
                "total": item["download_bytes"],
            }
        )

    report(_valid_bytes(item, target))
    if "url" in item and installed_path(item) is None:
        _download_file(item, target, check, report)
    if installed_path(item) is None:
        # Reuse the user's complete legacy snapshots without another download.
        for cache in _legacy_caches():
            legacy = snapshot(item, cache)
            if legacy == target or _valid_bytes(item, legacy) != item["download_bytes"]:
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
                        os.link((legacy / name).resolve(), temporary)
                    except OSError:
                        shutil.copyfile(legacy / name, temporary)
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
        **({"repo": item["repo"]} if "repo" in item else {"url": item["url"]}),
        "revision": item["revision"],
        "path": str(target),
    }
