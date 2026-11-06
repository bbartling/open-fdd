#!/usr/bin/env python3
"""Sample-level look at one rule: pandas raw/confirmed fault vs SQL fault hours, on the SI parity dataset.

    python tests/parity/debug_rule.py FC1 --equip AHU-2 [--equips 2 --days 3] [--out debug.json]

(Replaces tools/python_oracle/debug_rule_parity.py, which needed the retired crate fixtures.)
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness as h  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("rule")
    ap.add_argument("--equip", default="AHU-2")
    ap.add_argument("--equips", type=int, default=2)
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    data = h.run_sql(a.equips, a.days, Path(tempfile.mkdtemp()) / "sql.json", engines="pglite", rules=a.rule)
    sql = h.sql_rows(data, "pglite", a.rule).get(a.equip)
    hours, status = h.pandas_fault_hours(a.rule, h.equip_frame(data, a.equip), h.weather_frame(data))
    out = {"rule": a.rule, "equipment": a.equip, "sql": sql, "pandas_fault_hours": hours, "pandas_status": status}
    print(json.dumps(out, indent=2))
    if a.out:
        a.out.write_text(json.dumps(out, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
