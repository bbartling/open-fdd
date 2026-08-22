#!/usr/bin/env python3
"""Generate deterministic synthetic Open-FDD historian telemetry for H10 scale tests.

The generator intentionally emits a portable JSONL workload rather than writing the
canonical historian directly. Benchmark/qualification harnesses can feed the same
rows through the production ingest/writer path, preserving the H1-H9 storage
contract while keeping the synthetic source deterministic and easy to scale.

Use --duration-hours/--offset-hours/--append to generate repeatable incremental
chunks for continuous-ingest plus rolling-AFDD qualification without regenerating
or rescanning the retained synthetic source.
"""

from __future__ import annotations

import argparse
import json
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator, TextIO

UTC = timezone.utc


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def rows(
    *,
    buildings: int,
    equipment_per_building: int,
    duration_seconds: int,
    interval_seconds: int,
    start: datetime,
    seed: int,
) -> Iterator[dict[str, object]]:
    rng = random.Random(seed)
    sample_count = duration_seconds // interval_seconds
    for building_index in range(buildings):
        building_id = f"building-{building_index + 1:04d}"
        weather_phase = rng.random() * math.tau
        for equipment_index in range(equipment_per_building):
            equipment_id = f"ahu-{equipment_index + 1:05d}"
            equipment_bias = rng.uniform(-1.5, 1.5)
            for sample_index in range(sample_count):
                timestamp = start + timedelta(seconds=sample_index * interval_seconds)
                hour = timestamp.hour + timestamp.minute / 60.0
                daily_wave = math.sin((hour / 24.0) * math.tau + weather_phase)
                oat = 72.0 + 14.0 * daily_wave
                sat = 55.0 + equipment_bias + 0.15 * daily_wave
                rat = 72.0 + equipment_bias + 2.0 * daily_wave
                fan = 1.0 if 6 <= timestamp.hour < 20 else 0.0
                damper = max(0.0, min(100.0, 35.0 + 30.0 * daily_wave))
                yield {
                    "timestamp_utc": timestamp.isoformat().replace("+00:00", "Z"),
                    "building_id": building_id,
                    "equipment_id": equipment_id,
                    "roles": {
                        "outside_air_temperature": round(oat, 4),
                        "supply_air_temperature": round(sat, 4),
                        "return_air_temperature": round(rat, 4),
                        "supply_fan_status": fan,
                        "outside_air_damper_command": round(damper, 4),
                    },
                }


def open_output(path: str, *, append: bool) -> tuple[TextIO, bool]:
    if path == "-":
        if append:
            raise ValueError("--append requires a file --output, not stdout")
        import sys

        return sys.stdout, False
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if append else "w"
    return target.open(mode, encoding="utf-8"), True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--buildings", type=int, default=1)
    parser.add_argument("--equipment-per-building", type=int, default=10)
    parser.add_argument("--days", type=int, default=1)
    parser.add_argument(
        "--duration-hours",
        type=int,
        help="override --days with an exact chunk duration in hours",
    )
    parser.add_argument(
        "--offset-hours",
        type=int,
        default=0,
        help="advance the requested --start before generating this chunk",
    )
    parser.add_argument("--interval-seconds", type=int, default=300)
    parser.add_argument("--start", default="2026-01-01T00:00:00Z")
    parser.add_argument("--seed", type=int, default=20260822)
    parser.add_argument("--output", default="-")
    parser.add_argument(
        "--append",
        action="store_true",
        help="append this deterministic chunk to an existing JSONL source",
    )
    args = parser.parse_args()

    for name in ("buildings", "equipment_per_building", "days", "interval_seconds"):
        if getattr(args, name) <= 0:
            parser.error(f"--{name.replace('_', '-')} must be > 0")
    if args.duration_hours is not None and args.duration_hours <= 0:
        parser.error("--duration-hours must be > 0")
    if args.offset_hours < 0:
        parser.error("--offset-hours must be >= 0")

    duration_seconds = (
        args.duration_hours * 60 * 60
        if args.duration_hours is not None
        else args.days * 24 * 60 * 60
    )
    if duration_seconds < args.interval_seconds:
        parser.error("duration must include at least one sample interval")

    chunk_start = parse_utc(args.start) + timedelta(hours=args.offset_hours)
    try:
        output, should_close = open_output(args.output, append=args.append)
    except ValueError as exc:
        parser.error(str(exc))

    count = 0
    try:
        for row in rows(
            buildings=args.buildings,
            equipment_per_building=args.equipment_per_building,
            duration_seconds=duration_seconds,
            interval_seconds=args.interval_seconds,
            start=chunk_start,
            seed=args.seed,
        ):
            output.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
            count += 1
    finally:
        if should_close:
            output.close()

    import sys

    chunk_end = chunk_start + timedelta(seconds=duration_seconds)
    print(
        " ".join(
            [
                f"generated_rows={count}",
                f"chunk_start={chunk_start.isoformat()}",
                f"chunk_end={chunk_end.isoformat()}",
                f"append={str(args.append).lower()}",
            ]
        ),
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
