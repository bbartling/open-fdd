"""
Merge per-device point CSVs into one commissioning file.

  python -m bacnet_toolshed.merge_points_csv \\
    --input-dir workspace/bacnet/commissioning/points_per_device \\
    -o workspace/bacnet/commissioning/points_discovered.csv
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from bacnet_toolshed.config import CSV_FIELDNAMES, normalize_row


def _device_instance_key(path: Path) -> int:
    stem = path.stem
    if stem.startswith("device_"):
        try:
            return int(stem.split("_", 1)[1])
        except ValueError:
            pass
    return -1


def merge_points_dir(
    input_dir: Path,
    output: Path,
    *,
    enabled_only: bool = False,
    pattern: str = "device_*.csv",
) -> int:
    files = sorted(input_dir.glob(pattern), key=_device_instance_key, reverse=True)
    if not files:
        sys.stderr.write(f"No files matching {pattern} in {input_dir}\n")
        return 1

    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for path in files:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for raw in reader:
                if not raw.get("device_instance") or not raw.get("object_type"):
                    continue
                row = normalize_row(raw)
                if enabled_only and row.get("enabled", "0") not in ("1", "true", "yes"):
                    continue
                pid = row.get("point_id") or ""
                if pid and pid in seen:
                    continue
                if pid:
                    seen.add(pid)
                rows.append(row)

    rows.sort(
        key=lambda r: (
            -int(r["device_instance"] or 0),
            r.get("object_type", ""),
            int(r.get("object_instance") or 0),
        )
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    sys.stderr.write(f"Merged {len(rows)} rows from {len(files)} file(s) → {output}\n")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge per-device point CSVs")
    parser.add_argument("--input-dir", required=True, type=Path)
    parser.add_argument("-o", "--output", required=True, type=Path)
    parser.add_argument("--enabled-only", action="store_true")
    parser.add_argument("--pattern", default="device_*.csv")
    args = parser.parse_args()
    if not args.input_dir.is_dir():
        sys.stderr.write(f"Not a directory: {args.input_dir}\n")
        sys.exit(1)
    rc = merge_points_dir(
        args.input_dir,
        args.output,
        enabled_only=args.enabled_only,
        pattern=args.pattern,
    )
    sys.exit(rc)


if __name__ == "__main__":
    main()
