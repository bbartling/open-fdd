"""Rotate supervisory override scans — one BACnet device per interval (default 1 hour)."""

from __future__ import annotations

import sys
import threading
import time
from typing import Any, Callable

from bacnet_toolshed.bacnet_io_priority import BacnetIoInterrupted
from bacnet_toolshed.bacnet_ops import supervisory_logic_check
from bacnet_toolshed.override_registry import (
    advance_cursor,
    list_devices_for_scan,
    record_scan_error,
    save_device_scan,
    scan_interval_s,
    scan_status,
)

_scan_thread: threading.Thread | None = None


def run_override_scan_cycle(run_bacnet_sync: Callable[..., Any]) -> dict[str, Any]:
    """Scan exactly one device in the rotation (background BACnet priority)."""
    devices = list_devices_for_scan()
    if not devices:
        return {**scan_status(), "samples": 0, "scanned_device": None, "error": ""}
    cursor = int(scan_status().get("cursor") or 0)
    dev = devices[cursor % len(devices)]
    inst = int(dev["device_instance"])
    addr = str(dev.get("device_address") or "").strip()
    try:

        async def _run(app) -> dict[str, Any]:
            return await supervisory_logic_check(app, inst, device_address=addr or None)

        result = run_bacnet_sync(_run)
        save_device_scan(result)
        advance_cursor(len(devices))
        summary = result.get("summary") or {}
        return {
            **scan_status(),
            "ok": True,
            "scanned_device": inst,
            "override_points": int(summary.get("points_with_override_count") or 0),
            "error": "",
        }
    except BacnetIoInterrupted:
        return {
            **scan_status(),
            "ok": True,
            "scanned_device": None,
            "interrupted": True,
            "error": "interrupted for operator request",
        }
    except Exception as exc:
        record_scan_error(device_instance=inst, device_address=addr, error=str(exc))
        advance_cursor(len(devices))
        print(f"BACnet override scan failed for {inst}: {exc}", file=sys.stderr)
        return {
            **scan_status(),
            "ok": False,
            "scanned_device": inst,
            "error": str(exc)[:500],
        }


def _override_scan_loop(run_bacnet_sync: Callable[..., Any]) -> None:
    # Stagger start so we do not collide with poll loop boot.
    time.sleep(45.0)
    while True:
        interval = scan_interval_s()
        if list_devices_for_scan():
            run_override_scan_cycle(run_bacnet_sync)
        time.sleep(interval)


def start_override_scan_loop(run_bacnet_sync: Callable[..., Any]) -> None:
    global _scan_thread
    if _scan_thread is not None and _scan_thread.is_alive():
        return
    _scan_thread = threading.Thread(
        target=_override_scan_loop,
        args=(run_bacnet_sync,),
        name="bacnet-override-scan",
        daemon=True,
    )
    _scan_thread.start()
