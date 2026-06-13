"""VAV reheat leak — discharge air much hotter than parent AHU supply air (Arrow, VAV-A)."""

import pyarrow as pa
import pyarrow.compute as pc


def _false_mask(table):
    return pa.array([False] * table.num_rows, type=pa.bool_())


def apply_faults_arrow(table, cfg, context=None):
    dat_col = str(cfg.get("value_column") or cfg.get("column") or "discharge-air-temperature")
    sat_col = str(cfg.get("reference_sat_column") or "sa-t")
    delta_f = float(cfg.get("reheat_delta_f", 8.0))
    if dat_col not in table.column_names or sat_col not in table.column_names:
        return _false_mask(table)
    dat = pc.cast(table[dat_col], pa.float64())
    sat = pc.cast(table[sat_col], pa.float64())
    return pc.greater(pc.subtract(dat, sat), delta_f)
