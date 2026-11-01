"""Pinned local speech models and a shared user cache; no inference during setup."""

import io
import json
import os
import platform
import shutil
import threading
import time
from pathlib import Path

from . import preferences
from .executors import CancelledError

CATALOG = json.loads(Path(__file__).with_suffix(".json").read_text(encoding="utf-8"))
DEFAULT_ID = "qwen3-0.6b"


def get(model: str) -> dict:
    for item in CATALOG:
        if model in (item["id"], item["repo"], f"{item['repo']}@{item['revision']}"):
            return dict(item)
    raise ValueError("Unknown TTS model. Run tts list to see supported models")


def cache_directory() -> Path:
    return preferences.data_directory() / "models" / "hub"


def snapshot(model: dict, cache: Path | None = None) -> Path:
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


def installed_path(model: str) -> Path | None:
    item = get(model)
    path = snapshot(item)
    return path if _valid_bytes(item, path) == item["download_bytes"] else None


def list_models() -> list[dict]:
    compatible = platform.system() == "Darwin" and platform.machine() == "arm64"
    return [
        {
            **{key: value for key, value in item.items() if key != "files"},
            "installed": installed_path(item["id"]) is not None,
            "compatible": compatible,
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
    choice = model or selected()
    try:
        item = get(choice)
    except ValueError:
        if model is None:
            raise
        return choice  # Preserve the existing repo@revision/local-directory API.
    return f"{item['repo']}@{item['revision']}"


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


def download(model: str, *, cancelled=lambda: False, progress=lambda value: None) -> dict:
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
    if installed_path(model) is None:
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
    if installed_path(model) is None:
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
    if installed_path(model) is None:
        raise RuntimeError("TTS model download is incomplete; retry the download to continue")
    report(item["download_bytes"])
    return {
        "id": item["id"],
        "repo": item["repo"],
        "revision": item["revision"],
        "path": str(target),
    }
