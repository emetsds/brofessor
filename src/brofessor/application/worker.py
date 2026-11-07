"""One independent worker per workspace, owned through a lifetime OS lock."""

import fcntl
import os
import signal
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from typing import Final

from brofessor.contracts.jobs import JobStatus
from brofessor.infrastructure.storage.workspace import Workspace

WORKER_LOCK_FILENAME: Final = "worker.lock"
WORKER_LOG_FILENAME: Final = "worker.log"


@contextmanager
def worker_lock(workspace):
    with (workspace.path / WORKER_LOCK_FILENAME).open("a+") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield None
            return
        try:
            yield handle
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def is_running(workspace: Workspace) -> bool:
    with worker_lock(workspace) as lock:
        return lock is None


def ensure_worker(workspace: Workspace) -> None:
    if is_running(workspace):
        return
    with (workspace.path / WORKER_LOG_FILENAME).open("ab") as output:
        subprocess.Popen(
            [sys.executable, "-m", "brofessor.application.worker", str(workspace.path)],
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=output,
            start_new_session=True,
            close_fds=True,
        )


def run(workspace: Workspace, *, once: bool = False) -> bool:
    from brofessor.application.initial_audio import reconcile
    from brofessor.application.pipeline import execute

    stop = False

    def request_stop(signum, frame):
        nonlocal stop
        stop = True

    old_term = signal.signal(signal.SIGTERM, request_stop)
    old_int = signal.signal(signal.SIGINT, request_stop)
    try:
        with worker_lock(workspace) as lock:
            if lock is None:
                return False
            lock.seek(0)
            lock.truncate()
            lock.write(str(os.getpid()))
            lock.flush()
            workspace.recover()
            reconcile(workspace)
            last_reconcile = time.monotonic()
            while not stop:
                job = workspace.claim()
                if job is None:
                    if time.monotonic() - last_reconcile >= 5:
                        reconcile(workspace)
                        last_reconcile = time.monotonic()
                    if once:
                        break
                    time.sleep(0.3)
                    continue

                def cancelled():
                    return stop or bool(workspace.job(job["id"])["cancel_requested"])

                heartbeat_stop = threading.Event()

                def keep_time():
                    from brofessor.application.progress import heartbeat

                    while not heartbeat_stop.wait(1):
                        try:
                            heartbeat(workspace, job["id"])
                        except OSError:
                            pass

                clock_thread = threading.Thread(target=keep_time, daemon=True)
                clock_thread.start()
                try:
                    execute(workspace, job, cancelled)
                    state = JobStatus.CANCELLED if cancelled() else JobStatus.SUCCEEDED
                    if stop:
                        state = JobStatus.INTERRUPTED
                    workspace.update_job(job["id"], status=state)
                except Exception as error:
                    state = (
                        JobStatus.INTERRUPTED
                        if stop
                        else JobStatus.CANCELLED
                        if cancelled()
                        else JobStatus.FAILED
                    )
                    workspace.update_job(job["id"], status=state, error=str(error)[:1500])
                finally:
                    heartbeat_stop.set()
                    clock_thread.join(timeout=2)
                reconcile(workspace)
                if once:
                    break
            return True
    finally:
        signal.signal(signal.SIGTERM, old_term)
        signal.signal(signal.SIGINT, old_int)


if __name__ == "__main__":
    run(Workspace(sys.argv[1]), once="--once" in sys.argv[2:])
