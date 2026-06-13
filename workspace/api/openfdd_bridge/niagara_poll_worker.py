"""Background Niagara poll worker (optional, non-blocking startup)."""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from typing import Any

_log = logging.getLogger(__name__)
_worker: threading.Thread | None = None
_started = False
_loop: asyncio.AbstractEventLoop | None = None


def _stations_due() -> list[dict[str, Any]]:
    from .niagara_store import _POLL_ENABLED, list_stations

    due: list[dict[str, Any]] = []
    now = time.time()
    for station in list_stations():
        sid = str(station.get("id"))
        if not _POLL_ENABLED.get(sid):
            continue
        if not station.get("enabled"):
            continue
        interval = max(15, int(station.get("poll_interval_seconds") or 60))
        last = _poll_last_run.get(sid, 0)
        if now - last >= interval:
            due.append(station)
    return due


_poll_last_run: dict[str, float] = {}


async def _poll_cycle_async() -> dict[str, Any]:
    from .niagara_service import poll_station_once

    results: list[dict[str, Any]] = []
    for station in _stations_due():
        sid = str(station["id"])
        try:
            out = await poll_station_once(sid, persistent=True)
            results.append(out)
            _poll_last_run[sid] = time.time()
        except Exception as exc:
            _log.warning("niagara poll failed for %s: %s", sid, exc)
            results.append({"station_id": sid, "error": str(exc)[:200]})
    return {"polled": len(results), "results": results}


def _loop_main() -> None:
    global _loop
    _loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_loop)
    while True:
        try:
            result = _loop.run_until_complete(_poll_cycle_async())
            if int(result.get("polled") or 0) > 0:
                _log.info("niagara poll cycle: polled=%s", result.get("polled"))
        except Exception as exc:
            _log.warning("niagara poll worker failed: %s", exc)
        time.sleep(5.0)


def start_niagara_poll_worker() -> None:
    global _worker, _started
    if _started:
        return
    if os.environ.get("OFDD_DISABLE_NIAGARA_POLL_WORKER", "").strip().lower() in {"1", "true", "yes"}:
        return
    try:
        import aiohttp  # noqa: F401
    except ImportError:
        _log.info("Niagara poll worker skipped — aiohttp not installed")
        return
    _started = True
    _worker = threading.Thread(target=_loop_main, name="niagara-poll-worker", daemon=True)
    _worker.start()
    _log.info("Niagara poll worker started")
