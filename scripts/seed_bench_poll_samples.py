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


def main() -> int:
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
