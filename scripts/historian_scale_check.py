#!/usr/bin/env python3
"""Cheap deterministic checks for the H10 historian scale qualification assets."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GEN = ROOT / "scripts" / "historian_scale_generate.py"
WORKLOADS = ROOT / "scripts" / "historian_scale_workloads.sql"
EXPECTED_ROLES = {
    "outside_air_temperature",
    "supply_air_temperature",
    "return_air_temperature",
    "supply_fan_status",
    "outside_air_damper_command",
}
EXPECTED_WORKLOADS = {
    "equipment/day",
    "equipment/month",
    "building/hour",
    "monthly aggregation",
    "weather join",
    "representative FDD proof query",
}


def fail(message: str) -> None:
    print(f"FAIL: {message}", file=sys.stderr)
    raise SystemExit(1)


def run_generator(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GEN), *args],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )


def read_jsonl(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            fail(f"{path}:{line_number}: invalid JSON: {exc}")
        if not isinstance(value, dict):
            fail(f"{path}:{line_number}: expected JSON object")
        rows.append(value)
    return rows


def check_determinism(tmp: Path) -> dict[str, object]:
    a = tmp / "a.jsonl"
    b = tmp / "b.jsonl"
    common = [
        "--buildings",
        "1",
        "--equipment-per-building",
        "2",
        "--duration-hours",
        "2",
        "--interval-seconds",
        "300",
        "--seed",
        "42",
    ]
    run_generator(*common, "--output", str(a))
    run_generator(*common, "--output", str(b))
    if a.read_bytes() != b.read_bytes():
        fail("same seed/config did not produce byte-identical JSONL")

    rows = read_jsonl(a)
    if len(rows) != 48:
        fail(f"2 equipment x 2 hours x 12 samples/hour should be 48 rows, got {len(rows)}")
    for row in rows:
        roles = row.get("roles")
        if not isinstance(roles, dict) or set(roles) != EXPECTED_ROLES:
            fail(f"unexpected role set: {roles!r}")
        if row.get("building_id") != "building-0001":
            fail(f"unexpected building id: {row.get('building_id')!r}")
    equipment = sorted({str(row.get("equipment_id")) for row in rows})
    if equipment != ["ahu-00001", "ahu-00002"]:
        fail(f"unexpected equipment ids: {equipment}")
    return {"rows": len(rows), "equipment": equipment}


def check_incremental_append(tmp: Path) -> dict[str, object]:
    out = tmp / "append.jsonl"
    common = [
        "--buildings",
        "1",
        "--equipment-per-building",
        "1",
        "--duration-hours",
        "1",
        "--interval-seconds",
        "300",
        "--seed",
        "7",
        "--output",
        str(out),
    ]
    run_generator(*common, "--offset-hours", "0")
    run_generator(*common, "--offset-hours", "1", "--append")
    rows = read_jsonl(out)
    if len(rows) != 24:
        fail(f"two appended one-hour chunks should be 24 rows, got {len(rows)}")
    timestamps = [str(row.get("timestamp_utc")) for row in rows]
    if len(set(timestamps)) != len(timestamps):
        fail("incremental chunks overlapped timestamps unexpectedly")
    if timestamps != sorted(timestamps):
        fail("incremental append is not monotonic")
    return {"rows": len(rows), "first": timestamps[0], "last": timestamps[-1]}


def check_workloads() -> dict[str, object]:
    if not WORKLOADS.is_file():
        fail(f"missing workload suite: {WORKLOADS}")
    text = WORKLOADS.read_text(encoding="utf-8")
    found = {
        line.split(":", 1)[1].strip()
        for line in text.splitlines()
        if line.startswith("-- workload:")
    }
    missing = EXPECTED_WORKLOADS - found
    if missing:
        fail(f"workload suite missing markers: {sorted(missing)}")
    required_fragments = [
        "building_id = 'building-0001'",
        "equipment_id = 'ahu-00001'",
        "year = '2026'",
        "month = '01'",
        "timestamp_utc >=",
        "timestamp_utc <",
        "JOIN weather",
    ]
    for fragment in required_fragments:
        if fragment not in text:
            fail(f"workload suite missing selective/pruning fragment: {fragment}")
    return {"workloads": sorted(found)}


def main() -> int:
    if not GEN.is_file():
        fail(f"missing generator: {GEN}")
    with tempfile.TemporaryDirectory(prefix="openfdd-h10-") as raw_tmp:
        tmp = Path(raw_tmp)
        summary = {
            "determinism": check_determinism(tmp),
            "incremental_append": check_incremental_append(tmp),
            "workload_suite": check_workloads(),
        }
    print(json.dumps(summary, indent=2, sort_keys=True))
    print("PASS: H10 historian scale assets are deterministic and self-consistent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
