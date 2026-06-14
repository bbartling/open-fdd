"""Bench humidity out of bounds (Arrow)."""

import pyarrow.compute as pc

VALUE_COLUMN = "oa-h"
RH_LOW = 15.0
RH_HIGH = 75.0


def _col(cfg):
    return str((cfg or {}).get("value_column") or VALUE_COLUMN)


def _kit_fmt(scalar):
    v = scalar.as_py() if scalar is not None else None
    return "nan" if v is None else f"{v:.2f}"


def apply_faults_arrow(table, cfg, context=None):
    col = _col(cfg)
    vals = pc.cast(table[col], "float64")
    print(
        f"rows={table.num_rows} column={col} "
        f"min={_kit_fmt(pc.min(vals))} max={_kit_fmt(pc.max(vals))} "
        f"mean={_kit_fmt(pc.mean(vals))}"
    )
    return pc.or_(pc.less(vals, RH_LOW), pc.greater(vals, RH_HIGH))
