"""Bench OA-T out of bounds (Arrow)."""

import pyarrow.compute as pc

VALUE_COLUMN = "oa-t"
OAT_LOW = 68.0
OAT_HIGH = 88.0


def _kit_fmt(scalar):
    v = scalar.as_py() if scalar is not None else None
    return "nan" if v is None else f"{v:.2f}"


def _kit_value_stats(table):
    vals = pc.cast(table[VALUE_COLUMN], "float64")
    print(
        f"rows={table.num_rows} column={VALUE_COLUMN} "
        f"min={_kit_fmt(pc.min(vals))} max={_kit_fmt(pc.max(vals))} "
        f"mean={_kit_fmt(pc.mean(vals))}"
    )


def apply_faults_arrow(table, cfg, context=None):
    _kit_value_stats(table)
    vals = pc.cast(table[VALUE_COLUMN], "float64")
    return pc.or_(pc.less(vals, OAT_LOW), pc.greater(vals, OAT_HIGH))
