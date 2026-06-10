"""VAV airflow chronically below minimum when damper is open (Arrow, VAV-B)."""

import pyarrow as pc


def _norm_cmd(col):
    c = pc.cast(col, __import__("pyarrow").float64())
    return pc.if_else(pc.greater(c, 1.0), pc.divide(c, 100.0), c)


def apply_faults_arrow(table, cfg, context=None):
    flow_col = str(cfg.get("value_column") or cfg.get("column") or "airflow")
    damper_col = str(cfg.get("damper_column") or "damper-position-command")
    min_flow = float(cfg.get("min_airflow_cfm", 50))
    damper_min = float(cfg.get("damper_open_min", 0.15))
    if flow_col not in table.column_names:
        return pc.fill_null(
            pc.cast(table[table.column_names[0]], __import__("pyarrow").bool_()),
            False,
        )
    flow = pc.cast(table[flow_col], __import__("pyarrow").float64())
    low = pc.less(flow, min_flow)
    if damper_col in table.column_names:
        damper = _norm_cmd(table[damper_col])
        return pc.and_(low, pc.greater_equal(damper, damper_min))
    return low
