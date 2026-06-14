"""Humidity out of bounds (Arrow) — one rule for all bound humidity points."""

import pyarrow.compute as pc

DEFAULT_LOW = 15.0
DEFAULT_HIGH = 75.0


def _col(cfg):
    return str((cfg or {}).get("value_column") or "")


def apply_faults_arrow(table, cfg, context=None):
    col = _col(cfg)
    low = float((cfg or {}).get("low") or DEFAULT_LOW)
    high = float((cfg or {}).get("high") or DEFAULT_HIGH)
    vals = pc.cast(table[col], "float64")
    return pc.or_(pc.less(vals, low), pc.greater(vals, high))
