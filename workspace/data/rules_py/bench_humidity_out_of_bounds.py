"""Bench humidity out of bounds (Arrow)."""

import pyarrow.compute as pc

VALUE_COLUMN = "oa-h"
RH_LOW = 15.0
RH_HIGH = 75.0


def _kit_value_stats(table):
    vals = pc.cast(table[VALUE_COLUMN], "float64")
    print(
        f"rows={table.num_rows} column={VALUE_COLUMN} "
        f"min={pc.min(vals).as_py():.2f} max={pc.max(vals).as_py():.2f} "
        f"mean={pc.mean(vals).as_py():.2f}"
    )


def apply_faults_arrow(table, cfg, context=None):
    _kit_value_stats(table)
    vals = pc.cast(table[VALUE_COLUMN], "float64")
    return pc.or_(pc.less(vals, RH_LOW), pc.greater(vals, RH_HIGH))
