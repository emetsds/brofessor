"""One independent worker per workspace, owned through a lifetime OS lock."""

import fcntl
import os
import signal
import subprocess
import sys
import time
from contextlib import contextmanager

from .workspace import Workspace


@contextmanager
def worker_lock(workspace):
    with (workspace.path / "worker.lock").open("a+") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield None
            return
        try:
            yield handle
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def is_running(workspace):
    with worker_lock(workspace) as lock:
        return lock is None


def ensure_worker(workspace):
    if is_running(workspace):
        return
    with (workspace.path / "worker.log").open("ab") as output:
        subprocess.Popen(
            [sys.executable, "-m", "brofessor.worker", str(workspace.path)],
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=output,
            start_new_session=True,
            close_fds=True,
        )


def run(workspace, *, once=False):
    from .pipeline import execute

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
            while not stop:
                job = workspace.claim()
                if job is None:
                    if once:
                        break
                    time.sleep(0.3)
                    continue

                def cancelled():
                    return stop or bool(workspace.job(job["id"])["cancel_requested"])

                try:
                    execute(workspace, job, cancelled)
                    state = "cancelled" if cancelled() else "succeeded"
                    if stop:
                        state = "interrupted"
                    workspace.update_job(job["id"], status=state)
                except Exception as error:
                    state = "interrupted" if stop else "cancelled" if cancelled() else "failed"
                    workspace.update_job(job["id"], status=state, error=str(error)[:1500])
                if once:
                    break
            return True
    finally:
        signal.signal(signal.SIGTERM, old_term)
        signal.signal(signal.SIGINT, old_int)


if __name__ == "__main__":
    run(Workspace(sys.argv[1]), once="--once" in sys.argv[2:])
