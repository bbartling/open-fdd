#!/usr/bin/env python3
"""Merge discovery-enabled BACnet points missing from points.csv (poll driver list)."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

FIELDNAMES = [
    "device_instance",
    "device_address",
    "object_type",
    "object_instance",
    "object_name",
    "description",
    "present_value",
    "units",
    "site_id",
    "building_id",
    "system_id",
    "brick_class",
    "brick_tag",
    "enabled",
    "poll_interval_s",
    "point_id",
    "series_id",
]


def _truthy(v: str) -> bool:
    return str(v or "").strip().lower() in ("1", "true", "yes", "y", "on")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--commission-dir", type=Path, required=True)
    ap.add_argument("--poll-interval", type=int, default=60)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    comm = args.commission_dir
    points_path = comm / "points.csv"
    disc_path = comm / "points_discovered.csv"
    if not disc_path.is_file():
        print(f"missing {disc_path}", file=sys.stderr)
        return 1

    existing: dict[str, dict[str, str]] = {}
    if points_path.is_file():
        with points_path.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                pid = str(row.get("point_id") or "").strip()
                if pid:
                    existing[pid] = dict(row)

    added = 0
    with disc_path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if not _truthy(str(row.get("enabled") or "")):
                continue
            pid = str(row.get("point_id") or "").strip()
            if not pid or pid in existing:
                continue
            out = {k: str(row.get(k) or "") for k in FIELDNAMES}
            out["enabled"] = "1"
            out["poll_interval_s"] = str(args.poll_interval)
            existing[pid] = out
            added += 1

    rows = sorted(existing.values(), key=lambda r: (r.get("device_instance", ""), r.get("point_id", "")))
    print(f"points.csv total={len(rows)} added_from_discovery={added}")
    if args.dry_run:
        return 0

    points_path.parent.mkdir(parents=True, exist_ok=True)
    with points_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDNAMES, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
