#!/usr/bin/env python3
"""Minimal Open-FDD Arrow rule — no Docker required."""

from __future__ import annotations

import pyarrow as pa
import pyarrow.compute as pc

from open_fdd.arrow_runtime import run_arrow_rule

RULE = '''
import pyarrow.compute as pc

def apply_faults_arrow(table, cfg, context=None):
    col = str(cfg.get("value_column", "SAT"))
    return pc.greater(table[col], float(cfg["high"]))
'''

def main() -> None:
    table = pa.table({"SAT": [70.0, 90.0, 88.0, 72.0]})
    result = run_arrow_rule(RULE, table, {"high": 85, "value_column": "SAT"})
    print("version ok, true_count=", result.true_count, "errors=", result.errors)


if __name__ == "__main__":
    main()
