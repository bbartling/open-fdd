"""BACnet RPM polling on the commission agent's shared BACnet stack."""

from __future__ import annotations

import csv
import sys
import threading
import time
from pathlib import Path
from typing import Any

from bacnet_toolshed.config import group_by_device, load_enabled_points, validate_points
from bacnet_toolshed.paths import default_points_enabled, polls_dir
from bacnet_toolshed.poll_driver import poll_once


_poll_thread: threading.Thread | None = None
_poll_lock = threading.Lock()
_last_poll: dict[str, Any] = {"ok": False, "samples": 0, "error": "", "at": ""}


def poll_interval_s() -> float:
    path = default_points_enabled()
    if not path.is_file():
        return 60.0
    intervals: list[int] = []
    try:
        with path.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                if str(row.get("enabled") or "").strip().lower() not in {"1", "true", "yes"}:
                    continue
                try:
                    iv = int(str(row.get("poll_interval_s") or "60"))
                except ValueError:
                    iv = 60
                if iv > 0:
                    intervals.append(iv)
    except OSError:
        pass
    return float(min(intervals)) if intervals else 60.0


def enabled_point_count() -> int:
    path = default_points_enabled()
    if not path.is_file():
        return 0
    try:
        return len(load_enabled_points(path))
    except (OSError, ValueError):
        return 0


def last_poll_status() -> dict[str, Any]:
    with _poll_lock:
        return dict(_last_poll)


def _set_last_poll(**fields: Any) -> None:
    with _poll_lock:
        _last_poll.update(fields)


async def poll_enabled_points(app, *, output_csv: Path | None = None) -> int:
    path = default_points_enabled()
    if not path.is_file():
        return 0
    points = load_enabled_points(path)
    if not points:
        return 0
    errors = validate_points(points)
    if errors:
        raise RuntimeError(errors[0])
    out = output_csv or (polls_dir() / "samples.csv")
    return await poll_once(app, group_by_device(points), output_csv=out, dry_run=False)


def run_poll_cycle(run_bacnet_sync) -> dict[str, Any]:
    """Run one BACnet poll cycle using commission agent BACnet I/O."""
    if enabled_point_count() == 0:
        _set_last_poll(ok=True, samples=0, error="", at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        return last_poll_status()
    try:
        n = run_bacnet_sync(lambda app: poll_enabled_points(app))
        _set_last_poll(ok=True, samples=int(n), error="", at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        _notify_bridge_ingest()
        return last_poll_status()
    except Exception as exc:
        _set_last_poll(
            ok=False,
            samples=0,
            error=str(exc)[:500],
            at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )
        print(f"BACnet poll cycle failed: {exc}", file=sys.stderr)
        return last_poll_status()


def _notify_bridge_ingest() -> None:
    import os
    import urllib.request

    port = os.environ.get("OFDD_BRIDGE_PORT", "8765").strip() or "8765"
    url = f"http://127.0.0.1:{port}/internal/bacnet/ingest-samples"
    try:
        req = urllib.request.Request(url, method="POST", data=b"{}")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=15):
            pass
    except Exception:
        pass


def _poll_loop(run_bacnet_sync) -> None:
    while True:
        interval = max(15.0, poll_interval_s())
        if enabled_point_count() > 0:
            run_poll_cycle(run_bacnet_sync)
        time.sleep(interval)


def start_poll_loop(run_bacnet_sync) -> None:
    global _poll_thread
    if _poll_thread is not None and _poll_thread.is_alive():
        return
    _poll_thread = threading.Thread(
        target=_poll_loop,
        args=(run_bacnet_sync,),
        name="bacnet-poll-loop",
        daemon=True,
    )
    _poll_thread.start()
