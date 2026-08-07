#!/usr/bin/env python3
"""Sample-level parity debug for one rule/fixture using open_fdd.rules.

Writes JSON under ``.cache/debug/`` (not committed). Replaces the retired
Vibe19 ``cookbook_engine`` path.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fixture", type=Path, required=True)
    ap.add_argument("--rule", required=True)
    ap.add_argument("--equipment-id", default="AHU_1")
    ap.add_argument("--poll-seconds", type=float, default=300.0)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    try:
        import pandas as pd
        from open_fdd.rules import run_rule
    except ImportError as e:
        print(f"FAIL: need open-fdd[oracle]: {e}", file=sys.stderr)
        return 2

    hist = args.fixture / "history_wide.csv"
    df = pd.read_csv(hist)
    ts = pd.to_datetime(df.get("timestamp_utc", df.get("timestamp")), utc=True)
    df = df.copy()
    df.index = ts
    cols = args.fixture / "columns.csv"
    if cols.is_file():
        cmap = pd.read_csv(cols)
        df = df.rename(
            columns={
                str(r.col): str(r.point_role)
                for r in cmap.itertuples()
                if pd.notna(r.col) and pd.notna(r.point_role)
            }
        )
    df.attrs["equipment_id"] = args.equipment_id
    result = run_rule(args.rule, df, poll_seconds=args.poll_seconds)
    out = args.out or Path(".cache/debug") / f"{args.rule}_{args.equipment_id}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "rule_id": args.rule,
        "status": result.status,
        "fault_hours": result.fault_hours,
        "missing_roles": list(result.missing_roles or []),
        "raw_true": int(result.raw_fault.fillna(False).sum())
        if result.raw_fault is not None
        else None,
        "confirmed_true": int(result.confirmed_fault.fillna(False).sum())
        if result.confirmed_fault is not None
        else None,
    }
    out.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
