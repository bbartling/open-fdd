#!/usr/bin/env python3
"""Compare fdd_cli run-rules JSON against expected_faults_slice.csv."""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

TOL = 0.15
ALIASES = {"FC13": ["FC13-SAT-HIGH", "FC13"]}


def hours_from_result(path: Path, equipment_id: str) -> float | None:
    if not path.is_file():
        return None
    body = json.loads(path.read_text())
    rows = body.get("rows") or []
    best = None
    for r in rows:
        if not isinstance(r, dict):
            continue
        eq = str(r.get("equipment_id") or "")
        if eq and eq != equipment_id:
            continue
        for key in ("fault_hours", "confirmed_fault_hours"):
            v = r.get(key)
            if v is None:
                continue
            try:
                best = float(v)
            except (TypeError, ValueError):
                continue
    return best


def main() -> int:
    expected = Path(sys.argv[1])
    results_dir = Path(sys.argv[2])
    rows = list(csv.DictReader(expected.open()))
    failed = []
    for row in rows:
        rid = row["rule_id"]
        eq = row["equipment_id"]
        want = float(row["expected_fault_hours"])
        names = ALIASES.get(rid, [rid])
        got = None
        used = rid
        for name in names:
            p = results_dir / f"{name}.json"
            got = hours_from_result(p, eq)
            if got is not None:
                used = name
                break
        ok = got is not None and abs(got - want) <= TOL
        print(f"{rid}/{eq}: want={want} got={got} file={used} {'OK' if ok else 'FAIL'}")
        if not ok:
            failed.append(rid)
    if failed:
        print("FAILED", failed)
        return 1
    print(f"OK {len(rows)} pairs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
