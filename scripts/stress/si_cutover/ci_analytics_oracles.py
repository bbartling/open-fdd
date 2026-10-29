"""Pandas SI oracles for W4f analytics P2 (#1284). Mirrors SQL row keys and numerics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Sequence

import numpy as np
import pandas as pd

from scripts.stress.si_cutover import ci_fixtures_lib as cfl
from scripts.stress.si_cutover.parity_chain import ANALYTICS_REL_TOL, analytics_relative_equal


@dataclass(frozen=True)
class OracleRowSet:
    rows: tuple[tuple[Any, ...], ...]
    key_columns: tuple[int, ...]
    numeric_columns: tuple[int, ...]
    comparison_type: str


def _melt_si_frame(si_frame: pd.DataFrame, equipment_id: str) -> pd.DataFrame:
    """Long sample rows matching Timescale seed (openfdd_key = equipment_id.role)."""
    records: list[dict[str, Any]] = []
    idx = si_frame.index
    for col in si_frame.columns:
        if col in {"equipment_id", "occ_mode"}:
            continue
        role = cfl.frame_column_to_sql_role(str(col))
        key = f"{equipment_id}.{role}"
        ser = pd.to_numeric(si_frame[col], errors="coerce")
        for ts, val in ser.items():
            if pd.isna(val):
                continue
            records.append(
                {
                    "ts": ts.tz_convert("UTC") if hasattr(ts, "tzinfo") and ts.tzinfo else ts,
                    "equipment_id": equipment_id,
                    "role": role,
                    "openfdd_key": key,
                    "val": float(val),
                }
            )
    if not records:
        return pd.DataFrame(columns=["ts", "equipment_id", "role", "openfdd_key", "val"])
    return pd.DataFrame.from_records(records)


def _window_filter(long: pd.DataFrame, ws: str | None, we: str | None) -> pd.DataFrame:
    if long.empty:
        return long
    out = long
    if ws:
        start = pd.Timestamp(ws)
        if start.tzinfo is None:
            start = start.tz_localize("UTC")
        out = out[out["ts"] >= start]
    if we:
        end = pd.Timestamp(we)
        if end.tzinfo is None:
            end = end.tz_localize("UTC")
        out = out[out["ts"] < end]
    return out


def compare_oracle_to_sql(
    sql_rows: Sequence[Sequence[Any]],
    oracle: OracleRowSet,
    *,
    stem: str,
    abs_tol: float | None = None,
) -> tuple[int, list[str]]:
    errors: list[str] = []
    pd_rows = oracle.rows

    def row_key(row: Sequence[Any]) -> tuple[Any, ...]:
        return tuple(row[i] for i in oracle.key_columns)

    sql_by_key = {row_key(r): r for r in sql_rows}
    pd_by_key = {row_key(r): r for r in pd_rows}
    comparisons = 0

    extra_sql = set(sql_by_key) - set(pd_by_key)
    extra_pd = set(pd_by_key) - set(sql_by_key)
    if extra_sql or extra_pd:
        if len(extra_sql) <= 3 and len(extra_pd) <= 3:
            for k in sorted(extra_sql)[:5]:
                errors.append(f"{stem}: SQL-only key {k!r}")
            for k in sorted(extra_pd)[:5]:
                errors.append(f"{stem}: pandas-only key {k!r}")
        else:
            errors.append(
                f"{stem}: row key mismatch sql={len(sql_by_key)} pandas={len(pd_by_key)} "
                f"(sql_only={len(extra_sql)} pandas_only={len(extra_pd)})"
            )

    for key in sorted(set(sql_by_key) & set(pd_by_key)):
        srow = sql_by_key[key]
        prow = pd_by_key[key]
        comparisons += 1
        for col_i in oracle.numeric_columns:
            sv, pv = srow[col_i], prow[col_i]
            if sv is None and pv is None:
                continue
            if (sv is None) != (pv is None):
                if sv is None and pv == 0.0:
                    continue
                if pv is None and sv == 0.0:
                    continue
                errors.append(f"{stem} key={key} col={col_i}: sql={sv!r} pandas={pv!r}")
                continue
            if isinstance(sv, (int, np.integer)) and isinstance(pv, (int, np.integer)):
                if int(sv) != int(pv):
                    errors.append(f"{stem} key={key} col={col_i}: sql={sv} pandas={pv}")
                continue
            if not analytics_relative_equal(float(sv), float(pv)):
                if abs_tol is not None and abs(float(sv) - float(pv)) <= abs_tol:
                    continue
                errors.append(f"{stem} key={key} col={col_i}: sql={sv} pandas={pv}")

    if comparisons == 0 and not sql_rows and not pd_rows:
        comparisons = 1
    return comparisons, errors


def oracle_plant_health_inventory(*, equipment_id: str, equip_type: str) -> OracleRowSet:
    rows = ((equipment_id, equip_type),)
    return OracleRowSet(rows, key_columns=(0, 1), numeric_columns=(), comparison_type="keys_only")


def oracle_sensor_stats(long: pd.DataFrame) -> OracleRowSet:
    if long.empty:
        return OracleRowSet((), (0, 1, 2), (3, 4, 5, 6), "numeric_parity")
    g = long.groupby(["equipment_id", "role", "openfdd_key"], sort=True)
    rows: list[tuple[Any, ...]] = []
    for (eid, role, key), grp in g:
        vals = grp["val"]
        rows.append(
            (
                eid,
                role,
                key,
                int(len(vals)),
                float(vals.min()),
                float(vals.max()),
                float(vals.mean()),
                float(vals.std(ddof=1)) if len(vals) > 1 else None,
                grp["ts"].min(),
                grp["ts"].max(),
            )
        )
    rows.sort(key=lambda r: (r[0], r[1], r[2]))
    return OracleRowSet(tuple(rows[:2000]), (0, 1, 2), (3, 4, 5, 6, 7), "numeric_parity")


def oracle_diurnal_hourly(long: pd.DataFrame) -> OracleRowSet:
    roles = {
        "oa_t",
        "web_oa_t",
        "sat",
        "mat",
        "rat",
        "zone_t",
        "fan_cmd",
        "clg_valve_pct",
        "htg_valve_pct",
    }
    sub = long[long["role"].isin(roles)]
    if sub.empty:
        return OracleRowSet((), (0, 1, 2, 3), (4, 5), "numeric_parity")
    sub = sub.copy()
    sub["hour_utc"] = sub["ts"].dt.hour.astype(int)
    rows: list[tuple[Any, ...]] = []
    for (eid, role, key, hour), grp in sub.groupby(
        ["equipment_id", "role", "openfdd_key", "hour_utc"], sort=True
    ):
        rows.append((eid, role, key, int(hour), float(grp["val"].mean()), int(len(grp))))
    rows.sort(key=lambda r: (r[0], r[1], r[2], r[3]))
    return OracleRowSet(tuple(rows[:5000]), (0, 1, 2, 3), (4, 5), "numeric_parity")


def oracle_role_timeseries(long: pd.DataFrame, *, role: str, limit: int) -> OracleRowSet:
    sub = long[long["role"] == role]
    if sub.empty:
        return OracleRowSet((), (0, 1), (2,), "numeric_parity")
    sub = sub.sort_values(["ts", "openfdd_key"], ascending=[False, True]).head(limit)
    rows = tuple(
        (r.ts, r.openfdd_key, r.val, r.equipment_id, r.role) for r in sub.itertuples(index=False)
    )
    return OracleRowSet(rows, (0, 1), (2,), "numeric_parity")


def oracle_schedule_occupancy(long: pd.DataFrame) -> OracleRowSet:
    sub = long[long["role"] == "occ_mode"]
    if sub.empty:
        return OracleRowSet((), (0, 1), (2,), "numeric_parity")
    sub = sub.sort_values(["ts", "openfdd_key"], ascending=[False, True]).head(2000)
    rows = tuple((r.ts, r.openfdd_key, r.val, r.equipment_id) for r in sub.itertuples(index=False))
    return OracleRowSet(rows, (0, 1), (2,), "numeric_parity")


def oracle_setpoints_snapshot(long: pd.DataFrame) -> OracleRowSet:
    def is_sp(role: str) -> bool:
        return role.endswith("_sp") or role.endswith("_setpoint") or role in {
            "sat_sp",
            "dsp_sp",
            "zone_t_sp",
            "chw_supply_sp",
            "hw_supply_sp",
        }

    sub = long[long["role"].map(is_sp)]
    if sub.empty:
        return OracleRowSet((), (0, 1, 2), (4,), "numeric_parity")
    rows: list[tuple[Any, ...]] = []
    for key, grp in sub.groupby("openfdd_key", sort=True):
        latest = grp.sort_values("ts", ascending=False).iloc[0]
        rows.append(
            (
                latest["equipment_id"],
                latest["role"],
                key,
                latest["ts"],
                float(latest["val"]),
            )
        )
    rows.sort(key=lambda r: (r[0], r[1], r[2]))
    return OracleRowSet(tuple(rows[:2000]), (0, 1, 2), (4,), "numeric_parity")


def oracle_pid_hunting_proxy(long: pd.DataFrame) -> OracleRowSet:
    roles = {
        "clg_valve_pct",
        "htg_valve_pct",
        "oa_damper_pct",
        "fan_cmd",
        "dsp",
        "sat",
        "zone_t",
    }
    sub = long[long["role"].isin(roles)]
    rows: list[tuple[Any, ...]] = []
    for (eid, role, key), grp in sub.groupby(["equipment_id", "role", "openfdd_key"], sort=True):
        if len(grp) < 12:
            continue
        vals = grp["val"]
        std = float(vals.std(ddof=1)) if len(vals) > 1 else 0.0
        flag = "HUNT_PROXY" if len(vals) >= 24 and std > 8.0 else "OK"
        rows.append(
            (
                eid,
                role,
                key,
                int(len(vals)),
                float(vals.mean()),
                std,
                flag,
            )
        )
    rows.sort(key=lambda r: (-(r[5] or 0.0), r[2]))
    return OracleRowSet(tuple(rows[:2000]), (0, 1, 2), (3, 4, 5), "numeric_parity")


def oracle_rcx_preset_role_coverage(long: pd.DataFrame) -> OracleRowSet:
    roles = {
        "oa_t",
        "web_oa_t",
        "sat",
        "mat",
        "rat",
        "oa_damper_pct",
        "zone_t",
        "dsp",
        "chw_supply_t",
        "hw_supply_t",
        "fan_cmd",
        "clg_valve_pct",
        "htg_valve_pct",
    }
    sub = long[long["role"].isin(roles)]
    rows: list[tuple[Any, ...]] = []
    for (eid, role, key), grp in sub.groupby(["equipment_id", "role", "openfdd_key"], sort=True):
        rows.append(
            (
                eid,
                role,
                key,
                int(len(grp)),
                grp["ts"].min(),
                grp["ts"].max(),
            )
        )
    rows.sort(key=lambda r: (r[0], r[1], r[2]))
    return OracleRowSet(tuple(rows[:5000]), (0, 1, 2), (3,), "numeric_parity")


def oracle_topology_equipment(
    long: pd.DataFrame, *, equipment_id: str, equip_type: str
) -> OracleRowSet:
    if long.empty:
        role_count = 0
        last_ts = None
    else:
        role_count = int(long["role"].nunique())
        last_ts = long["ts"].max()
    rows = ((equipment_id, equip_type, None, role_count, last_ts),)
    return OracleRowSet(rows, (0,), (3,), "numeric_parity")


def oracle_fuel_or_metering(long: pd.DataFrame, *, fuel: bool) -> OracleRowSet:
    if fuel:

        def match(role: str) -> bool:
            return (
                "gas" in role
                or "fuel" in role
                or "therm" in role
                or role
                in {"gas_therm", "gas_ccf", "fuel_gal", "steam_mlb", "electric_kwh", "power_kw"}
            )
    else:

        def match(role: str) -> bool:
            return (
                "kwh" in role
                or role.endswith("_kwh")
                or role in {"electric_kwh", "gas_therm", "steam_mlb", "water_gal", "power_kw"}
            )

    sub = long[long["role"].map(match)]
    rows: list[tuple[Any, ...]] = []
    if not sub.empty:
        sub = sub.copy()
        sub["day_utc"] = sub["ts"].dt.floor("D")
        for (eid, role, key, day), grp in sub.groupby(
            ["equipment_id", "role", "openfdd_key", "day_utc"], sort=True
        ):
            vals = grp["val"]
            rows.append(
                (
                    eid,
                    role,
                    key,
                    day,
                    int(len(vals)),
                    float(vals.min()),
                    float(vals.max()),
                    float(vals.mean()),
                    float(vals.max() - vals.min()),
                )
            )
    rows.sort(key=lambda r: (r[3], r[0], r[1], r[2]), reverse=True)
    return OracleRowSet(tuple(rows[:2000]), (0, 1, 2, 3), (4, 5, 6, 7, 8), "numeric_parity")


def oracle_mv_change_point_daily(long: pd.DataFrame) -> OracleRowSet:
    roles = {
        "electric_kwh",
        "gas_therm",
        "power_kw",
        "steam_mlb",
        "oa_t",
        "web_oa_t",
        "sat",
        "zone_t",
    }
    sub = long[long["role"].isin(roles)]
    rows: list[tuple[Any, ...]] = []
    if not sub.empty:
        sub = sub.copy()
        sub["day_utc"] = sub["ts"].dt.floor("D")
        daily = (
            sub.groupby(["equipment_id", "role", "openfdd_key", "day_utc"])["val"]
            .agg(["mean", "count"])
            .reset_index()
        )
        daily = daily[daily["count"] >= 6]
        for key, grp in daily.groupby("openfdd_key", sort=False):
            grp = grp.sort_values("day_utc")
            prev = grp["mean"].shift(1)
            for i, row in grp.iterrows():
                pavg = prev.loc[i]
                if pd.isna(pavg):
                    continue
                delta = float(row["mean"] - pavg)
                if abs(delta) < max(abs(float(pavg)) * 0.25, 1.0):
                    continue
                rows.append(
                    (
                        row["equipment_id"],
                        row["role"],
                        key,
                        row["day_utc"],
                        float(row["mean"]),
                        float(pavg),
                        delta,
                        int(row["count"]),
                        "CHANGE",
                    )
                )
    rows.sort(key=lambda r: (r[3], -abs(r[6]), r[2]), reverse=True)
    return OracleRowSet(tuple(rows[:2000]), (0, 1, 2, 3), (4, 5, 6, 7), "numeric_parity")


def oracle_sql_anomaly_series(long: pd.DataFrame) -> OracleRowSet:
    roles = {"sat", "mat", "rat", "oa_t", "web_oa_t", "zone_t", "dsp"}
    sub = long[long["role"].isin(roles)]
    rows: list[tuple[Any, ...]] = []
    for (eid, role, key), grp in sub.groupby(["equipment_id", "role", "openfdd_key"], sort=True):
        vals = grp["val"]
        std = float(vals.std(ddof=1)) if len(vals) > 1 else None
        rows.append((eid, role, key, int(len(vals)), 0, std))
    rows.sort(key=lambda r: (r[0], r[1], r[2]))
    return OracleRowSet(rows, (0, 1, 2), (3, 5), "numeric_parity")


def oracle_sql_anomaly_zscore(
    long: pd.DataFrame, *, window_rows: int, z_threshold: float, transition_events: bool
) -> OracleRowSet:
    roles = {"sat", "mat", "rat", "oa_t", "web_oa_t", "zone_t", "dsp"}
    sub = long[long["role"].isin(roles)].sort_values(["openfdd_key", "ts"])
    events: list[tuple[Any, ...]] = []
    n_scored = n_flagged = n_ok = 0
    for _key, grp in sub.groupby("openfdd_key", sort=False):
        vals = grp["val"].to_numpy(dtype=float)
        tss = grp["ts"].tolist()
        flagged: list[bool] = []
        for i in range(len(vals)):
            if i < window_rows:
                continue
            window = vals[i - window_rows : i]
            if len(window) < window_rows:
                continue
            std = float(np.std(window, ddof=1))
            if std <= 0:
                continue
            mean = float(np.mean(window))
            z = abs((vals[i] - mean) / std)
            n_scored += 1
            is_anom = z >= z_threshold
            flagged.append(is_anom)
            if is_anom:
                n_flagged += 1
                prev = flagged[-2] if len(flagged) > 1 else False
                if not transition_events or not prev:
                    events.append(
                        (
                            n_scored,
                            n_flagged,
                            n_ok,
                            len(events) + 1,
                            grp.iloc[i]["equipment_id"],
                            grp.iloc[i]["role"],
                            tss[i],
                            vals[i],
                            mean,
                            std,
                            z,
                            True,
                        )
                    )
            else:
                n_ok += 1
    if n_scored == 0:
        row = (0, 0, 0, 0, None, None, None, None, None, None, None, None)
        return OracleRowSet((row,), (0,), (0, 1, 2, 3), "numeric_parity")
    # SQL returns one counts row joined with events; compare first row counts + event keys separately
    head = (n_scored, n_flagged, n_ok, len(events), None, None, None, None, None, None, None, None)
    out = [head] + events[:2000]
    return OracleRowSet(tuple(out), (0, 1, 2, 3), (0, 1, 2, 3), "numeric_parity")


def oracle_bas_vs_web_oat(
    long: pd.DataFrame, *, equipment_id: str, oa_key: str, max_age_s: float, limit: int
) -> OracleRowSet:
    bas = long[(long["role"] == "oa_t") & (long["openfdd_key"] == oa_key)]
    web = long[long["role"] == "web_oa_t"]
    if bas.empty or web.empty:
        return OracleRowSet((), (0, 1), (2, 3, 4), "numeric_parity")
    web = web.sort_values("ts")
    rows: list[tuple[Any, ...]] = []
    for _, brow in bas.sort_values("ts", ascending=False).iterrows():
        wsub = web[web["ts"] <= brow["ts"]]
        if wsub.empty:
            continue
        wrow = wsub.iloc[-1]
        age = (brow["ts"] - wrow["ts"]).total_seconds()
        if age > max_age_s:
            continue
        rows.append(
            (
                brow["ts"],
                equipment_id,
                brow["val"],
                wrow["val"],
                brow["val"] - wrow["val"],
            )
        )
        if len(rows) >= limit:
            break
    return OracleRowSet(tuple(rows), (0, 1), (2, 3, 4), "numeric_parity")


def oracle_motor_weekly_runtime(
    si_frame: pd.DataFrame, *, equipment_id: str, equip_type: str
) -> OracleRowSet:
    from open_fdd.analytics.core import motor_run_hours_weekly

    role_map = {
        equipment_id: {
            "equipType": equip_type,
            "fan-status": "fan-status",
            "fan-cmd": "fan-cmd",
            "pump-status": "pump-status",
            "pump-cmd": "pump-cmd",
        }
    }
    weekly = motor_run_hours_weekly({equipment_id: si_frame}, role_map)
    if weekly is None or weekly.empty:
        return OracleRowSet((), (0, 3, 4), (6, 7), "numeric_parity")
    rows: list[tuple[Any, ...]] = []
    for _, row in weekly.iterrows():
        pg = str(row.get("plant_group") or "air")
        signal = str(row.get("signal") or "")
        if "fan" in signal:
            pg = "air"
        rows.append(
            (
                equipment_id,
                "motor",
                signal.replace("-", "_") if "-" in signal else signal,
                pg,
                pd.Timestamp(row["week_start"]).tz_localize("UTC")
                if pd.Timestamp(row["week_start"]).tzinfo is None
                else pd.Timestamp(row["week_start"]).tz_convert("UTC"),
                str(row.get("week_label") or ""),
                float(row.get("hours") or 0.0),
                float(row.get("hours") or 0.0),
            )
        )
    return OracleRowSet(tuple(rows[:500]), (0, 2, 4), (6, 7), "numeric_parity")


def build_oracle_for_stem(
    stem: str,
    *,
    si_frame: pd.DataFrame,
    equipment_id: str,
    equip_type: str,
    ws: str | None,
    we: str | None,
    extra: dict[str, Any] | None = None,
) -> OracleRowSet | None:
    extra = extra or {}
    long = _window_filter(_melt_si_frame(si_frame, equipment_id), ws, we)

    builders: dict[str, Callable[[], OracleRowSet]] = {
        "plant_health_inventory": lambda: oracle_plant_health_inventory(
            equipment_id=equipment_id, equip_type=equip_type
        ),
        "sensor_stats": lambda: oracle_sensor_stats(long),
        "diurnal_hourly": lambda: oracle_diurnal_hourly(long),
        "role_timeseries": lambda: oracle_role_timeseries(
            long, role=str(extra.get("role") or "fan_status"), limit=int(extra.get("limit") or 500)
        ),
        "schedule_occupancy": lambda: oracle_schedule_occupancy(long),
        "setpoints_snapshot": lambda: oracle_setpoints_snapshot(long),
        "pid_hunting_proxy": lambda: oracle_pid_hunting_proxy(long),
        "rcx_preset_role_coverage": lambda: oracle_rcx_preset_role_coverage(long),
        "topology_equipment": lambda: oracle_topology_equipment(
            long, equipment_id=equipment_id, equip_type=equip_type
        ),
        "fuel_daily": lambda: oracle_fuel_or_metering(long, fuel=True),
        "metering_kwh": lambda: oracle_fuel_or_metering(long, fuel=False),
        "mv_change_point_daily": lambda: oracle_mv_change_point_daily(long),
        "sql_anomaly_series": lambda: oracle_sql_anomaly_series(long),
        "sql_anomaly_zscore": lambda: oracle_sql_anomaly_zscore(
            long,
            window_rows=int(extra.get("window_rows") or 20),
            z_threshold=float(extra.get("z_threshold") or 3.0),
            transition_events=bool(extra.get("transition_events")),
        ),
        "bas_vs_web_oat": lambda: oracle_bas_vs_web_oat(
            long,
            equipment_id=equipment_id,
            oa_key=str(extra.get("oa_key") or f"{equipment_id}.oa_t"),
            max_age_s=float(extra.get("max_age_s") or 7200.0),
            limit=int(extra.get("limit") or 500),
        ),
        "motor_weekly_runtime": lambda: oracle_motor_weekly_runtime(
            si_frame, equipment_id=equipment_id, equip_type=equip_type
        ),
    }
    fn = builders.get(stem)
    if fn is None:
        return None
    return fn()
