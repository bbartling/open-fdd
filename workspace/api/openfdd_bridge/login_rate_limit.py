"""In-memory login failure rate limiting (per client IP + username)."""

from __future__ import annotations

import os
import time
from collections import defaultdict
from threading import Lock

_lock = Lock()
_failures: dict[str, list[float]] = defaultdict(list)


def _max_failures() -> int:
    raw = os.environ.get("OFDD_AUTH_MAX_FAILURES", "").strip()
    try:
        return max(1, int(raw)) if raw else 5
    except ValueError:
        return 5


def _failure_window_sec() -> int:
    raw = os.environ.get("OFDD_AUTH_FAILURE_WINDOW_SECONDS", "").strip()
    try:
        return max(60, int(raw)) if raw else 300
    except ValueError:
        return 300


def _lockout_sec() -> int:
    raw = os.environ.get("OFDD_AUTH_LOCKOUT_SECONDS", "").strip()
    try:
        return max(60, int(raw)) if raw else 300
    except ValueError:
        return 300


def _key(ip: str, username: str) -> str:
    return f"{ip.strip()}:{username.strip().lower()}"


def _prune(times: list[float], *, now: float, window: float) -> list[float]:
    cutoff = now - window
    return [t for t in times if t >= cutoff]


def check_lockout(ip: str, username: str) -> tuple[bool, int]:
    """Return (locked_out, retry_after_seconds)."""
    now = time.time()
    window = float(_failure_window_sec())
    max_fail = _max_failures()
    key = _key(ip, username)
    with _lock:
        recent = _prune(_failures.get(key, []), now=now, window=window)
        _failures[key] = recent
        if len(recent) < max_fail:
            return False, 0
        oldest = min(recent)
        retry = int(max(1, _lockout_sec() - (now - oldest)))
        return True, retry


def record_failure(ip: str, username: str) -> int:
    """Record a failed login; return failure count in the current window."""
    now = time.time()
    window = float(_failure_window_sec())
    key = _key(ip, username)
    with _lock:
        recent = _prune(_failures.get(key, []), now=now, window=window)
        recent.append(now)
        _failures[key] = recent
        return len(recent)


def record_success(ip: str, username: str) -> None:
    key = _key(ip, username)
    with _lock:
        _failures.pop(key, None)


def reset_for_tests() -> None:
    with _lock:
        _failures.clear()
