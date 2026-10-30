"""Pandas SI oracles for W4f analytics P2 (#1284). Mirrors SQL row keys and numerics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Sequence

import numpy as np
import pandas as pd

from scripts.stress.si_cutover import ci_fixtures_lib as cfl
from scripts.stress.si_cutover import ci_timescale_sql as cts


@dataclass(frozen=True)
class OracleRowSet:
    rows: tuple[tuple[Any, ...], ...]
    key_columns: tuple[int, ...]
    numeric_columns: tuple[int, ...]
    comparison_type: str


def _melt_si_frame(si_frame: pd.DataFrame, equipment_id: str) -> pd.DataFrame:
    """Long sample rows matching Timescale seed (openfdd_key = equipment_id.role)."""
    records: list[dict[str, Any]] = []
    for col in si_frame.columns:
        if col == "equipment_id":
            continue
        if col == "occ_mode":
            role = "occ_mode"
            ser = si_frame[col].map(cts.occ_mode_value)
        else:
            role = cfl.frame_column_to_sql_role(str(col))
            ser = pd.to_numeric(si_frame[col], errors="coerce")
        key = f"{equipment_id}.{role}"
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
    """Mirror ``sql_anomaly_zscore.sql``: trailing-window z-score per series, global
    counts joined to every selected event (or one counts row when there are none)."""
    roles = {"sat", "mat", "rat", "oa_t", "web_oa_t", "zone_t", "dsp"}
    sub = long[long["role"].isin(roles)].sort_values(["openfdd_key", "ts"])
    events: list[tuple[Any, ...]] = []
    n_scored = n_flagged = 0
    for _key, grp in sub.groupby("openfdd_key", sort=True):
        vals = grp["val"].to_numpy(dtype=float)
        tss = grp["ts"].tolist()
        prev_anom: bool | None = None
        for i in range(window_rows, len(vals)):
            window = vals[i - window_rows : i]
            if not window.max() > window.min():
                continue
            std = float(np.std(window, ddof=1))
            mean = float(np.mean(window))
            z = abs((vals[i] - mean) / std)
            is_anom = bool(z >= z_threshold)
            n_scored += 1
            if is_anom:
                n_flagged += 1
                transition = prev_anom is not True
                if not transition_events or transition:
                    events.append(
                        (
                            grp.iloc[i]["equipment_id"], grp.iloc[i]["role"], tss[i],
                            float(vals[i]), mean, std, float(z), transition,
                        )
                    )
            prev_anom = is_anom
    head = (n_scored, n_flagged, n_scored - n_flagged, len(events))
    if not events:
        return OracleRowSet((head + (None,) * 8,), (4, 5, 6), (0, 1, 2, 3), "numeric_parity")
    events.sort(key=lambda e: (-e[6], -pd.Timestamp(e[2]).value, e[0], e[1]))
    rows = tuple(head + e for e in events[:2000])
    return OracleRowSet(rows, (4, 5, 6), (0, 1, 2, 3, 7, 8, 9, 10), "numeric_parity")


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


def _unique_role_pivot(long: pd.DataFrame, roles: Sequence[str]) -> pd.DataFrame:
    """Per (ts, equipment_id) wide rows of roles with exactly one series (SQL ``unique_role``)."""
    sub = long[long["role"].isin(roles)]
    if sub.empty:
        return pd.DataFrame(columns=["ts", "equipment_id", *roles])
    keys_per_role = sub.groupby(["equipment_id", "role"])["openfdd_key"].nunique()
    unique = {k for k, v in keys_per_role.items() if int(v) == 1}
    sub = sub[np.array([(e, r) in unique for e, r in zip(sub["equipment_id"], sub["role"])], dtype=bool)]
    wide = sub.pivot_table(index=["ts", "equipment_id"], columns="role", values="val", aggfunc="max")
    for r in roles:
        if r not in wide.columns:
            wide[r] = np.nan
    return wide.reset_index()


def oracle_economizer_deltas(long: pd.DataFrame, *, dt_min: float) -> list[tuple[Any, ...]]:
    roles = ("oa_t", "rat", "mat", "sat", "oa_damper_pct", "fan_status")
    w = _unique_role_pivot(long, roles)
    rows: list[tuple[Any, ...]] = []
    for r in w.itertuples(index=False):
        oa, rat, mat, fan = r.oa_t, r.rat, r.mat, r.fan_status
        if pd.isna(oa) or pd.isna(rat) or pd.isna(mat) or pd.isna(fan):
            continue
        if not float(fan) > 0.05 or not abs(float(oa) - float(rat)) >= dt_min:
            continue
        damper = None if pd.isna(r.oa_damper_pct) else float(r.oa_damper_pct)
        resid = None if damper is None else float(mat) - (float(rat) + (damper / 100.0) * (float(oa) - float(rat)))
        rows.append(
            (
                r.ts, r.equipment_id, float(oa), float(rat), float(mat),
                None if pd.isna(r.sat) else float(r.sat), damper,
                float(oa) - float(rat), float(mat) - float(rat), resid, True, True,
            )
        )
    rows.sort(key=lambda x: x[0], reverse=True)
    return rows[:2000]


def oracle_mech_cooling_oat_bins(long: pd.DataFrame, *, edges: Sequence[float]) -> list[tuple[Any, ...]]:
    labels = ("<10", "10-16", "16-21", "21-27", "27-32", ">=32")
    if len(edges) != len(labels) - 1:
        raise ValueError(f"mech OAT bins need {len(labels) - 1} edges, got {len(edges)}")
    comp_roles = ("chiller_status", "compressor_status", "chiller_cmd", "compressor_cmd")
    keys = long.groupby(["equipment_id", "role"])["openfdd_key"].nunique()
    unique = {k for k, v in keys.items() if int(v) == 1}
    oat_roles = [r for r in ("web_oa_t", "oa_t") if sum(1 for (_e, rr) in unique if rr == r) == 1]
    if not oat_roles:
        return []
    oat_role = oat_roles[0]
    oat = long[(long["role"] == oat_role) & np.array([(e, r) in unique for e, r in zip(long["equipment_id"], long["role"])], dtype=bool)]
    oat = oat.groupby("ts")["val"].max()
    comp = long[long["role"].isin(comp_roles) & np.array([(e, r) in unique for e, r in zip(long["equipment_id"], long["role"])], dtype=bool)]
    if comp.empty or oat.empty:
        return []
    active = comp.groupby(["equipment_id", "ts"])["val"].max().reset_index()
    active = active[active["ts"].isin(oat.index)]
    out: dict[tuple[str, str], float] = {}
    for eid, grp in active.groupby("equipment_id", sort=True):
        grp = grp.sort_values("ts")
        nxt = grp["ts"].shift(-1)
        for (_, r), n_ts in zip(grp.iterrows(), nxt):
            if not float(r["val"]) > 0.05:
                continue
            o = float(oat.loc[r["ts"]])
            idx = next((i for i, e in enumerate(edges) if o < e), len(edges))
            label = labels[idx]
            secs = 0.0
            if not pd.isna(n_ts):
                d = (n_ts - r["ts"]).total_seconds()
                if 0.0 < d <= 3600.0:
                    secs = d
            out[(str(eid), label)] = out.get((str(eid), label), 0.0) + secs
    rows = [("oat_bin", eid, label, secs / 3600.0) for (eid, label), secs in out.items()]
    rows.sort(key=lambda x: (x[1], x[2]))
    return rows[:500]


def oracle_sensor_faults_staleness(
    long: pd.DataFrame, *, range_min: float, range_max: float, as_of: Any
) -> list[tuple[Any, ...]]:
    stale_before = pd.Timestamp(as_of) - pd.Timedelta(hours=24)
    rows: list[tuple[Any, ...]] = []
    for (eid, role, key), grp in long.groupby(["equipment_id", "role", "openfdd_key"], sort=True):
        vals = grp["val"]
        n = int(len(vals))
        std = float(vals.std(ddof=1)) if n > 1 else None
        last = grp["ts"].max()
        mn, mx = float(vals.min()), float(vals.max())
        # SQL ``role LIKE '%_t'``: '_' is a single-char wildcard -> len >= 2 and ends with 't'.
        temp_like = len(role) >= 2 and role.endswith("t")
        if last < stale_before:
            flag, rank = "STALE", 0
        elif std is not None and std == 0 and n >= 12:
            flag, rank = "FLATLINE", 1
        elif (mn < range_min or mx > range_max) and temp_like:
            flag, rank = "RANGE", 2
        else:
            flag, rank = "OK", 3
        rows.append((rank, (eid, role, key, n, last, mn, mx, std, flag)))
    rows.sort(key=lambda x: (x[0], x[1][0], x[1][1], x[1][2]))
    return [r for _rank, r in rows][:2000]


def oracle_motor_weekly_runtime_sql(long: pd.DataFrame, *, equip_type: str) -> list[tuple[Any, ...]]:
    import re

    roles = ("fan_status", "fan_cmd", "pump_status", "pump_cmd")
    keys = long.groupby(["equipment_id", "role"])["openfdd_key"].nunique()
    unique = {k for k, v in keys.items() if int(v) == 1}
    sub = long[long["role"].isin(roles) & np.array([(e, r) in unique for e, r in zip(long["equipment_id"], long["role"])], dtype=bool)].copy()
    if sub.empty:
        return []
    sub["family"] = ["fan" if r in ("fan_status", "fan_cmd") else "pump" for r in sub["role"]]
    sub["rank"] = [1 if r in ("fan_status", "pump_status") else 2 for r in sub["role"]]
    best = sub.groupby(["equipment_id", "family"])["rank"].transform("min")
    sub = sub[sub["rank"] == best]
    rows: list[tuple[Any, ...]] = []
    boiler = re.search(r"(boiler|hot.?water|hw.?plant)", equip_type.lower()) is not None
    for (eid, signal), grp in sub.groupby(["equipment_id", "role"], sort=True):
        grp = grp.sort_values("ts").copy()
        grp["dt"] = (grp["ts"].shift(-1) - grp["ts"]).dt.total_seconds()
        grp["week"] = grp["ts"].dt.tz_convert("UTC").dt.tz_localize(None).dt.to_period("W-SUN").dt.start_time.dt.tz_localize("UTC")
        if signal.startswith("fan"):
            pg = "air"
        elif boiler:
            pg = "boiler"
        elif signal.startswith("pump"):
            pg = "chiller"
        else:
            pg = "air"
        for week, wk in grp.groupby("week", sort=True):
            run = wk[(wk["val"] > 0.05) & (wk["dt"] > 0.0) & (wk["dt"] <= 3600.0)]["dt"].sum() / 3600.0
            iso = week.isocalendar()
            rows.append(
                (
                    eid, "motor", signal, pg, week, f"{iso[0]:04d}-W{iso[1]:02d}",
                    float(run), float(run), int(len(wk)),
                    bool((wk["ts"].max() - wk["ts"].min()) < pd.Timedelta(days=6)),
                )
            )
    rows.sort(key=lambda x: (x[0], x[4]))
    return rows[:500]
