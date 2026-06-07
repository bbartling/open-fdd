"""Bench stat ZN-T flatline 1h (Arrow)."""

import pyarrow.compute as pc
from open_fdd.arrow_runtime.windows import arrow_rolling_max, arrow_rolling_min

VALUE_COLUMN = "stat_zn-t"
WINDOW_SAMPLES = 12
FLATLINE_TOLERANCE = 0.1


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
    rmin = arrow_rolling_min(vals, WINDOW_SAMPLES)
    rmax = arrow_rolling_max(vals, WINDOW_SAMPLES)
    spread = pc.subtract(rmax, rmin)
    return pc.less_equal(pc.abs(spread), FLATLINE_TOLERANCE)
