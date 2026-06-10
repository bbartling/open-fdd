"""Reheat valve open when outdoor air is warm (Arrow, VAV-A)."""

import pyarrow as pa
import pyarrow.compute as pc


def _norm_cmd(col):
    c = pc.cast(col, pa.float64())
    return pc.if_else(pc.greater(c, 1.0), pc.divide(c, 100.0), c)


def _false_mask(table):
    return pa.array([False] * table.num_rows, type=pa.bool_())


def _oat_column(table, cfg):
    for name in cfg.get("oat_columns") or ["oa-t", "outdoor_air_temperature", "outside-air-temperature"]:
        if name in table.column_names:
            return name
    return None


def apply_faults_arrow(table, cfg, context=None):
    oat_col = _oat_column(table, cfg)
    reheat_col = str(cfg.get("value_column") or cfg.get("reheat_column") or "heating-valve-command")
    if not oat_col or reheat_col not in table.column_names:
        return _false_mask(table)
    cutoff = float(cfg.get("t_amb_cutoff") or cfg.get("warm_oat_cutoff_f") or 78.0)
    reheat_min = float(cfg.get("reheat_open_min") or 0.52)
    oat = pc.cast(table[oat_col], pa.float64())
    reheat = _norm_cmd(table[reheat_col])
    warm = pc.greater(oat, cutoff)
    open_valve = pc.greater(reheat, reheat_min)
    return pc.and_(warm, open_valve)
