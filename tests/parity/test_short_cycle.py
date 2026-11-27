"""#1781 SHORT-CYCLE: boiler / compressor short cycling from proven run status, duty-aware.

Every case runs on the pandas twin and on the SQL pack (PGlite and SQLite through sql_run.mjs, DuckDB, and standalone
PostgreSQL when POSTGRES_TEST_URL + OPENFDD_PG_TEST_DISPOSABLE=1 are set) and must give the same answer. Expected fault
hours are derived by hand in the case comments (1 min samples unless noted; a sample holds until the next one).
"""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

import pandas as pd
import pytest

from adapters import DuckDBAdapter, NodeEngineAdapter, PostgresAdapter, postgres_configured
from open_fdd.parity import generate
from open_fdd.parity.pandas_ref import equip_frame, pandas_rule_result

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sql" / "fdd"))
sys.path.insert(0, str(ROOT / "scripts" / "nf"))
import render_rule  # noqa: E402

RID = "SHORT-CYCLE"
T0 = 1767571200000  # 2026-01-05 00:00 UTC


def _series(col, n, step_s, fn):
    return [{"ts": T0 + i * step_s * 1000, col: fn(i)} for i in range(n)]


# id -> (rows, expected fault hours | assessment string)
CASES = {
    # on 3 min / off 2 min: a start every 5 min (12/h), 180 s on-times. The third seen short cycle ends at min 17 and
    # the trailing hour holds >= 3 of them from then on: fault 17..180 min = 2.716667 h.
    "boiler_12_starts_180s": (_series("boiler_status", 181, 60, lambda m: 1.0 if m % 5 < 3 else 0.0), 2.716667),
    # 2 starts/h, 20 min on-times: pass
    "boiler_2_starts_20min": (_series("boiler_status", 181, 60, lambda m: 1.0 if m % 30 < 20 else 0.0), 0.0),
    # on-time exactly 600 s (10 x 60 s) is not short: pass (threshold edge)
    "compressor_on_600s_edge": (_series("compressor_status", 181, 60, lambda m: 1.0 if m % 20 < 10 else 0.0), 0.0),
    # 540 s on-times, 3 per hour: the third ends at min 68 -> fault 68..180 = 1.866667 h
    "compressor_on_540s": (_series("compressor_status", 181, 60, lambda m: 1.0 if m % 20 < 9 else 0.0), 1.866667),
    # 540 s on-times but only 2 per trailing hour: below min_short_cycles (edge) -> pass
    "compressor_two_short_per_hour": (_series("compressor_status", 181, 60, lambda m: 1.0 if m % 30 < 9 else 0.0), 0.0),
    # no status: chiller current above MECH_AMPS_MIN is the proof (same cycling as the first case)
    "chiller_amps_fallback": (_series("chiller_amps", 181, 60, lambda m: 50.0 if m % 5 < 3 else 0.0), 2.716667),
    # no run status, current or power at all: never a silent pass
    "no_run_status": (_series("hw_supply_t", 181, 60, lambda m: 60.0), "no_run_status"),
    # 15 min of firing per hour resampled to 1 h by AVERAGE: duty 0.25 every hour. Coarser than max_interval and the
    # start floor stays below the cap: not assessed, never a pass
    "hourly_duty_quarter": (_series("boiler_status", 25, 3600, lambda h: 0.25), "insufficient_trend"),
}

# parameter edges (run with overrides): starts every 10 min with 5 min on-times = exactly 6 starts per trailing hour
STARTS_6 = _series("boiler_status", 181, 60, lambda m: 1.0 if m % 10 < 5 else 0.0)
PARAM_CASES = {
    # 6 starts is not above a cap of 6: pass
    "starts_6_cap_6": (STARTS_6, {"max_starts_per_hour": 6.0, "min_short_cycles": 10.0, "min_on_seconds": 60.0}, 0.0),
    # cap 5: the 6th seen start is at min 60 -> fault 60..180 = 2.0 h
    "starts_6_cap_5": (STARTS_6, {"max_starts_per_hour": 5.0, "min_short_cycles": 10.0, "min_on_seconds": 60.0}, 2.0),
    # 16 min trend (coarser than 900 s), 30 % duty then off: each partial sample is a seen, completed 288 s cycle.
    # One short cycle is enough here, so the floor reaches the threshold: FAULT with the coarse-floor caveat
    "coarse_floor_fault": (_series("boiler_status", 46, 960, lambda i: 0.3 if i % 2 == 0 else 0.0),
                           {"min_short_cycles": 1.0}, "coarse_floor"),
}


def _dataset(cases: dict) -> object:
    base = generate(0, 1, 1)
    rows = []
    for eid, rs in cases.items():
        rows += [{"equipment_id": eid, **r} for r in rs]
    equipment = [{"building_id": "site-1", "equipment_id": eid} for eid in cases]
    return dataclasses.replace(base, history=rows, equipment=equipment, series=[], weather=[], authorized_series=[],
                               utility_monthly=[], utility_interval=[], equips=len(cases))


def _engines(ds, rule_sql: dict | None = None) -> dict[str, dict[str, dict]]:
    out = {}
    kinds = ["pglite"] if rule_sql else ["pglite", "sqlite"]
    for kind in kinds:
        ad = NodeEngineAdapter(kind)
        ad.load(ds)
        try:
            out[kind] = {r["equipment_id"]: r for r in ad.run([RID], rule_sql=rule_sql)[RID]}
        finally:
            ad.close()
    pytest.importorskip("duckdb")
    adapters = [DuckDBAdapter()] + ([PostgresAdapter()] if postgres_configured() else [])
    for ad in adapters:
        ad.load(ds)
        try:
            out[ad.name] = {r["equipment_id"]: r for r in ad.run([RID], rule_sql=rule_sql)[RID]}
            assert ad.stats["errors"] == {}, ad.stats["errors"]
        finally:
            ad.close()
    return out


def _pandas(ds, eid, params=None):
    df = equip_frame(ds, eid)
    return pandas_rule_result(RID, df, None, 60.0, params)


def _check(engines, ds, eid, expect, params=None):
    hours, status, res = _pandas(ds, eid, params)
    for name, rows in engines.items():
        row = rows[eid]
        if expect == "no_run_status":
            assert row["assessment"] == "no_run_status" and row["fault_hours"] is None and row["covered_hours"] == 0, (name, row)
        elif expect == "insufficient_trend":
            assert row["assessment"] == "insufficient_trend" and row["fault_hours"] is None, (name, row)
        elif expect == "coarse_floor":
            assert row["assessment"] == "coarse_floor" and row["fault_hours"] > 0, (name, row)
            assert row["fault_hours"] == pytest.approx(hours, abs=1e-6), (name, row, hours)
        else:
            assert row["assessment"] == "assessed", (name, row)
            assert row["fault_hours"] == pytest.approx(expect, abs=1e-5), (name, row)
    if expect == "no_run_status":
        assert status == "SKIPPED_MISSING_ROLES" and hours is None
    elif expect == "insufficient_trend":
        assert status == "NOT_ASSESSED_INSUFFICIENT_TREND" and hours is None
    elif expect == "coarse_floor":
        assert status == "FAULT" and res.metrics["assessment"] == "coarse_floor"
    else:
        assert status == ("FAULT" if expect > 0 else "PASS"), (status, res.notes if res else None)
        assert hours == pytest.approx(expect, abs=1e-5)


@pytest.fixture(scope="module")
def default_run():
    ds = _dataset({k: v[0] for k, v in CASES.items()})
    return ds, _engines(ds)


@pytest.mark.parametrize("case", list(CASES))
def test_short_cycle_pandas_equals_sql(default_run, case):
    ds, engines = default_run
    _check(engines, ds, case, CASES[case][1])


@pytest.mark.parametrize("case", list(PARAM_CASES))
def test_short_cycle_parameter_edges(case):
    rows, params, expect = PARAM_CASES[case]
    ds = _dataset({case: rows})
    sql = render_rule.render(RID, 300, overrides=params)
    _check(_engines(ds, {RID: sql}), ds, case, expect, params)


def test_duty_mean_not_max():
    """1 min 0/1 status with 15 min of firing per hour, resampled to 1 h: the mean keeps the duty (0.25); a max would read
    the boiler as on all hour and hide every start."""
    idx = pd.date_range("2026-01-05", periods=24 * 60, freq="1min", tz="UTC")
    status = pd.Series([1.0 if m % 60 < 15 else 0.0 for m in range(len(idx))], index=idx)
    hourly = status.resample("1h").mean()
    assert hourly.round(6).eq(0.25).all()
    assert status.resample("1h").max().eq(1.0).all()   # what max-aggregation would wrongly report
