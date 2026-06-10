"""VAV reheat leak — discharge air much hotter than parent AHU supply air (Arrow, VAV-A)."""

import pyarrow as pc


def apply_faults_arrow(table, cfg, context=None):
    dat_col = str(cfg.get("value_column") or cfg.get("column") or "discharge-air-temperature")
    sat_col = str(cfg.get("reference_sat_column") or "sa-t")
    delta_f = float(cfg.get("reheat_delta_f", 8.0))
    if dat_col not in table.column_names or sat_col not in table.column_names:
        return pc.fill_null(
            pc.cast(table[table.column_names[0]], __import__("pyarrow").bool_()),
            False,
        )
    dat = pc.cast(table[dat_col], __import__("pyarrow").float64())
    sat = pc.cast(table[sat_col], __import__("pyarrow").float64())
    return pc.greater(pc.subtract(dat, sat), delta_f)
