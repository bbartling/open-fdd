#!/usr/bin/env python3
"""Sample-level parity debug export for one rule/equipment (Python oracle path).

Writes JSON under `.cache/debug/` (not committed).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

_APP = Path(__file__).resolve().parent
_BACKEND = _APP / "backend"
_ROOT = _APP.parent
for p in (_BACKEND, _ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import cookbook_engine as ce  # noqa: E402
import cookbook_rules as cb  # noqa: E402
from rules.base import confirm_fault  # noqa: E402
from shared.data_config import get_config  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--building", default=None)
    ap.add_argument("--equipment", default="AHU_1")
    ap.add_argument("--rule", default="FC2")
    ap.add_argument("--max-rows", type=int, default=500)
    ap.add_argument(
        "--out",
        type=Path,
        default=_ROOT / ".cache" / "debug" / "fc2_ahu1_parity.json",
    )
    args = ap.parse_args()
    cfg = get_config()
    building = args.building or cfg.building
    rule = cb.RULES_BY_ID.get(args.rule)
    if rule is None:
        print(f"Unknown rule {args.rule}", file=sys.stderr)
        return 1
    resolver = __import__("haystack_rdf.resolver", fromlist=["get_resolver"]).get_resolver()
    weather = ce.load_weather(resolver)
    d, resolved, poll, _wx = ce.build_logical_frame(args.equipment, "ahu", resolver, weather)
    if d is None or d.empty:
        print(f"No data for {args.equipment}", file=sys.stderr)
        return 1
    params = {p.key: p.default for p in rule.params}
    raw = rule.compute(d, params, poll)
    confirmed = confirm_fault(raw, poll_seconds=poll, confirm_seconds=rule.confirm_seconds)
    out_rows = []
    n = min(args.max_rows, len(d))
    for i in range(n):
        ts = d.index[i] if isinstance(d.index, pd.DatetimeIndex) else d.iloc[i].get("timestamp")
        row = d.iloc[i]
        out_rows.append(
            {
                "timestamp": str(ts),
                "mat": float(row["mat"]) if "mat" in d.columns and pd.notna(row.get("mat")) else None,
                "oa_t": float(row["oa_t"]) if "oa_t" in d.columns and pd.notna(row.get("oa_t")) else None,
                "rat": float(row["rat"]) if "rat" in d.columns and pd.notna(row.get("rat")) else None,
                "fan_cmd": float(row["fan_cmd"]) if "fan_cmd" in d.columns and pd.notna(row.get("fan_cmd")) else None,
                "fan_status": float(row["fan_status"]) if "fan_status" in d.columns and pd.notna(row.get("fan_status")) else None,
                "raw_python_fault": bool(raw.iloc[i]),
                "confirmed_python_fault": bool(confirmed.iloc[i]),
            }
        )
    payload = {
        "building": building,
        "equipment": args.equipment,
        "rule": args.rule,
        "confirm_seconds": rule.confirm_seconds,
        "poll_seconds": poll,
        "resolved_roles": resolved,
        "raw_fault_samples": int(raw.fillna(False).sum()),
        "confirmed_fault_samples": int(confirmed.sum()),
        "confirmed_fault_hours": float(confirmed.sum() * poll / 3600.0),
        "rows": out_rows,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    summary = {k: payload[k] for k in payload if k != "rows"}
    print(json.dumps({"ok": True, "out": str(args.out), **summary}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
