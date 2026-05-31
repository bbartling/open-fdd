"""Background poll ingest worker — triggers commission poll + feather ingest."""

from __future__ import annotations

import logging
import os
import threading
import time

from .bacnet_poll_ingest import ingest_poll_samples_to_feather
from .paths import bacnet_poll_csv

_log = logging.getLogger(__name__)

_worker: threading.Thread | None = None
_started = False
_last_mtime: float = 0.0
_DEFAULT_INTERVAL_S = 30.0


def _poll_ingest_interval_s() -> float:
    raw = os.environ.get("OFDD_POLL_INGEST_INTERVAL_S", "30").strip()
    try:
        return float(raw)
    except ValueError:
        _log.warning("Invalid OFDD_POLL_INGEST_INTERVAL_S=%r — using %.0fs", raw, _DEFAULT_INTERVAL_S)
        return _DEFAULT_INTERVAL_S


def _loop() -> None:
    global _last_mtime
    while True:
        sleep_s = _DEFAULT_INTERVAL_S
        try:
            sleep_s = _poll_ingest_interval_s()
            path = bacnet_poll_csv()
            if path.is_file():
                mtime = path.stat().st_mtime
                if mtime > _last_mtime:
                    _last_mtime = mtime
                    result = ingest_poll_samples_to_feather()
                    if result.get("ok"):
                        _log.info("feather ingest: %s", result.get("sites"))
        except Exception as exc:
            _log.warning("poll ingest worker failed: %s", exc)
        time.sleep(max(10.0, sleep_s))


def start_bacnet_poll_worker() -> None:
    global _worker, _started
    if _started:
        return
    if os.environ.get("OFDD_DISABLE_POLL_WORKER", "").strip().lower() in {"1", "true", "yes"}:
        return
    _started = True
    _worker = threading.Thread(target=_loop, name="bacnet-poll-worker", daemon=True)
    _worker.start()
    _log.info("BACnet poll worker started (commission agent + feather ingest)")
