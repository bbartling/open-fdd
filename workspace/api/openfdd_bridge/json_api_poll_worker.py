"""Background JSON API poll worker."""

from __future__ import annotations

import logging
import os
import threading
import time

from .json_api_store import run_poll_cycle

_log = logging.getLogger(__name__)
_worker: threading.Thread | None = None
_started = False
_TICK_S = 5.0


def _loop() -> None:
    while True:
        try:
            result = run_poll_cycle()
            if int(result.get("polled") or 0) > 0:
                _log.info(
                    "json_api poll cycle: polled=%s samples=%s",
                    result.get("polled"),
                    result.get("samples"),
                )
        except Exception as exc:
            _log.warning("json_api poll worker failed: %s", exc)
        time.sleep(_TICK_S)


def start_json_api_poll_worker() -> None:
    global _worker, _started
    if _started:
        return
    if os.environ.get("OFDD_DISABLE_JSON_API_POLL_WORKER", "").strip().lower() in {"1", "true", "yes"}:
        return
    _started = True
    _worker = threading.Thread(target=_loop, name="json-api-poll-worker", daemon=True)
    _worker.start()
    _log.info("JSON API poll worker started")
