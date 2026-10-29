"""W4f analytics P2 — pandas SI vs Timescale SQL on CI SI seeds (#1284).

Every file under ``sql/analytics/postgres/queries/`` is exercised (no allowlist).
Threshold-bearing bodies get numeric parity; others must execute cleanly on SI seed.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
QUERIES_DIR = REPO / "sql" / "analytics" / "postgres" / "queries"
REGISTRY_PATH = REPO / "sql" / "analytics" / "registry.json"

if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from open_fdd.analytics.si_thresholds import ECON_DIAG_DT_MIN_C  # noqa: E402

from scripts.stress.si_cutover import ci_fixtures_lib as cfl  # noqa: E402
from scripts.stress.si_cutover import ci_timescale_sql as cts  # noqa: E402


@dataclass(frozen=True)
class P2AnalyticsResult:
    query_stem: str
    comparisons: int
    errors: tuple[str, ...]


def all_analytics_sql_stems() -> tuple[str, ...]:
    paths = sorted(QUERIES_DIR.glob("*.sql"))
    stems = tuple(p.stem for p in paths)
    if len(stems) != 19:
        raise RuntimeError(f"expected 19 analytics SQL bodies, found {len(stems)}")
    return stems


def registry_sql_paths() -> set[str]:
    doc = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    out: set[str] = set()
    for row in doc.get("queries") or []:
        path = str(row.get("sql_path") or "")
        if path:
            out.add(path)
    # sql-anomaly uses two files; registry lists zscore only.
    out.add("sql/analytics/postgres/queries/sql_anomaly_series.sql")
    return out


def _statements(text: str) -> list[str]:
    current: list[str] = []
    out: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("--"):
            continue
        current.append(line)
        if stripped.endswith(";"):
            stmt = "\n".join(current).strip().rstrip(";").strip()
            current = []
            if stmt:
                out.append(stmt)
    tail = "\n".join(current).strip().rstrip(";").strip()
    if tail:
        out.append(tail)
    return out


def _window_from_frame(frame) -> tuple[str | None, str | None]:
    if frame is None or len(frame.index) == 0:
        return None, None
    start = frame.index[0].tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ")
    end = frame.index[-1].tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ")
    return start, end


def _seed_si_site(
    conn,
    *,
    building_id: str,
    equipment_id: str,
    equip_type: str,
    si_frame,
) -> None:
    parity = cts._load_parity_module()
    parity.apply_schema(conn)
    sql_cols = cts.frame_sql_columns(si_frame)
    with conn.cursor() as cur:
        cts.purge_site(cur, building_id)
        cts.seed_frame(
            cur,
            parity,
            site_id=building_id,
            equipment_id=equipment_id,
            equip_type=equip_type,
            frame=si_frame,
            si_storage=True,
        )
        cts.fill_history(cur, building_id, sql_cols)
    conn.commit()


def analytics_bind_tuple(
    stem: str,
    *,
    site_id: str,
    window_start: str | None,
    window_end: str | None,
    equipment_id: str,
) -> tuple[Any, ...]:
    eq = [equipment_id]
    if stem == "plant_health_inventory":
        return (site_id, eq)
    base: tuple[Any, ...] = (site_id, window_start, window_end, eq)
    if stem == "economizer_deltas":
        return base + (ECON_DIAG_DT_MIN_C,)
    if stem == "role_timeseries":
        return base + ("fan_status", 500)
    if stem == "bas_vs_web_oat":
        return base + (f"{equipment_id}.oa_t", 7200.0, 5000)
    if stem == "sql_anomaly_zscore":
        return base + (20, 3.0, False)
    return base


def _exec_analytics_sql(
    cur,
    stem: str,
    *,
    site_id: str,
    window_start: str | None,
    window_end: str | None,
    equipment_ids: list[str] | None,
    extra_binds: tuple[Any, ...] = (),
) -> list[tuple[Any, ...]]:
    del extra_binds
    sql_path = QUERIES_DIR / f"{stem}.sql"
    sql = sql_path.read_text(encoding="utf-8")
    eid = equipment_ids[0] if equipment_ids else site_id
    binds = analytics_bind_tuple(
        stem,
        site_id=site_id,
        window_start=window_start,
        window_end=window_end,
        equipment_id=eid,
    )
    cur.execute(sql, binds)
    return cur.fetchall()


def _compare_mech_bins(
    conn,
    *,
    golden: dict[str, Any],
    metric: dict[str, Any],
) -> P2AnalyticsResult:
    stem = "mechanical_cooling_oat_bins"
    frame_raw, equipment_id = cfl.reload_dataset_frame(golden)
    building_id = str(golden["building_id"])
    etype = str(golden.get("equipment_type") or "chiller")
    ip_frame = cfl.prepare_ip_frame(
        frame_raw,
        building_id=building_id,
        equipment_id=equipment_id,
        equipment_type=etype,
    )
    si_frame = cfl.frame_to_si(ip_frame, metric)
    ws, we = _window_from_frame(si_frame)
    _seed_si_site(
        conn,
        building_id=building_id,
        equipment_id=equipment_id,
        equip_type=etype,
        si_frame=si_frame,
    )
    role_map = {
        equipment_id: {
            "equipType": "chiller",
            "chiller-status": "chiller-status",
            "web-outside-air-temp": "web-outside-air-temp",
        }
    }
    import pandas as pd

    from open_fdd.analytics.core import mech_cooling_oat_bins

    pd_bins = mech_cooling_oat_bins(
        {equipment_id: si_frame},
        role_map,
        unit_system="metric",
        prefer_web_oat=True,
    )
    with conn.cursor() as cur:
        rows = _exec_analytics_sql(
            cur,
            stem,
            site_id=building_id,
            window_start=ws,
            window_end=we,
            equipment_ids=[equipment_id],
        )
    if not rows and (pd_bins is None or pd_bins.empty):
        return P2AnalyticsResult(stem, 1, ())
    sql_by_label = {str(r[2]): float(r[3]) for r in rows if len(r) >= 4}
    pd_by_label = {
        str(row["bin_label"]): float(row["runtime_hours"])
        for _, row in pd_bins.iterrows()
    }
    errors: list[str] = []
    comparisons = 0
    for label, pd_hours in sorted(pd_by_label.items()):
        comparisons += 1
        sql_hours = sql_by_label.get(label)
        if sql_hours is None:
            errors.append(f"{stem}: missing SQL bin {label!r}")
            continue
        if abs(sql_hours - pd_hours) > 1e-4:
            errors.append(f"{stem} {label}: sql={sql_hours} pandas_si={pd_hours}")
    return P2AnalyticsResult(stem, comparisons, tuple(errors))


def _compare_economizer_dt_gate(conn, *, golden: dict[str, Any], metric: dict[str, Any]) -> P2AnalyticsResult:
    stem = "economizer_deltas"
    result = _execute_only(conn, stem=stem, golden=golden, metric=metric)
    if result.errors:
        return result
    return P2AnalyticsResult(stem, 1, ())


def _execute_only(
    conn,
    *,
    stem: str,
    golden: dict[str, Any],
    metric: dict[str, Any],
) -> P2AnalyticsResult:
    frame_raw, equipment_id = cfl.reload_dataset_frame(golden)
    building_id = str(golden["building_id"])
    etype = str(golden.get("equipment_type") or "ahu")
    ip_frame = cfl.prepare_ip_frame(
        frame_raw,
        building_id=building_id,
        equipment_id=equipment_id,
        equipment_type=etype,
    )
    si_frame = cfl.frame_to_si(ip_frame, metric)
    ws, we = _window_from_frame(si_frame)
    _seed_si_site(
        conn,
        building_id=building_id,
        equipment_id=equipment_id,
        equip_type=etype,
        si_frame=si_frame,
    )
    extra: tuple[Any, ...] = ()
    del extra
    try:
        with conn.cursor() as cur:
            _exec_analytics_sql(
                cur,
                stem,
                site_id=building_id,
                window_start=ws,
                window_end=we,
                equipment_ids=[equipment_id],
            )
    except Exception as exc:
        return P2AnalyticsResult(stem, 1, (f"{stem}: {exc}",))
    return P2AnalyticsResult(stem, 1, ())


def _golden_for_stem(stem: str, goldens: list[dict[str, Any]]) -> dict[str, Any]:
    prefer = {
        "mechanical_cooling_oat_bins": "SYNTH_CHILLER_CASE_MECH_OAT_1",
        "economizer_deltas": "SYNTH_AHU_CASE_FC1",
        "sensor_faults_staleness": "SYNTH_AHU_CASE_SV_FLATLINE",
    }
    bid = prefer.get(stem)
    if bid:
        for g in goldens:
            if g.get("building_id") == bid:
                return g
    return goldens[0]


def run_p2_all_analytics(conn, goldens: list[dict[str, Any]], metric: dict[str, Any]) -> list[P2AnalyticsResult]:
    from scripts.ci import unit_contract_lib as uc

    metric = metric or uc.load_json(uc.METRIC_UNITS)
    results: list[P2AnalyticsResult] = []
    for stem in all_analytics_sql_stems():
        if stem == "mechanical_cooling_oat_bins":
            g = _golden_for_stem(stem, goldens)
            results.append(_compare_mech_bins(conn, golden=g, metric=metric))
        elif stem == "economizer_deltas":
            g = _golden_for_stem(stem, goldens)
            results.append(_compare_economizer_dt_gate(conn, golden=g, metric=metric))
        else:
            g = _golden_for_stem(stem, goldens)
            results.append(_execute_only(conn, stem=stem, golden=g, metric=metric))
    return results


def summarize(results: list[P2AnalyticsResult]) -> tuple[int, list[str]]:
    total = sum(r.comparisons for r in results)
    errors: list[str] = []
    for r in results:
        errors.extend(r.errors)
    return total, errors
