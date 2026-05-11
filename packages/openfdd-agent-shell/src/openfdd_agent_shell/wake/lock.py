from __future__ import annotations

import os
import time
from contextlib import contextmanager
from pathlib import Path


class WakeLockError(RuntimeError):
    pass


@contextmanager
def wake_lock(path: Path, *, stale_seconds: int = 6 * 3600):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        age = time.time() - path.stat().st_mtime
        if age < stale_seconds:
            raise WakeLockError(f"wake lock busy: {path}")
        path.unlink(missing_ok=True)
    path.write_text(f"pid={os.getpid()}\n", encoding="utf-8")
    try:
        yield
    finally:
        path.unlink(missing_ok=True)
