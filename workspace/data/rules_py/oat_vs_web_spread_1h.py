"""Local OA-T vs OpenWeather web-oat-t spread (Arrow).

Requires BACnet historian column ``oa-t`` and JSON API column ``web-oat-t``
(register via JSON API tab → OpenWeather bundle). Flags stuck or drifting
outdoor-air sensors when local readings diverge from the weather service.
"""

import pyarrow as pa
import pyarrow.compute as pc

LOCAL_OAT = "oa-t"
WEB_OAT = "web-oat-t"
MAX_SPREAD_F = 8.0


def _kit_fmt(scalar):
    v = scalar.as_py() if scalar is not None else None
    return "nan" if v is None else f"{v:.2f}"


def _kit_value_stats(table):
    if LOCAL_OAT not in table.column_names or WEB_OAT not in table.column_names:
        print(
            f"rows={table.num_rows} missing columns "
            f"(need {LOCAL_OAT} + {WEB_OAT}); available={table.column_names}"
        )
        return
    local = pc.cast(table[LOCAL_OAT], "float64")
    web = pc.cast(table[WEB_OAT], "float64")
    spread = pc.abs(pc.subtract(local, web))
    print(
        f"rows={table.num_rows} spread "
        f"min={_kit_fmt(pc.min(spread))} max={_kit_fmt(pc.max(spread))} "
        f"mean={_kit_fmt(pc.mean(spread))} threshold={MAX_SPREAD_F}"
    )


def apply_faults_arrow(table, cfg, context=None):
    _kit_value_stats(table)
    if LOCAL_OAT not in table.column_names or WEB_OAT not in table.column_names:
        return pa.array([False] * table.num_rows)
    local = pc.cast(table[LOCAL_OAT], "float64")
    web = pc.cast(table[WEB_OAT], "float64")
    spread = pc.abs(pc.subtract(local, web))
    return pc.greater(spread, MAX_SPREAD_F)
