"""Bench OA temperature high — PyArrow (device 5007 OA-T)."""

import pyarrow.compute as pc


def apply_faults_arrow(table, cfg, context=None):
    col = str((cfg or {}).get("value_column") or "oa-t")
    high = float((cfg or {}).get("high", 85.0))
    vals = pc.cast(table[col], "float64")
    return pc.greater(vals, high)
