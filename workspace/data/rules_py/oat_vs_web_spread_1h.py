"""Local OA-T vs OpenWeather web-oat-t spread (Arrow, BLD-B).

Requires BACnet historian ``oa-t`` (or ``local_oat_column`` in cfg) and JSON API
``web-oat-t``. Register OpenWeather via JSON API tab; bind RTU/boiler OAT in model
with ``external_id: oa-t`` or set ``local_oat_column`` to the BACnet feather column.
"""

import pyarrow as pa
import pyarrow.compute as pc

LOCAL_OAT = "oa-t"
WEB_OAT = "web-oat-t"
MAX_SPREAD_F = 8.0


def _false_mask(table):
    return pa.array([False] * table.num_rows, type=pa.bool_())


def _col_names(cfg):
    local = str(cfg.get("local_oat_column") or cfg.get("value_column") or LOCAL_OAT)
    web = str(cfg.get("web_oat_column") or WEB_OAT)
    spread = float(cfg.get("max_spread_f") or cfg.get("max_spread") or MAX_SPREAD_F)
    return local, web, spread


def apply_faults_arrow(table, cfg, context=None):
    local_col, web_col, max_spread = _col_names(cfg)
    if local_col not in table.column_names or web_col not in table.column_names:
        return _false_mask(table)
    local = pc.cast(table[local_col], pa.float64())
    web = pc.cast(table[web_col], pa.float64())
    spread = pc.abs(pc.subtract(local, web))
    return pc.greater(spread, max_spread)
