#!/usr/bin/env python3
"""Seed synthetic BACnet poll CSV for bench device 5007 when OT poll is unavailable."""

from __future__ import annotations

import csv
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "workspace" / "api"))
os.environ.setdefault("OPENFDD_REPO_ROOT", str(REPO))
os.environ.setdefault("OPENFDD_WORKSPACE_DIR", str(REPO / "workspace"))
os.environ.setdefault("OFDD_DESKTOP_DATA_DIR", str(REPO / "workspace" / "data"))

POINTS = [
    ("5007-analog-input-1173", "1173", "degrees-fahrenheit", 70.0, 0.5, 8),
    ("5007-analog-input-10014", "10014", "degrees-fahrenheit", 72.0, 0.3, 6),
    ("5007-analog-input-1192", "1192", "degrees-fahrenheit", 53.0, 0.2, 5),
    ("5007-analog-input-1168", "1168", "percent-relative-humidity", 45.0, 0.5, 4),
]

FIELDNAMES = [
    "timestamp_utc",
    "site_id",
    "building_id",
    "system_id",
    "point_id",
    "series_id",
    "device_instance",
    "object_type",
    "object_instance",
    "value",
    "units",
]


def append_live_tick(*, poll_path: Path | None = None) -> dict:
    """Append one 1-minute sample row per bench 5007 point (OT fallback)."""
    poll = poll_path or (REPO / "workspace" / "bacnet" / "polls" / "samples.csv")
    poll.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    minute = int(now.timestamp() // 60)
    rows: list[dict[str, str]] = []
    for pid, inst, units, base, step, mod in POINTS:
        rows.append(
            {
                "timestamp_utc": now.isoformat(),
                "site_id": "demo",
                "building_id": "bens-office",
                "system_id": "unknown",
                "point_id": pid,
                "series_id": "x",
                "device_instance": "5007",
                "object_type": "analog-input",
                "object_instance": inst,
                "value": str(base + (minute % mod) * step),
                "units": units,
            }
        )
    write_header = not poll.is_file() or poll.stat().st_size == 0
    with poll.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES)
        if write_header:
            w.writeheader()
        w.writerows(rows)
    from openfdd_bridge.bacnet_poll_ingest import ingest_poll_samples_to_feather

    ingest = ingest_poll_samples_to_feather()
    return {"ok": True, "timestamp_utc": now.isoformat(), "rows_appended": len(rows), "ingest": ingest}


def main() -> int:
    if os.environ.get("OPENFDD_BENCH_POLL_TICK") == "1" or "--tick" in sys.argv:
        result = append_live_tick()
        print(result)
        return 0 if result.get("ok") else 1
    poll = REPO / "workspace" / "bacnet" / "polls" / "samples.csv"
    poll.parent.mkdir(parents=True, exist_ok=True)
    if poll.is_file() and poll.stat().st_size > 500 and os.environ.get("OPENFDD_FORCE_RESEED") != "1":
        print(f"keep existing {poll} ({poll.stat().st_size} bytes)")
    else:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        rows: list[dict[str, str]] = []
        for i in range(96):
            ts = (now - timedelta(hours=96 - i)).isoformat()
            for pid, inst, units, base, step, mod in POINTS:
                rows.append(
                    {
                        "timestamp_utc": ts,
                        "site_id": "demo",
                        "building_id": "bens-office",
                        "system_id": "unknown",
                        "point_id": pid,
                        "series_id": "x",
                        "device_instance": "5007",
                        "object_type": "analog-input",
                        "object_instance": inst,
                        "value": str(base + (i % mod) * step),
                        "units": units,
                    }
                )
        with poll.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        print(f"seeded {len(rows)} rows → {poll}")

    from openfdd_bridge.bacnet_poll_ingest import ingest_poll_samples_to_feather

    result = ingest_poll_samples_to_feather(force_full=True)
    print(result)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
