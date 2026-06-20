import pyarrow as pa
import pyarrow.compute as pc

def apply_faults_arrow(table, cfg, context=None):
    col = str(cfg.get("value_column") or "stat_zn-t")
    low = float(cfg.get("low", 65))
    high = float(cfg.get("high", 75))
    if col not in table.column_names:
        return pa.array([False] * table.num_rows, type=pa.bool_())
    v = pc.cast(table[col], pa.float64())
    return pc.or_(pc.less(v, low), pc.greater(v, high))
