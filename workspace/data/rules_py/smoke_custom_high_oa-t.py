"""Smoke custom OA-T high (Arrow constants)."""

import pyarrow.compute as pc

VALUE_COLUMN = "oa-t"
HIGH_LIMIT = 50.0


def _kit_value_stats(table):
    vals = pc.cast(table[VALUE_COLUMN], "float64")
    print(f"rows={table.num_rows} column={VALUE_COLUMN} max={pc.max(vals).as_py():.2f}")


def apply_faults_arrow(table, cfg, context=None):
    _kit_value_stats(table)
    vals = pc.cast(table[VALUE_COLUMN], "float64")
    return pc.greater(vals, HIGH_LIMIT)
