"""
Enable/disable points in a commissioning CSV (sets enabled=1 and optional brick_class).

  python -m bacnet_toolshed.enable_points \\
    --input workspace/bacnet/commissioning/points_discovered.csv \\
    --output workspace/bacnet/commissioning/points.csv \\
    --all
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from bacnet_toolshed.config import CSV_FIELDNAMES, normalize_row


def main() -> None:
    parser = argparse.ArgumentParser(description="Enable BACnet points in commissioning CSV")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--all", action="store_true", help="Enable every row")
    parser.add_argument(
        "--match",
        action="append",
        default=[],
        help="Enable rows whose point_id or object_name contains this substring (repeatable)",
    )
    parser.add_argument(
        "--object-instance",
        action="append",
        default=[],
        help="Enable exact BACnet object (repeatable), e.g. analog-input,1168",
    )
    parser.add_argument("--poll-interval", type=int, default=60)
    args = parser.parse_args()

    if not args.input.is_file():
        sys.stderr.write(f"Missing input: {args.input}\n")
        sys.exit(1)

    rows: list[dict[str, str]] = []
    enabled_count = 0
    with args.input.open(newline="", encoding="utf-8") as f:
        for raw in csv.DictReader(f):
            row = normalize_row(raw)
            enable = args.all
            if not enable and args.object_instance:
                oid = f"{row.get('object_type', '')},{row.get('object_instance', '')}".lower()
                enable = any(m.strip().lower() == oid for m in args.object_instance)
            if not enable and args.match:
                hay = f"{row.get('point_id','')} {row.get('object_name','')}".lower()
                enable = any(m.lower() in hay for m in args.match)
            if enable:
                row["enabled"] = "1"
                row["poll_interval_s"] = str(args.poll_interval)
                enabled_count += 1
            rows.append(row)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    sys.stderr.write(
        f"Wrote {len(rows)} rows ({enabled_count} enabled) → {args.output}\n"
    )


if __name__ == "__main__":
    main()
