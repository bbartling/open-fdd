"""W4f analytics SI parity (#1284): P1 (pandas IP vs pandas SI) and P2 (pandas SI vs SQL SI).

Every one of the 19 ``sql/analytics/postgres/queries/*.sql`` stems is compared per
dataset x equipment x bucket (the stem's key columns).  Keys must match exactly;
text, bool and timestamp cells must match exactly; numeric cells must agree within
the plan's documented ``ANALYTICS_REL_TOL`` (1e-6 relative).  No None->0 coercion,
no absolute tolerances, no row truncation.

SQL SI rows are frozen in ``tests/fixtures/si_cutover/analytics_si_goldens.json``
(regenerated against Timescale with ``--regen``) so the offline gate needs no DB.
Pandas IP and pandas SI rows are recomputed from the fixtures on every run so a
parameter mutation (T1284-4) is visible to P1.
"""

from __future__ import annotations

import argparse
import datetime as dt
import decimal
import json
import math
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

ANALYTICS_GOLDENS_PATH = REPO / "tests" / "fixtures" / "si_cutover" / "analytics_si_goldens.json"
GOLDEN_SCHEMA = "openfdd.analytics_si_goldens.v1"
STALE_AGE = dt.timedelta(hours=24)

# Column kinds:
#   key            bucket/identity column (exact)
#   text / bool    exact
#   ts             timestamp, compared as UTC ISO string
#   count          dimensionless number (counts, hours, percent-free ratios)
#   abs:<role>     absolute value in the unit of <role>; "@" = the row's ``role`` column
#   delta:<role>   difference/spread in the unit of <role>; "@" = the row's ``role`` column
STEM_COLUMNS: dict[str, tuple[tuple[str, str], ...]] = {
    "bas_vs_web_oat": (
        ("ts", "key"), ("equipment_id", "key"), ("bas_oa_t", "abs:oa_t"),
        ("web_oa_t", "abs:web_oa_t"), ("delta_f", "delta:oa_t"),
    ),
    "diurnal_hourly": (
        ("equipment_id", "key"), ("role", "key"), ("openfdd_key", "key"), ("hour_utc", "key"),
        ("avg_val", "abs:@"), ("n", "count"),
    ),
    "economizer_deltas": (
        ("ts", "key"), ("equipment_id", "key"), ("oa_t", "abs:oa_t"), ("rat", "abs:rat"),
        ("mat", "abs:mat"), ("sat", "abs:sat"), ("oa_damper_pct", "abs:oa_damper_pct"),
        ("delta_or_f", "delta:oa_t"), ("delta_mr_f", "delta:mat"), ("mat_resid_f", "delta:mat"),
        ("fan_on", "bool"), ("identifiable", "bool"),
    ),
    "fuel_daily": (
        ("equipment_id", "key"), ("role", "key"), ("openfdd_key", "key"), ("day_utc", "key"),
        ("n", "count"), ("min_val", "abs:@"), ("max_val", "abs:@"), ("avg_val", "abs:@"),
        ("delta_val", "delta:@"),
    ),
    "mechanical_cooling_oat_bins": (
        ("kind", "key"), ("equipment_id", "key"), ("oat_bin", "key"), ("run_hours", "count"),
    ),
    "metering_kwh": (
        ("equipment_id", "key"), ("role", "key"), ("openfdd_key", "key"), ("day_utc", "key"),
        ("n", "count"), ("min_val", "abs:@"), ("max_val", "abs:@"), ("avg_val", "abs:@"),
        ("delta_val", "delta:@"),
    ),
    "motor_weekly_runtime": (
        ("equipment_id", "key"), ("kind", "key"), ("signal", "key"), ("plant_group", "key"),
        ("week_start", "key"), ("week_label", "key"), ("run_hours", "count"),
        ("runtime_hours", "count"), ("n_observations", "count"), ("partial_week", "bool"),
    ),
    "mv_change_point_daily": (
        ("equipment_id", "key"), ("role", "key"), ("openfdd_key", "key"), ("day_utc", "key"),
        ("avg_val", "abs:@"), ("prev_avg", "abs:@"), ("delta_avg", "delta:@"), ("n", "count"),
        ("change_flag", "text"),
    ),
    "pid_hunting_proxy": (
        ("equipment_id", "key"), ("role", "key"), ("openfdd_key", "key"), ("n", "count"),
        ("avg_val", "abs:@"), ("stddev_val", "delta:@"), ("hunt_flag", "text"),
    ),
    "plant_health_inventory": (("equipment_id", "key"), ("equip_type", "text")),
    "rcx_preset_role_coverage": (
        ("equipment_id", "key"), ("role", "key"), ("openfdd_key", "key"), ("n", "count"),
        ("first_ts", "ts"), ("last_ts", "ts"),
    ),
    "role_timeseries": (
        ("ts", "key"), ("openfdd_key", "key"), ("val", "abs:@"), ("equipment_id", "text"),
        ("role", "text"),
    ),
    "schedule_occupancy": (
        ("ts", "key"), ("openfdd_key", "key"), ("val", "count"), ("equipment_id", "text"),
    ),
    "sensor_faults_staleness": (
        ("equipment_id", "key"), ("role", "key"), ("openfdd_key", "key"), ("n", "count"),
        ("last_ts", "ts"), ("min_val", "abs:@"), ("max_val", "abs:@"),
        ("stddev_val", "delta:@"), ("fault_flag", "text"),
    ),
    "sensor_stats": (
        ("equipment_id", "key"), ("role", "key"), ("openfdd_key", "key"), ("n", "count"),
        ("min_val", "abs:@"), ("max_val", "abs:@"), ("avg_val", "abs:@"),
        ("stddev_val", "delta:@"), ("first_ts", "ts"), ("last_ts", "ts"),
    ),
    "setpoints_snapshot": (
        ("equipment_id", "key"), ("role", "key"), ("openfdd_key", "key"), ("ts", "ts"),
        ("setpoint", "abs:@"),
    ),
    "sql_anomaly_series": (
        ("equipment_id", "key"), ("role", "key"), ("openfdd_key", "key"), ("n", "count"),
        ("n_null", "count"), ("stddev_val", "delta:@"),
    ),
    "sql_anomaly_zscore": (
        ("n_scored", "count"), ("n_flagged", "count"), ("n_ok", "count"),
        ("n_selected", "count"), ("equipment_id", "key"), ("role", "key"), ("ts", "key"),
        ("val", "abs:@"), ("avg_val", "abs:@"), ("stddev_val", "delta:@"),
        ("z_abs", "count"), ("transition", "bool"),
    ),
    "topology_equipment": (
        ("equipment_id", "key"), ("equip_type", "text"), ("parent_equipment_id", "text"),
        ("role_count", "count"), ("last_sample_ts", "ts"),
    ),
}


@dataclass(frozen=True)
class AnalyticsParam:
    """A unit-bearing analytics threshold: imperial value converted once to SI."""

    stem: str
    name: str
    ip_values: tuple[float, ...]
    quantity: str  # "absolute_temperature" | "temperature_delta"
    ip_unit: str


# Unit-bearing thresholds of the W4f analytics (SQL binds / literals and pandas twins).
ANALYTICS_PARAMS: tuple[AnalyticsParam, ...] = (
    AnalyticsParam("economizer_deltas", "dt_min", (10.0,), "temperature_delta", "degF"),
    AnalyticsParam(
        "mechanical_cooling_oat_bins", "oat_bin_edges",
        (50.0, 60.0, 70.0, 80.0, 90.0), "absolute_temperature", "degF",
    ),
    AnalyticsParam(
        "sensor_faults_staleness", "temp_range", (-40.0, 250.0), "absolute_temperature", "degF",
    ),
)

ParamHook = Callable[[AnalyticsParam, tuple[float, ...]], tuple[float, ...]]


def _metric() -> dict[str, Any]:
    from scripts.ci import unit_contract_lib as uc

    return uc.load_json(uc.METRIC_UNITS)


def _to_si(metric: dict[str, Any], quantity: str, value: float, unit: str) -> float:
    from scripts.ci import unit_contract_lib as uc

    if quantity == "temperature_delta":
        return uc.convert_to_canonical(metric, "absolute_temperature", value, unit) - (
            uc.convert_to_canonical(metric, "absolute_temperature", 0.0, unit)
        )
    return uc.convert_to_canonical(metric, quantity, value, unit)


def resolve_params(
    unit_system: str, metric: dict[str, Any], hook: ParamHook | None = None
) -> dict[str, dict[str, tuple[float, ...]]]:
    out: dict[str, dict[str, tuple[float, ...]]] = {}
    for p in ANALYTICS_PARAMS:
        if unit_system == "imperial":
            vals = p.ip_values
        else:
            vals = tuple(_to_si(metric, p.quantity, v, p.ip_unit) for v in p.ip_values)
            if hook is not None:
                vals = hook(p, vals)
        out.setdefault(p.stem, {})[p.name] = vals
    return out


def t1284_4_analytics_double_conversion(p: AnalyticsParam, si_vals: tuple[float, ...]) -> tuple[float, ...]:
    """T1284-4 mutation: convert the mech-cooling OAT bin edges to SI a second time."""
    if p.stem != "mechanical_cooling_oat_bins":
        return si_vals
    metric = _metric()
    return tuple(_to_si(metric, p.quantity, v, p.ip_unit) for v in si_vals)


# --------------------------------------------------------------------------- datasets


@dataclass(frozen=True)
class AnalyticsDataset:
    dataset_id: str
    building_id: str
    equipment_id: str
    equipment_type: str
    ip_frame: Any


def _synthetic_meter_frame():
    """Deterministic 4-day hourly meter + OAT frame (imperial units) covering the
    energy, change-point and BAS-vs-web OAT analytics no FDD golden exercises."""
    import pandas as pd

    idx = pd.date_range("2026-01-05T00:00:00Z", periods=96, freq="h")
    kwh: list[float] = []
    total = 1000.0
    oat: list[float] = []
    web: list[float] = []
    gas: list[float] = []
    zone: list[float] = []
    for i, _ts in enumerate(idx):
        day = i // 24
        hour = i % 24
        total += 12.5 + (30.0 if day == 2 else 0.0) + (hour % 6) * 0.75
        kwh.append(total)
        base = 38.0 if day < 2 else 71.0
        oat.append(base + 6.0 * math.sin(2.0 * math.pi * hour / 24.0))
        web.append(oat[-1] - 1.25 + 0.5 * (hour % 3))
        gas.append(4.0 + (2.5 if day == 1 else 0.0) + 0.1 * hour)
        zone.append(70.0 + (6.0 if day == 3 else 0.0) + 0.25 * (hour % 4))
    frame = pd.DataFrame(
        {
            "electric-kwh": kwh,
            "gas-therm": gas,
            "outside-air-temp": oat,
            "web-outside-air-temp": web,
            "zone-air-temp": zone,
        },
        index=idx,
    )
    return frame


SYNTH_METER_ID = "W4F_SYNTH_METER_OAT"


def iter_analytics_datasets() -> list[AnalyticsDataset]:
    from scripts.stress.si_cutover import ci_fixtures_lib as cfl
    from scripts.stress.si_cutover.parity_chain import load_all_ip_goldens

    out: list[AnalyticsDataset] = []
    for g in load_all_ip_goldens():
        raw, eid = cfl.reload_dataset_frame(g)
        bid = str(g["building_id"])
        et = str(g.get("equipment_type") or "ahu")
        ip = cfl.prepare_ip_frame(raw, building_id=bid, equipment_id=eid, equipment_type=et)
        out.append(AnalyticsDataset(bid, bid, eid, et, ip))
    ip = cfl.prepare_ip_frame(
        _synthetic_meter_frame(),
        building_id=SYNTH_METER_ID,
        equipment_id="METER_1",
        equipment_type="meter",
    )
    out.append(AnalyticsDataset(SYNTH_METER_ID, SYNTH_METER_ID, "METER_1", "meter", ip))
    return out


def window_of(frame) -> tuple[str | None, str | None]:
    if frame is None or len(frame.index) == 0:
        return None, None
    start = frame.index[0].tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ")
    end = frame.index[-1].tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ")
    return start, end


def role_units_of(ip_frame) -> dict[str, tuple[str, str]]:
    """SQL role -> (quantity, imperial unit) for unit-bearing columns of an IP frame."""
    from scripts.stress.si_cutover import ci_fixtures_lib as cfl

    out: dict[str, tuple[str, str]] = {}
    for col in ip_frame.columns:
        qu = cfl.column_quantity_unit(str(col))
        if qu is None:
            continue
        out[cfl.frame_column_to_sql_role(str(col))] = qu
    return out


# --------------------------------------------------------------------------- pandas side


def pandas_rows(
    stem: str,
    frame,
    *,
    ds: AnalyticsDataset,
    params: dict[str, dict[str, tuple[float, ...]]],
    as_of: dt.datetime,
) -> list[tuple[Any, ...]]:
    from scripts.stress.si_cutover import ci_analytics_oracles as cao

    ws, we = window_of(frame)
    long = cao._window_filter(cao._melt_si_frame(frame, ds.equipment_id), ws, we)
    if stem == "economizer_deltas":
        return cao.oracle_economizer_deltas(long, dt_min=params[stem]["dt_min"][0])
    if stem == "mechanical_cooling_oat_bins":
        return cao.oracle_mech_cooling_oat_bins(long, edges=params[stem]["oat_bin_edges"])
    if stem == "sensor_faults_staleness":
        lo, hi = params[stem]["temp_range"]
        return cao.oracle_sensor_faults_staleness(long, range_min=lo, range_max=hi, as_of=as_of)
    if stem == "motor_weekly_runtime":
        return cao.oracle_motor_weekly_runtime_sql(long, equip_type=ds.equipment_type)
    extra: dict[str, Any] = {}
    if stem == "bas_vs_web_oat":
        extra = {"oa_key": f"{ds.equipment_id}.oa_t", "max_age_s": 7200.0, "limit": 500}
    oracle = cao.build_oracle_for_stem(
        stem, si_frame=frame, equipment_id=ds.equipment_id, equip_type=ds.equipment_type,
        ws=ws, we=we, extra=extra,
    )
    if oracle is None:
        raise KeyError(f"no pandas analytics oracle for {stem!r}")
    return list(oracle.rows)


# --------------------------------------------------------------------------- normalization


def norm_cell(v: Any) -> Any:
    import numpy as np
    import pandas as pd

    if v is None:
        return None
    if isinstance(v, (bool, np.bool_)):
        return bool(v)
    if isinstance(v, (pd.Timestamp, dt.datetime)):
        ts = pd.Timestamp(v)
        if ts.tzinfo is None:
            raise ValueError(f"naive timestamp {v!r} in analytics row")
        return ts.tz_convert("UTC").isoformat()
    if isinstance(v, dt.date):
        return v.isoformat()
    if isinstance(v, (int, np.integer)):
        return int(v)
    if isinstance(v, (float, np.floating, decimal.Decimal)):
        f = float(v)
        if math.isnan(f):
            return None
        return f
    if isinstance(v, str):
        return v
    raise TypeError(f"unsupported analytics cell {type(v).__name__}: {v!r}")


def norm_rows(stem: str, rows: list[tuple[Any, ...]]) -> list[list[Any]]:
    width = len(STEM_COLUMNS[stem])
    out: list[list[Any]] = []
    for r in rows:
        if len(r) != width:
            raise ValueError(f"{stem}: row width {len(r)} != {width} columns")
        out.append([norm_cell(c) for c in r])
    return out


def _resolve_role(kind: str, row: list[Any], stem: str) -> str:
    role = kind.split(":", 1)[1]
    if role != "@":
        return role
    names = [c for c, _k in STEM_COLUMNS[stem]]
    return str(row[names.index("role")]) if "role" in names else str(row[names.index("openfdd_key")]).split(".", 1)[1]


def rows_ip_to_si(
    stem: str, rows: list[list[Any]], role_units: dict[str, tuple[str, str]], metric: dict[str, Any]
) -> list[list[Any]]:
    """Convert pandas-IP output cells to SI by declared column kind."""
    out: list[list[Any]] = []
    for row in rows:
        new = list(row)
        for i, (_name, kind) in enumerate(STEM_COLUMNS[stem]):
            if not (kind.startswith("abs:") or kind.startswith("delta:")) or row[i] is None:
                continue
            role = _resolve_role(kind, row, stem)
            qu = role_units.get(role)
            if qu is None:
                continue  # role carries no unit (percent/status/energy): identity
            quantity, unit = qu
            if kind.startswith("delta:"):
                q = "temperature_delta" if quantity == "absolute_temperature" else quantity
            else:
                q = quantity
            new[i] = _to_si(metric, q, float(row[i]), unit)
        out.append(new)
    return out


def _key(stem: str, row: list[Any]) -> tuple[Any, ...]:
    return tuple(row[i] for i, (_n, k) in enumerate(STEM_COLUMNS[stem]) if k == "key")


def _row_scale(stem: str, row: list[Any]) -> float:
    """Value magnitude of a row: max |abs-kind numeric cell| (0 when none)."""
    mags = [
        abs(float(v))
        for (_n, kind), v in zip(STEM_COLUMNS[stem], row)
        if kind.startswith("abs:") and isinstance(v, (int, float)) and not isinstance(v, bool)
    ]
    return max(mags, default=0.0)


def cells_equal(a: Any, b: Any, *, kind: str = "", scale: float = 0.0) -> bool:
    from scripts.stress.si_cutover.parity_chain import (
        analytics_relative_equal,
        analytics_spread_equal,
    )

    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if kind.startswith("delta:"):
            return analytics_spread_equal(float(a), float(b), scale)
        return analytics_relative_equal(float(a), float(b))
    return type(a) is type(b) and a == b


def compare_rows(
    stage: str, cell: str, stem: str, left_name: str, left: list[list[Any]],
    right_name: str, right: list[list[Any]],
) -> tuple[int, list[str]]:
    errors: list[str] = []
    names = [c for c, _k in STEM_COLUMNS[stem]]
    lk: dict[tuple[Any, ...], list[Any]] = {}
    rk: dict[tuple[Any, ...], list[Any]] = {}
    for side, rows, target in ((left_name, left, lk), (right_name, right, rk)):
        for r in rows:
            k = _key(stem, r)
            if k in target:
                errors.append(f"{stage} {cell} {stem}: duplicate {side} key {k!r}")
            target[k] = r
    comparisons = 0
    for k in sorted(set(lk) | set(rk), key=repr):
        comparisons += 1
        if k not in rk:
            errors.append(f"{stage} {cell} {stem} {k!r}: {right_name} missing row")
            continue
        if k not in lk:
            errors.append(f"{stage} {cell} {stem} {k!r}: {left_name} missing row")
            continue
        scale = max(_row_scale(stem, lk[k]), _row_scale(stem, rk[k]))
        for i, name in enumerate(names):
            kind = STEM_COLUMNS[stem][i][1]
            if not cells_equal(lk[k][i], rk[k][i], kind=kind, scale=scale):
                errors.append(
                    f"{stage} {cell} {stem} {k!r} {name}: {left_name}={lk[k][i]!r} {right_name}={rk[k][i]!r}"
                )
    return comparisons, errors


# --------------------------------------------------------------------------- golden I/O


def load_analytics_goldens(path: Path = ANALYTICS_GOLDENS_PATH) -> dict[str, Any]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("schema") != GOLDEN_SCHEMA:
        raise ValueError(f"{path}: schema {doc.get('schema')!r} != {GOLDEN_SCHEMA!r}")
    return doc


def stems_in_scope(scope: set[str] | None) -> tuple[str, ...]:
    from scripts.stress.si_cutover.ci_analytics_p2 import all_analytics_sql_stems

    stems = all_analytics_sql_stems()
    if set(stems) != set(STEM_COLUMNS):
        raise ValueError(
            f"STEM_COLUMNS {sorted(STEM_COLUMNS)} != analytics queries {sorted(stems)}"
        )
    if scope is None:
        return stems
    unknown = scope - set(stems)
    if unknown:
        raise KeyError(f"unknown analytics queries in scope: {sorted(unknown)}")
    return tuple(s for s in stems if s in scope)


# --------------------------------------------------------------------------- stages


def run_analytics_stages(
    *, scope: set[str] | None, param_hook: ParamHook | None = None,
    goldens_path: Path = ANALYTICS_GOLDENS_PATH,
):
    """Return (P1-analytics, P2-analytics) StageResults for the given query scope."""
    from scripts.stress.si_cutover import ci_fixtures_lib as cfl
    from scripts.stress.si_cutover.parity_chain import StageResult

    metric = _metric()
    golden = load_analytics_goldens(goldens_path)
    as_of = dt.datetime.fromisoformat(str(golden["evaluated_at"]))
    by_ds = {str(d["dataset_id"]): d for d in golden["datasets"]}
    stems = stems_in_scope(scope)
    ip_params = resolve_params("imperial", metric)
    si_params = resolve_params("metric", metric, param_hook)
    p1_err: list[str] = []
    p2_err: list[str] = []
    p1_n = p2_n = 0
    p1_rows: dict[str, int] = {s: 0 for s in stems}
    p2_rows: dict[str, int] = {s: 0 for s in stems}
    for ds in iter_analytics_datasets():
        gds = by_ds.get(ds.dataset_id)
        if gds is None:
            p2_err.append(f"P2-analytics {ds.dataset_id}: no SQL SI golden (run --regen)")
            continue
        si_frame = cfl.frame_to_si(ds.ip_frame, metric)
        units = role_units_of(ds.ip_frame)
        for stem in stems:
            cell = f"{ds.dataset_id}/{ds.equipment_id}"
            pd_si = norm_rows(stem, pandas_rows(stem, si_frame, ds=ds, params=si_params, as_of=as_of))
            pd_ip = norm_rows(stem, pandas_rows(stem, ds.ip_frame, ds=ds, params=ip_params, as_of=as_of))
            pd_ip_si = rows_ip_to_si(stem, pd_ip, units, metric)
            n, e = compare_rows("P1-analytics", cell, stem, "pandas_ip", pd_ip_si, "pandas_si", pd_si)
            p1_n += n
            p1_rows[stem] += n
            p1_err.extend(e)
            sstem = (gds.get("stems") or {}).get(stem)
            if sstem is None:
                p2_err.append(f"P2-analytics {cell} {stem}: no SQL SI golden rows (run --regen)")
                continue
            if list(sstem["columns"]) != [c for c, _k in STEM_COLUMNS[stem]]:
                p2_err.append(f"P2-analytics {cell} {stem}: golden columns {sstem['columns']} drifted")
                continue
            n, e = compare_rows("P2-analytics", cell, stem, "sql_si", sstem["sql_si"], "pandas_si", pd_si)
            p2_n += n
            p2_rows[stem] += n
            p2_err.extend(e)
    for stem in stems:
        if p1_rows[stem] == 0:
            p1_err.append(f"P1-analytics {stem}: zero compared rows across all datasets (no coverage)")
        if p2_rows[stem] == 0:
            p2_err.append(f"P2-analytics {stem}: zero compared rows across all datasets (no coverage)")
    coverage = [{"stem": s, "p1_rows": p1_rows[s], "p2_rows": p2_rows[s]} for s in stems]
    return (
        StageResult("P1-analytics", p1_n, tuple(p1_err), (), tuple(coverage)),
        StageResult("P2-analytics", p2_n, tuple(p2_err), (), tuple(coverage)),
    )


# --------------------------------------------------------------------------- DB regen / check


def sql_rows_for_dataset(conn, ds: AnalyticsDataset, metric: dict[str, Any], stems) -> dict[str, Any]:
    from scripts.stress.si_cutover import ci_analytics_p2 as cap2
    from scripts.stress.si_cutover import ci_fixtures_lib as cfl

    si_frame = cfl.frame_to_si(ds.ip_frame, metric)
    ws, we = window_of(si_frame)
    cap2._seed_si_site(
        conn, building_id=ds.building_id, equipment_id=ds.equipment_id,
        equip_type=ds.equipment_type, si_frame=si_frame,
    )
    out: dict[str, Any] = {}
    for stem in stems:
        with conn.cursor() as cur:
            rows = cap2._exec_analytics_sql(
                cur, stem, site_id=ds.building_id, window_start=ws, window_end=we,
                equipment_ids=[ds.equipment_id],
            )
            cols = [d.name for d in cur.description]
        expected = [c for c, _k in STEM_COLUMNS[stem]]
        if cols != expected:
            raise ValueError(f"{stem}: SQL columns {cols} != declared {expected}")
        out[stem] = {"columns": cols, "sql_si": norm_rows(stem, list(rows))}
        conn.commit()
    return out


def regen_goldens(conn, path: Path = ANALYTICS_GOLDENS_PATH) -> dict[str, Any]:
    metric = _metric()
    with conn.cursor() as cur:
        cur.execute("SELECT now()")
        now = cur.fetchone()[0]
    stems = stems_in_scope(None)
    doc = {
        "schema": GOLDEN_SCHEMA,
        "metric_profile": "metric-c-v2",
        "evaluated_at": norm_cell(now),
        "datasets": [],
    }
    for ds in iter_analytics_datasets():
        doc["datasets"].append(
            {
                "dataset_id": ds.dataset_id,
                "building_id": ds.building_id,
                "equipment_id": ds.equipment_id,
                "equipment_type": ds.equipment_type,
                "stems": sql_rows_for_dataset(conn, ds, metric, stems),
            }
        )
    path.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return doc


def check_goldens_against_db(conn, path: Path = ANALYTICS_GOLDENS_PATH) -> tuple[int, list[str]]:
    """Live SQL SI rows must equal the committed golden (except staleness flags, which
    depend on the DB clock and are recomputed against ``evaluated_at`` offline)."""
    metric = _metric()
    golden = load_analytics_goldens(path)
    by_ds = {str(d["dataset_id"]): d for d in golden["datasets"]}
    stems = stems_in_scope(None)
    n = 0
    errors: list[str] = []
    for ds in iter_analytics_datasets():
        live = sql_rows_for_dataset(conn, ds, metric, stems)
        gds = by_ds.get(ds.dataset_id)
        if gds is None:
            errors.append(f"golden missing dataset {ds.dataset_id}")
            continue
        for stem in stems:
            live_rows = live[stem]["sql_si"]
            gold_rows = gds["stems"][stem]["sql_si"]
            if stem == "sensor_faults_staleness":
                flag_i = [c for c, _k in STEM_COLUMNS[stem]].index("fault_flag")
                live_rows = [r[:flag_i] for r in live_rows]
                gold_rows = [r[:flag_i] for r in gold_rows]
                c, e = _compare_plain(stem, ds.dataset_id, gold_rows, live_rows)
            else:
                c, e = compare_rows("DB-golden", ds.dataset_id, stem, "golden", gold_rows, "live_sql", live_rows)
            n += c
            errors.extend(e)
    return n, errors


def _compare_plain(stem, cell, gold, live) -> tuple[int, list[str]]:
    errors: list[str] = []
    if len(gold) != len(live):
        errors.append(f"DB-golden {cell} {stem}: row count golden={len(gold)} live={len(live)}")
    gs = sorted(gold, key=repr)
    ls = sorted(live, key=repr)
    for g, l in zip(gs, ls):
        if len(g) != len(l) or not all(cells_equal(a, b) for a, b in zip(g, l)):
            errors.append(f"DB-golden {cell} {stem}: golden={g!r} live={l!r}")
    return max(len(gold), len(live)), errors


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--regen", action="store_true", help="rewrite the SQL SI analytics golden from Timescale")
    ap.add_argument("--check-db", action="store_true", help="verify the golden still matches live SQL")
    args = ap.parse_args(argv)
    if not (args.regen or args.check_db):
        p1, p2 = run_analytics_stages(scope=None)
        for st in (p1, p2):
            print(f"{st.stage}: comparisons={st.comparisons} errors={len(st.errors)}")
            for e in st.errors[:40]:
                print("  " + e)
        return 1 if (p1.errors or p2.errors) else 0
    from scripts.stress.si_cutover import ci_timescale_sql as cts

    dsn = os.environ.get("OPENFDD_TEST_DATABASE_URL") or os.environ.get("OPENFDD_DATABASE_URL")
    if not dsn:
        print("OPENFDD_TEST_DATABASE_URL is required for --regen/--check-db", file=sys.stderr)
        return 2
    conn = cts._load_parity_module().connect_with_retry(dsn)
    if args.regen:
        doc = regen_goldens(conn)
        print(f"wrote {ANALYTICS_GOLDENS_PATH.relative_to(REPO)} datasets={len(doc['datasets'])}")
        return 0
    n, errors = check_goldens_against_db(conn)
    print(f"DB-golden comparisons={n} errors={len(errors)}")
    for e in errors[:40]:
        print("  " + e)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
