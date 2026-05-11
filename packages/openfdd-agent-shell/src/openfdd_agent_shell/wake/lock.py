from __future__ import annotations

import os
import time
from contextlib import contextmanager
from pathlib import Path


class WakeLockError(RuntimeError):
    pass


def _create_lock_file(path: Path) -> bool:
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(f"pid={os.getpid()}\n")
    return True


@contextmanager
def wake_lock(path: Path, *, stale_seconds: int = 6 * 3600):
    path.parent.mkdir(parents=True, exist_ok=True)
    while True:
        if _create_lock_file(path):
            break
        age = time.time() - path.stat().st_mtime
        if age < stale_seconds:
            raise WakeLockError(f"wake lock busy: {path}")
        path.unlink(missing_ok=True)
    try:
        yield
    finally:
        path.unlink(missing_ok=True)
