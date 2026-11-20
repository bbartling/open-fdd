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


def role_timeseries(long: pd.DataFrame, roles, *, limit: int = 5000, start_ms: int | None = None,
                    end_ms: int | None = None) -> pd.DataFrame:
    """Samples of the given roles, newest first (then point_key, then the larger value), at most ``limit`` rows."""
    d = _clean(long, start_ms, end_ms)
    d = d[d["role"].isin(list(roles))]
    d = d.sort_values(["ts_ms", "point_key", "value"], ascending=[False, True, False], kind="stable").head(int(limit))
    return d.rename(columns={"ts_ms": "t"}).loc[:, ["point_key", "equipment_id", "role", "t", "value"]].reset_index(drop=True)


ANOMALY_ROLES = ("sat", "mat", "rat", "oa_t", "web_oa_t", "zone_t", "duct_static")


def anomaly_coverage(points: pd.DataFrame, long: pd.DataFrame, *, window: int = 24, roles=ANOMALY_ROLES,
                     start_ms: int | None = None, end_ms: int | None = None) -> pd.DataFrame:
    """Per bound point of ``roles`` (``points``: point_key, equipment_id, role), even with no samples: n, var_val
    (sample variance; NaN below two), is_short (n < window) and is_constant (n >= 2 and min == max)."""
    pts = points[points["role"].isin(list(roles))].loc[:, ["point_key", "equipment_id", "role"]]
    d = _clean(long, start_ms, end_ms)
    agg = d.groupby("point_key")["value"].agg(n="size", var_val=lambda s: s.var(ddof=1), vmin="min", vmax="max")
    out = pts.merge(agg, left_on="point_key", right_index=True, how="left")
    out["n"] = out["n"].fillna(0).astype(int)
    out["is_short"] = (out["n"] < int(window)).astype(int)
    out["is_constant"] = ((out["n"] >= 2) & (out["vmin"] == out["vmax"])).astype(int)
    out = out.drop(columns=["vmin", "vmax"])
    return out.sort_values("point_key", kind="stable").reset_index(drop=True)


PID_COMMAND_ROLES = ("clg_valve_pct", "htg_valve_pct", "oa_damper_pct", "fan_cmd")
PID_ROLES = (*PID_COMMAND_ROLES, "duct_static", "sat", "zone_t")
# variance limits = (legacy stddev limit)^2, written exactly as in pid_hunting_proxy.sql
PID_VAR_LIMIT = {"sat": 19.75308641975309, "zone_t": 19.75308641975309, "duct_static": 3962966.1184}
PID_VAR_LIMIT_COMMAND = 0.0064


def pid_hunting_proxy(long: pd.DataFrame, *, start_ms: int | None = None, end_ms: int | None = None) -> pd.DataFrame:
    """Per point with >= 12 samples of the PID roles: n, avg_val, var_val (commands scaled to 0-1) and is_hunting
    (n >= 24 and variance above the role's limit). Largest spread first."""
    d = _clean(long, start_ms, end_ms)
    d = d[d["role"].isin(PID_ROLES)].copy()
    cmd = d["role"].isin(PID_COMMAND_ROLES) & (d["value"] > 1.5)
    d.loc[cmd, "value"] = d.loc[cmd, "value"] / 100.0
    g = d.groupby(["point_key", "equipment_id", "role"], dropna=False, sort=True)["value"]
    out = g.agg(n="size", avg_val="mean", var_val=lambda s: s.var(ddof=1)).reset_index()
    out = out[out["n"] >= 12]
    limit = out["role"].map(PID_VAR_LIMIT).fillna(PID_VAR_LIMIT_COMMAND)
    out["is_hunting"] = ((out["n"] >= 24) & (out["var_val"] > limit)).astype(int)
    return out.sort_values(["var_val", "point_key"], ascending=[False, True], kind="stable").reset_index(drop=True)


# ---- slice 3: daily meter aggregates, day-over-day change points ---------------------------------------------------
METER_ROLES = ("electric_kwh", "kwh", "electric_kw", "power_kw", "chiller_power", "gas_therm", "gas_ccf", "fuel_gal",
               "steam_mlb", "water_gal")
FUEL_ROLES = ("gas_therm", "gas_ccf", "fuel_gal", "steam_mlb", "electric_kwh", "power_kw")
MV_ROLES = ("electric_kwh", "kwh", "electric_kw", "gas_therm", "power_kw", "steam_mlb", "oa_t", "web_oa_t", "sat",
            "zone_t")
MV_TEMP_ROLES = ("oa_t", "web_oa_t", "sat", "zone_t")
_DAY = 86_400_000


def meter_daily(long: pd.DataFrame, *, roles=METER_ROLES, limit: int = 2000, start_ms: int | None = None,
                end_ms: int | None = None) -> pd.DataFrame:
    """Per point and UTC day: n, min_val, max_val, avg_val, delta_val (max - min). Newest day first, then point."""
    d = _clean(long, start_ms, end_ms)
    d = d[d["role"].isin(list(roles))]
    d = d.assign(day_ms=d["ts_ms"] - (d["ts_ms"] % _DAY))
    g = d.groupby(["point_key", "equipment_id", "role", "day_ms"], dropna=False, sort=True)["value"]
    out = g.agg(n="size", min_val="min", max_val="max", avg_val="mean").reset_index()
    out["delta_val"] = out["max_val"] - out["min_val"]
    out = out.sort_values(["day_ms", "point_key"], ascending=[False, True], kind="stable").head(int(limit))
    return out.reset_index(drop=True)


def mv_change_points(long: pd.DataFrame, *, roles=MV_ROLES, limit: int = 2000, start_ms: int | None = None,
                     end_ms: int | None = None) -> pd.DataFrame:
    """Day-over-day CHANGE rows (archived 4.x thresholds); see sql/analytics/mv_change_point_daily.sql."""
    d = _clean(long, start_ms, end_ms)
    d = d[d["role"].isin(list(roles))]
    d = d.assign(day_ms=d["ts_ms"] - (d["ts_ms"] % _DAY))
    g = d.groupby(["point_key", "equipment_id", "role", "day_ms"], dropna=False, sort=True)["value"]
    daily = g.agg(avg_val="mean", n="size").reset_index()
    daily = daily[daily["n"] >= 6].sort_values(["point_key", "day_ms"], kind="stable")
    daily["prev_avg"] = daily.groupby("point_key")["avg_val"].shift(1)
    daily = daily[daily["prev_avg"].notna()].copy()
    temp = daily["role"].isin(MV_TEMP_ROLES)
    t_req = ((daily["prev_avg"] - (-17.77777777777778)).abs() * 0.25).clip(lower=0.5555555555555556)
    o_req = (daily["prev_avg"].abs() * 0.25).clip(lower=1.0)
    daily["required_delta"] = t_req.where(temp, o_req)
    daily["delta_avg"] = daily["avg_val"] - daily["prev_avg"]
    daily["abs_delta"] = daily["delta_avg"].abs()
    out = daily[daily["abs_delta"] >= daily["required_delta"]]
    out = out.sort_values(["day_ms", "abs_delta", "point_key"], ascending=[False, False, True], kind="stable")
    return out.drop(columns="abs_delta").head(int(limit)).reset_index(drop=True)


def zone_comfort(long: pd.DataFrame, occupied, *, lo_c: float, hi_c: float, start_ms: int | None = None,
                 end_ms: int | None = None) -> pd.DataFrame:
    """Per zone_t point: n_occ (samples in any occupied (start_ms, end_ms) half-open interval), n_in_band and
    pct_in_band for the band [lo_c, hi_c] degC. Worst first, then point_key; points with no occupied samples omitted."""
    lo, hi = float(min(lo_c, hi_c)), float(max(lo_c, hi_c))
    d = _clean(long, start_ms, end_ms)
    d = d[d["role"] == "zone_t"]
    occ = pd.Series(False, index=d.index)
    for a, b in occupied:
        occ |= (d["ts_ms"] >= int(a)) & (d["ts_ms"] < int(b))
    d = d[occ].assign(in_band=lambda x: ((x["value"] >= lo) & (x["value"] <= hi)).astype(int))
    out = d.groupby(["point_key", "equipment_id", "role"], dropna=False, sort=True).agg(
        n_occ=("value", "size"), n_in_band=("in_band", "sum")).reset_index()
    out["pct_in_band"] = 100.0 * out["n_in_band"] / out["n_occ"]
    return out.sort_values(["pct_in_band", "point_key"], kind="stable").reset_index(drop=True)
