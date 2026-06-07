"""Bench humidity flatline 1h (Arrow)."""

import pyarrow.compute as pc
from open_fdd.arrow_runtime.windows import arrow_rolling_max, arrow_rolling_min

VALUE_COLUMN = "oa-h"
WINDOW_SAMPLES = 12
FLATLINE_TOLERANCE = 1.0


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
    rmin = arrow_rolling_min(vals, WINDOW_SAMPLES)
    rmax = arrow_rolling_max(vals, WINDOW_SAMPLES)
    spread = pc.subtract(rmax, rmin)
    return pc.less_equal(pc.abs(spread), FLATLINE_TOLERANCE)
