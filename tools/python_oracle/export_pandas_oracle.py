#!/usr/bin/env python3
"""Export pandas oracle metrics for Rust/DataFusion SQL parity comparison.

Wave 0 rewrite: uses ``open_fdd.rules`` (PyPI oracle) only.
Does **not** import removed Vibe19 modules (``cookbook_engine``, ``shared.*``).

Usage (CI / bench)::

    pip install -e '.[oracle]'
    python tools/python_oracle/export_pandas_oracle.py \\
        --fixture crates/fdd_rules/fixtures/oracle/ECON-4/fault \\
        --rule ECON-4 \\
        --out .cache/oracle/ECON-4_fault.json

Product central/web never depends on this script.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _fail(msg: str) -> None:
    print(f"FAIL: {msg}", file=sys.stderr)
    raise SystemExit(1)


def _load_fixture(fixture_dir: Path):
    import pandas as pd

    hist = fixture_dir / "history_wide.csv"
    if not hist.is_file():
        _fail(f"missing {hist}")
    df = pd.read_csv(hist)
    if "timestamp_utc" in df.columns:
        ts = pd.to_datetime(df["timestamp_utc"], utc=True)
    elif "timestamp" in df.columns:
        ts = pd.to_datetime(df["timestamp"], utc=True)
    else:
        _fail("fixture needs timestamp_utc or timestamp")
    df = df.copy()
    df.index = ts
    cols = fixture_dir / "columns.csv"
    if cols.is_file():
        cmap = pd.read_csv(cols)
        mapping = {
            str(r["col"]): str(r["point_role"])
            for _, r in cmap.iterrows()
            if pd.notna(r.get("col")) and pd.notna(r.get("point_role"))
        }
        df = df.rename(columns=mapping)
    return df


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fixture", type=Path, required=True, help="Fixture directory")
    ap.add_argument("--rule", required=True, help="Pandas rule id (e.g. ECON-4, FC13)")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--poll-seconds", type=float, default=300.0)
    ap.add_argument("--equipment-id", default="AHU_1")
    args = ap.parse_args()

    try:
        from open_fdd.rules import RULES_BY_ID, run_rule
    except ImportError as e:
        _fail(f"open_fdd.rules not importable — pip install 'open-fdd[oracle]': {e}")

    if args.rule not in RULES_BY_ID and args.rule != "FC13":
        # FC13-SAT-HIGH is SQL id; pandas id is FC13
        _fail(f"unknown rule {args.rule!r}; known aliases include SV-SLEW")

    rule_id = "FC13" if args.rule in ("FC13", "FC13-SAT-HIGH") else args.rule
    df = _load_fixture(args.fixture)
    df.attrs["equipment_id"] = args.equipment_id
    result = run_rule(rule_id, df, poll_seconds=args.poll_seconds)

    raw = result.raw_fault
    confirmed = result.confirmed_fault
    payload: dict[str, Any] = {
        "ok": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "rule_id": rule_id,
        "equipment_id": args.equipment_id,
        "status": result.status,
        "missing_roles": list(result.missing_roles or []),
        "fault_hours": result.fault_hours,
        "fault_pct": result.fault_pct,
        "sample_count": result.sample_count,
        "params_fingerprint": result.params_fingerprint,
        "notes": result.notes,
        "raw_fault_true_count": int(raw.fillna(False).sum()) if raw is not None else None,
        "confirmed_fault_true_count": int(confirmed.fillna(False).sum())
        if confirmed is not None
        else None,
        "engine": "open_fdd.rules",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
