#!/usr/bin/env python3
"""
Schedule-aware monitor for the Open-FDD fake BACnet test bench.

Why this exists
---------------
A raw point spike (for example SA-T = 180.0 F) is not automatically a bug on this bench.
The fake AHU and VAV devices intentionally drive scheduled fault windows from
fake_bacnet_devices/fault_schedule.py:

- UTC minute 10-49  -> flatline window
- UTC minute 50-54  -> out-of-bounds window (180.0 F)

This helper reads the current schedule, samples the BACnet-side values directly through
DIY BACnet JSON-RPC, and explains whether the observed values look aligned with the
intended fake-device behavior.

It is meant to help humans and OpenClaw clones answer:
- is the 180 F spike expected right now?
- are we in normal / flatline / bounds mode?
- do the fake devices appear aligned with their documented schedule?
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
FAKE_DIR = REPO_ROOT / "fake_bacnet_devices"
DEFAULT_BACNET_URL = "http://192.168.204.16:8080"


@dataclass(frozen=True)
class PointSpec:
    label: str
    device_instance: int
    object_identifier: str
    expected_normal_min: float | None = None
    expected_normal_max: float | None = None


POINTS: list[PointSpec] = [
    PointSpec("SA-T", 3456789, "analog-input,2", 53.0, 72.0),
    PointSpec("RA-T", 3456789, "analog-input,4", 65.0, 75.0),
    PointSpec("MA-T", 3456789, "analog-input,3", 65.0, 75.0),
    PointSpec("ZoneTemp", 3456790, "analog-input,1", 60.0, 80.0),
]


def _load_fault_schedule_module():
    path = FAKE_DIR / "fault_schedule.py"
    spec = importlib.util.spec_from_file_location("fault_schedule", path)
    if not spec or not spec.loader:
        raise RuntimeError(f"Could not load fault schedule module from {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def rpc_read_property(base_url: str, device_instance: int, object_identifier: str) -> float:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "client_read_property",
        "params": {
            "request": {
                "device_instance": device_instance,
                "object_identifier": object_identifier,
                "property_identifier": "present-value",
            }
        },
    }
    r = requests.post(f"{base_url.rstrip('/')}/client_read_property", json=payload, timeout=20)
    r.raise_for_status()
    try:
        body = r.json()
    except json.JSONDecodeError as e:
        raise ValueError(
            f"BACnet RPC returned non-JSON (HTTP {r.status_code}): {r.text[:300]!r}"
        ) from e
    if not isinstance(body, dict):
        raise ValueError(f"BACnet RPC JSON root must be object, got {type(body).__name__}")
    res = body.get("result")
    if not isinstance(res, dict) or "present-value" not in res:
        raise ValueError(
            f"BACnet RPC missing result.present-value (HTTP {r.status_code}): {body!r}"
        )
    try:
        return float(res["present-value"])
    except (TypeError, ValueError) as e:
        raise ValueError(f"present-value not numeric: {res.get('present-value')!r}") from e


def judge_value(
    point: PointSpec,
    mode: str,
    current: float,
    previous: float | None,
    out_of_bounds_value: float,
) -> tuple[str, str]:
    if mode == "bounds":
        if abs(current - out_of_bounds_value) < 0.001:
            return "PASS", f"matches scheduled bounds value {out_of_bounds_value:.1f} F"
        return "FAIL", f"expected scheduled bounds value {out_of_bounds_value:.1f} F but saw {current:.3f}"

    if mode == "flatline":
        if previous is None:
            return "INFO", "flatline mode; need a second sample to confirm held value"
        if abs(current - previous) < 0.001:
            return "PASS", f"held constant across samples ({current:.3f}) as expected for flatline"
        return "WARN", f"expected flatline but value changed from {previous:.3f} to {current:.3f}"

    # normal
    if point.expected_normal_min is not None and point.expected_normal_max is not None:
        if point.expected_normal_min <= current <= point.expected_normal_max:
            return "PASS", f"within rough normal bench band {point.expected_normal_min:.1f}-{point.expected_normal_max:.1f}"
        if abs(current - out_of_bounds_value) < 0.001:
            return "WARN", "still at out-of-bounds marker outside scheduled bounds window"
        return "WARN", f"outside rough normal bench band {point.expected_normal_min:.1f}-{point.expected_normal_max:.1f}"
    return "INFO", "no normal range heuristic defined"


def main() -> int:
    parser = argparse.ArgumentParser(description="Monitor the fake BACnet fault schedule on the Open-FDD test bench.")
    parser.add_argument("--bacnet-url", default=DEFAULT_BACNET_URL, help="DIY BACnet JSON-RPC base URL")
    parser.add_argument("--second-sample-delay", type=float, default=3.0, help="Seconds to wait before the second sample")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of human-readable text")
    args = parser.parse_args()

    sched = _load_fault_schedule_module()
    oob = float(sched.OUT_OF_BOUNDS_VALUE)
    now_utc = datetime.now(timezone.utc)
    minute = now_utc.minute
    mode = sched.scheduled_mode(minute)

    rows: list[dict[str, Any]] = []
    first_by_point: list[float] = []
    for point in POINTS:
        first_by_point.append(
            rpc_read_property(args.bacnet_url, point.device_instance, point.object_identifier)
        )
    second_by_point: list[float | None] = [None] * len(POINTS)
    if mode == "flatline":
        time.sleep(args.second_sample_delay)
        for i, point in enumerate(POINTS):
            second_by_point[i] = rpc_read_property(
                args.bacnet_url, point.device_instance, point.object_identifier
            )

    for i, point in enumerate(POINTS):
        first = first_by_point[i]
        second = second_by_point[i]
        status, note = judge_value(
            point,
            mode,
            second if second is not None else first,
            first if second is not None else None,
            oob,
        )
        rows.append(
            {
                "point": point.label,
                "device_instance": point.device_instance,
                "object_identifier": point.object_identifier,
                "mode": mode,
                "first_value": first,
                "second_value": second,
                "status": status,
                "note": note,
            }
        )

    payload = {
        "timestamp_utc": now_utc.isoformat(),
        "minute_utc": minute,
        "scheduled_mode": mode,
        "schedule_summary": {
            "normal": "UTC minutes 0-9 and 55-59",
            "flatline": "UTC minutes 10-49",
            "bounds": "UTC minutes 50-54 -> expect 180.0 F on scheduled points",
        },
        "points": rows,
    }

    if args.json:
        print(json.dumps(payload, indent=2))
        return 0

    print(f"UTC time: {payload['timestamp_utc']}")
    print(f"Scheduled mode: {mode} (minute {minute:02d} UTC)")
    print("Expected windows: normal 0-9, flatline 10-49, bounds 50-54, normal 55-59")
    for row in rows:
        line = f"- {row['point']}: {row['status']} value={row['first_value']:.3f}"
        if row['second_value'] is not None:
            line += f" -> {row['second_value']:.3f}"
        line += f" | {row['note']}"
        print(line)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        raise SystemExit(130) from None
