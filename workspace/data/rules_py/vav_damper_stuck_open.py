"""VAV damper stuck wide open — flat command with damper near 100% (Arrow, VAV-D)."""

import pyarrow as pa
import pyarrow.compute as pc

from open_fdd.arrow_runtime.cookbook import flatline_1h_mask


def _norm_cmd(col):
    c = pc.cast(col, pa.float64())
    return pc.if_else(pc.greater(c, 1.0), pc.divide(c, 100.0), c)


def _false_mask(table):
    return pa.array([False] * table.num_rows, type=pa.bool_())


def apply_faults_arrow(table, cfg, context=None):
    col = str(cfg.get("value_column") or cfg.get("column") or "damper-position-command")
    if col not in table.column_names:
        return _false_mask(table)
    stuck = flatline_1h_mask(table, {**cfg, "column": col})
    wide = pc.greater(_norm_cmd(table[col]), float(cfg.get("damper_open_min", 0.975)))
    return pc.and_(stuck, wide)
