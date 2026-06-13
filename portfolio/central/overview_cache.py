"""Short TTL cache for slow Edge-backed Central API responses."""

from __future__ import annotations

import os
import time
from threading import Lock
from typing import Any, Callable

_lock = Lock()
_store: dict[str, tuple[float, Any]] = {}


def cache_ttl_seconds() -> int:
    raw = os.environ.get("OPENFDD_OVERVIEW_CACHE_SECS", "180")
    try:
        return max(0, int(raw))
    except ValueError:
        return 180


def get_or_set(key: str, ttl_s: int, builder: Callable[[], Any]) -> tuple[Any, bool]:
    """Return (value, from_cache). ttl_s=0 disables cache."""
    if ttl_s <= 0:
        return builder(), False
    now = time.monotonic()
    with _lock:
        hit = _store.get(key)
        if hit is not None and (now - hit[0]) < ttl_s:
            return hit[1], True
    value = builder()
    with _lock:
        _store[key] = (now, value)
    return value, False


def invalidate_prefix(prefix: str) -> None:
    with _lock:
        for k in list(_store):
            if k.startswith(prefix):
                del _store[k]
