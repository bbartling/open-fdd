"""Per-point statistics (issue #1757): the pandas twins of ``sql/analytics/sensor_stats.sql``, ``diurnal_hourly.sql``
and ``setpoints_latest.sql``.

Input is a long frame with columns ``point_key, equipment_id, role, ts_ms, value`` (SI values, UTC epoch ms). NULL
values are dropped first, as the core view ``fdd.input_sample`` does. Each function returns one row per point (and per
UTC hour for :func:`diurnal_hourly`), sorted like the SQL.
"""

from __future__ import annotations

import pandas as pd

LONG_COLUMNS = ("point_key", "equipment_id", "role", "ts_ms", "value")
DIURNAL_ROLES = ("oa_t", "web_oa_t", "sat", "mat", "rat", "zone_t", "fan_cmd", "clg_valve_pct", "htg_valve_pct")


def _clean(long: pd.DataFrame, start_ms: int | None, end_ms: int | None) -> pd.DataFrame:
    d = long.loc[:, list(LONG_COLUMNS)].copy()
    d["value"] = pd.to_numeric(d["value"], errors="coerce").astype(float)
    d["ts_ms"] = d["ts_ms"].astype("int64")
    d = d[d["value"].notna()]
    if start_ms is not None:
        d = d[d["ts_ms"] >= int(start_ms)]
    if end_ms is not None:
        d = d[d["ts_ms"] < int(end_ms)]
    return d


def sensor_stats(long: pd.DataFrame, *, start_ms: int | None = None, end_ms: int | None = None) -> pd.DataFrame:
    """Per point: n, min_val, max_val, avg_val, stddev_val (sample, n - 1; NaN for one sample), first_ms, last_ms."""
    d = _clean(long, start_ms, end_ms)
    g = d.groupby(["point_key", "equipment_id", "role"], dropna=False, sort=True)
    out = g.agg(n=("value", "size"), min_val=("value", "min"), max_val=("value", "max"), avg_val=("value", "mean"),
                stddev_val=("value", lambda s: s.std(ddof=1)), first_ms=("ts_ms", "min"), last_ms=("ts_ms", "max"))
    return out.reset_index().sort_values("point_key", kind="stable").reset_index(drop=True)


def diurnal_hourly(long: pd.DataFrame, *, roles=DIURNAL_ROLES, start_ms: int | None = None,
                   end_ms: int | None = None) -> pd.DataFrame:
    """Per point and UTC hour of day (0-23): avg_val and n over the roles given (None = every role)."""
    d = _clean(long, start_ms, end_ms)
    if roles is not None:
        d = d[d["role"].isin(list(roles))]
    d = d.assign(hour_utc=((d["ts_ms"] % 86_400_000) // 3_600_000).astype(int))
    g = d.groupby(["point_key", "equipment_id", "role", "hour_utc"], dropna=False, sort=True)
    out = g.agg(avg_val=("value", "mean"), n=("value", "size")).reset_index()
    return out.sort_values(["point_key", "hour_utc"], kind="stable").reset_index(drop=True)


def setpoint_roles(role_map: dict) -> list[str]:
    """The setpoint roles of a role map: every role ending in ``_sp`` or ``_setpoint``."""
    return sorted(r for r in role_map if r.endswith("_sp") or r.endswith("_setpoint"))


def latest_setpoints(long: pd.DataFrame, roles, *, start_ms: int | None = None,
                     end_ms: int | None = None) -> pd.DataFrame:
    """Per point of the given roles: the last sample in the window (``t``, ``value``); a tie keeps the larger value."""
    d = _clean(long, start_ms, end_ms)
    d = d[d["role"].isin(list(roles))]
    d = d.sort_values(["point_key", "ts_ms", "value"], kind="stable")
    last = d.groupby("point_key", sort=True).tail(1)
    out = last.rename(columns={"ts_ms": "t"}).loc[:, ["point_key", "equipment_id", "role", "t", "value"]]
    return out.sort_values("point_key", kind="stable").reset_index(drop=True)
