"""Private CLI supervisor: EOF on the worker's pipe ends our owned process group.

The guardian remains the live process-group leader until cleanup. It never reads
stored PIDs, discovers user processes, opens credentials, or starts a shell.
A small second pipe reports the CLI exit code before group cleanup kills the
guardian too. The caller accepts it only after the guardian has stopped.
"""

from __future__ import annotations

import contextlib
import os
import select
import signal
import subprocess
import sys
import time


def supervise(lifeline: int, status: int, command: list[str]) -> None:
    if os.getpgrp() != os.getpid():
        raise RuntimeError("Runner guardian must own a fresh process group")
    stopping = False

    def stop(signum, frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    code = None
    child = None
    try:
        child = subprocess.Popen(command, close_fds=True, shell=False)
        while not stopping:
            # Check the lifeline before accepting an exit result. The child cannot
            # keep it alive because neither control descriptor is inherited.
            readable, _, _ = select.select([lifeline], [], [], 0.05)
            if readable and not os.read(lifeline, 1):
                stopping = True
                break
            code = child.poll()
            if code is not None:
                break
    except OSError:
        # Deliberately omit exception text, argv and environment from diagnostics.
        os.write(2, b"Could not start the official CLI from the runner guardian.\n")
        code = 127
    finally:
        # This group identifier cannot be stale: it is our own live session.
        os.killpg(os.getpgrp(), signal.SIGTERM)
        if child is not None:
            with contextlib.suppress(subprocess.TimeoutExpired):
                child.wait(timeout=0.2)
        if code is not None:
            with contextlib.suppress(BrokenPipeError):
                os.write(status, f"{code}\n".encode("ascii"))
        # Give cooperative descendants a short opportunity to finish, then ensure
        # no ignored SIGTERM or orphaned grandchild outlives this operation.
        time.sleep(0.05)
        os.killpg(os.getpgrp(), signal.SIGKILL)


if __name__ == "__main__":
    if len(sys.argv) < 5 or sys.argv[3] != "--":
        raise SystemExit("Private runner guardian: invalid invocation")
    supervise(int(sys.argv[1]), int(sys.argv[2]), sys.argv[4:])
