"""Resource locks shared by all project workers, independent of the project catalog."""

import fcntl
import time
from contextlib import contextmanager
from pathlib import Path

from brofessor.infrastructure.storage import preferences


class ResourceBusy(RuntimeError):
    pass


@contextmanager
def _lock(path, *, exclusive, wait, check, description):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError("A resource lock cannot be a symbolic link")
    with path.open("a+") as handle:
        mode = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        while True:
            if check is not None:
                check()
            try:
                fcntl.flock(handle, mode | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if not wait:
                    raise ResourceBusy(f"{description} is in use; wait for processing to finish")
                time.sleep(0.05)
        try:
            yield handle
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def models_lock(*, exclusive=False, wait=True, check=None):
    return _lock(
        preferences.data_directory() / "locks" / "models.lock",
        exclusive=exclusive,
        wait=wait,
        check=check,
        description="Model storage",
    )


def audio_cache_lock(workspace_or_path, *, exclusive=False, wait=True, check=None):
    path = Path(getattr(workspace_or_path, "path", workspace_or_path)).expanduser().resolve()
    if not path.is_dir():
        raise ValueError("The project folder is unavailable")
    return _lock(
        path / "audio-cache.lock",
        exclusive=exclusive,
        wait=wait,
        check=check,
        description="Project audio cache",
    )
