"""Temperature rate of change (Arrow) — flags steps faster than recent history."""

import pyarrow as pa
import pyarrow.compute as pc

DEFAULT_MULTIPLIER = 3.0
DEFAULT_FLOOR = 0.15


def _col(cfg):
    return str((cfg or {}).get("value_column") or "").strip()


def _as_array(vals):
    try:
        return vals.combine_chunks()
    except Exception:
        return vals


def apply_faults_arrow(table, cfg, context=None):
    col = _col(cfg)
    n = table.num_rows
    if not col or n < 3:
        return pa.array([False] * n, type=pa.bool_())
    mult = float((cfg or {}).get("roc_multiplier") or DEFAULT_MULTIPLIER)
    floor = float((cfg or {}).get("roc_floor") or DEFAULT_FLOOR)
    vals = _as_array(pc.cast(table[col], "float64"))
    prev = vals.slice(0, n - 1)
    curr = vals.slice(1, n)
    step = pc.abs(pc.subtract(curr, prev))
    mean = pc.mean(step).as_py()
    std = pc.stddev(step).as_py()
    if mean is None:
        mean = 0.0
    if std is None:
        std = 0.0
    thresh = max(floor, float(mean) + mult * float(std))
    tail_flags = pc.greater(step, thresh)
    head = pa.array([False], type=pa.bool_())
    return pa.concat_arrays([head, tail_flags])
