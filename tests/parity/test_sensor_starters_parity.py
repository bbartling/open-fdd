"""#1763: per-sensor starters and overrides give the same per-sensor verdicts in pandas and in SQL on SQLite (stdlib
sqlite3), DuckDB and, when configured, standalone PostgreSQL (POSTGRES_TEST_URL + OPENFDD_PG_TEST_DISPOSABLE=1).

One AHU, 24 h at 5 min, six sensors (SI), two of them sharing the zone-air-temp role:

  zat-1  zone_air_temperature       22.0 + (0, .25, .5, .25) repeating: well controlled, never flat at the shipped tolerance
  zat-2  zone_air_temperature       same, stuck at 22.0 10:00-16:00, 40.0 18:00-19:00
  discharge_air_temperature-1  discharge_air_temperature          30 degC while off (proof 0 before 06:00), a 17.25 degC startup step, then 13 degC
  rh-1   outdoor_air_intake_relative_humidity         50 %RH + 1 %RH pattern
  dsp-1  discharge_air_static_pressure  250 Pa + 10 Pa pattern
  mixed_air_temperature-1  mixed_air_temperature          15 degC + pattern, no samples 14:00-16:00

Hand-calculated expectations are asserted on every engine; pandas must equal SQL per series for SV-RANGE, SV-SPIKE,
SV-FLATLINE and SV-STALE (SV-RATE has a known pandas difference: SQL engines only).
"""
from __future__ import annotations

import json
import math
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "sql" / "fdd"))
sys.path.insert(0, str(ROOT / "scripts" / "nf"))

import render_rule  # noqa: E402
from adapters import DuckDBAdapter, PostgresAdapter, postgres_configured  # noqa: E402
from build_sql_pack import to_sqlite  # noqa: E402
from open_fdd.parity import Policy  # noqa: E402
from open_fdd.parity.pandas_ref import pandas_rule_result, role_map  # noqa: E402
from open_fdd.rules import role_limit_overrides as o  # noqa: E402
from test_engine_matrix import _register_sqlite_udfs  # noqa: E402

EQ = "AHU-1"
STEP, N = 300, 288
START_MS = int(datetime(2026, 1, 5, tzinfo=timezone.utc).timestamp() * 1000)
PATTERN = (0.0, 0.25, 0.5, 0.25)
H = 1 / 3600.0
RULES = ("SV-RANGE", "SV-SPIKE", "SV-FLATLINE", "SV-STALE", "SV-RATE")
PANDAS_RULES = ("SV-RANGE", "SV-SPIKE", "SV-FLATLINE", "SV-STALE")
SQL_TO_HS = role_map()
PACK = json.loads((ROOT / "nf-app" / "rules" / "pack-postgres.json").read_text(encoding="utf-8"))


def _zat2(i: int) -> float:
    if 120 <= i < 192:
        return 22.0     # stuck 10:00-16:00
    if 216 <= i < 228:
        return 40.0     # 18:00-19:00 above the zone band (37.78 degC)
    return 22.0 + PATTERN[i % 4]


SENSORS = {
    "zat-1": ("zone_air_temperature", "°C", [22.0 + PATTERN[i % 4] for i in range(N)]),
    "zat-2": ("zone_air_temperature", "°C", [_zat2(i) for i in range(N)]),
    "discharge_air_temperature-1": ("discharge_air_temperature", "°C", [(30.0 if i < 72 else 13.0) + PATTERN[i % 4] for i in range(N)]),
    "rh-1": ("outdoor_air_intake_relative_humidity", "%RH", [50.0 + 2 * PATTERN[i % 4] for i in range(N)]),
    "dsp-1": ("discharge_air_static_pressure", "Pa", [250.0 + 20 * PATTERN[i % 4] for i in range(N)]),
    "mixed_air_temperature-1": ("mixed_air_temperature", "°C", [None if 168 <= i < 192 else 15.0 + PATTERN[i % 4] for i in range(N)]),
}
HISTORY = [{"equipment_id": EQ, "ts": START_MS + i * STEP * 1000, "operating_status": 0.0 if i < 72 else 1.0} for i in range(N)]
DATASET = SimpleNamespace(
    history_columns=[], history=HISTORY, weather=[], utility_interval=[], utility_monthly=[],
    sensor_history=[{"equipment_id": EQ, "series_id": sid, "sensor_role": role, "unit": unit, "ts": HISTORY[i]["ts"], "value": v}
                    for sid, (role, unit, values) in SENSORS.items() for i, v in enumerate(values)],
)

CONFIGS = {
    "shipped": None,
    # zat-1 at its own boundaries: max 22.5 == hi (no range fault), span 0.5 == flat_tol (flat: <= faults)
    "zat-1 at the boundary": {"version": 1, "roles": {}, "sensors": {
        "zat-1": {"role": "zone_air_temperature", "lo": 15.0, "hi": 22.5, "flat_tol": 0.5}}},
    # zat-1 just inside: 22.5 > hi 22.25 faults, span 0.5 > flat_tol 0.25 does not; 3 degC/h > its 2.5 degC/h rate
    "zat-1 past the boundary": {"version": 1, "roles": {}, "sensors": {
        "zat-1": {"role": "zone_air_temperature", "lo": 15.0, "hi": 22.25, "flat_tol": 0.25, "rate_per_h": 2.5}}},
}
ENERGIZED_HELD = 215 * STEP   # samples 06:00 .. 23:50 (the last sample holds 0 s)
EXPECTED = {   # (config, rule, series) -> fault hours ("shipped" rows hold for every config except zat-1); else 0
    ("shipped", "SV-RANGE", "zat-2"): 12 * STEP * H,
    ("shipped", "SV-SPIKE", "zat-2"): 2 * STEP * H,
    ("shipped", "SV-FLATLINE", "zat-2"): 61 * STEP * H,      # windows 11:00 .. 16:00 all 22.0
    ("shipped", "SV-STALE", "mixed_air_temperature-1"): (7500 - 1800) * H,     # 13:55 -> 16:00, less the 30 min threshold
    ("zat-1 at the boundary", "SV-FLATLINE", "zat-1"): ENERGIZED_HELD * H,
    ("zat-1 past the boundary", "SV-RANGE", "zat-1"): 54 * STEP * H,   # the energized 22.5 samples
}


def _sql(rid: str, limits) -> str:
    return render_rule.render(rid, 300, role_limits=limits)


def _limits(name):
    return o.effective_role_limits(equipment=CONFIGS[name]) if CONFIGS[name] else None


def _by_series(rows: list[dict]) -> dict[str, tuple]:
    return {r["series_id"]: (r["fault_hours"], r["covered_hours"]) for r in rows if r["equipment_id"] == EQ}


def _run_duckdb(rule_sql):
    pytest.importorskip("duckdb")
    ad = DuckDBAdapter()
    ad.load(DATASET)
    try:
        rows = ad.run(list(rule_sql), rule_sql=rule_sql)
    finally:
        ad.close()
    assert ad.stats["errors"] == {}, ad.stats["errors"]
    return {rid: _by_series(r) for rid, r in rows.items()}


def _run_sqlite(rule_sql):
    db = sqlite3.connect(":memory:")
    _register_sqlite_udfs(db)
    try:
        kinds = {"double": "REAL", "text": "TEXT", "timestamp": "REAL"}
        tables = {"history": HISTORY, "sensor_history": DATASET.sensor_history, "weather": [], "utility_interval": [],
                  "utility_monthly": [], "sweep_series": []}
        for table, rows in tables.items():
            spec = PACK["contract"][table]
            db.execute(f"CREATE TABLE {table} ({', '.join(chr(34) + c['name'] + chr(34) + ' ' + kinds[c['type']] for c in spec)})")
            if rows:
                db.executemany(f"INSERT INTO {table} VALUES ({', '.join('?' * len(spec))})",
                               [tuple(r["ts"] / 1000.0 if c["type"] == "timestamp" else r.get(c["name"]) for c in spec) for r in rows])
        out = {}
        for rid, sql in rule_sql.items():
            cur = db.execute(to_sqlite(sql)[0])
            names = [d[0] for d in cur.description]
            out[rid] = _by_series([dict(zip(names, r)) for r in cur.fetchall()])
        return out
    finally:
        db.close()


def _run_postgres(rule_sql):
    ad = PostgresAdapter()
    ad.load(DATASET)
    try:
        rows = ad.run(list(rule_sql), rule_sql=rule_sql)
    finally:
        ad.close()
    assert ad.stats["errors"] == {}, ad.stats["errors"]
    return {rid: _by_series(r) for rid, r in rows.items()}


def _pandas(limits) -> dict[str, dict[str, float]]:
    """{rule: {series_id: fault hours}}: each series is its own frame (one point per role column)."""
    idx = pd.DatetimeIndex(pd.to_datetime([r["ts"] for r in HISTORY], unit="ms", utc=True), name="timestamp_utc")
    proof = pd.Series([r["operating_status"] for r in HISTORY], index=idx, dtype=float)
    out: dict[str, dict[str, float]] = {rid: {} for rid in PANDAS_RULES}
    for sid, (role, unit, values) in SENSORS.items():
        hs = SQL_TO_HS[role]
        df = pd.DataFrame({hs: pd.Series(values, index=idx, dtype=float), SQL_TO_HS["operating_status"]: proof}, index=idx)
        df.attrs.update(equipment_id=EQ, run_proof_resolved=True, role_units={hs: unit}, series_ids={hs: sid})
        if limits is not None:
            df.attrs["sweep_limits"] = limits
        for rid in PANDAS_RULES:
            _, status, res = pandas_rule_result(rid, df, None, float(STEP))
            assert not status.startswith("ERROR"), (rid, sid, status)
            ev = [r for r in res.metrics.get("sv_sweep_evidence") or [] if r["role"] == hs]
            if ev:
                assert ev[0].get("series_id") == sid
                out[rid][sid] = float(ev[0]["fault_hours"])
    return out


ENGINES = {"sqlite": _run_sqlite, "duckdb": _run_duckdb}
if postgres_configured():
    ENGINES["postgres"] = _run_postgres


@pytest.fixture(scope="module")
def results():
    out = {}
    for name in CONFIGS:
        limits = _limits(name)
        rule_sql = {rid: _sql(rid, limits) for rid in RULES}
        out[name] = {"engines": {e: run(rule_sql) for e, run in ENGINES.items()}, "pandas": _pandas(limits)}
    return out


@pytest.mark.parametrize("config", list(CONFIGS))
def test_sql_engines_agree_and_match_the_hand_calculation(results, config):
    engines = results[config]["engines"]
    ref_name, ref = next(iter(engines.items()))
    for name, got in engines.items():
        for rid in RULES:
            assert set(got[rid]) == set(ref[rid]), (config, name, rid)
            for sid, (fh, ch) in got[rid].items():
                rf, rc = ref[rid][sid]
                assert (fh is None) == (rf is None) and math.isclose(fh or 0.0, rf or 0.0, abs_tol=1e-9), (config, name, rid, sid, fh, rf)
                assert math.isclose(ch or 0.0, rc or 0.0, abs_tol=1e-9), (config, name, rid, sid, ch, rc)
    for rid in RULES:
        for sid, (fh, _) in ref[rid].items():
            want = EXPECTED.get((config, rid, sid), EXPECTED.get(("shipped", rid, sid), 0.0) if sid != "zat-1" else 0.0)
            if rid == "SV-RATE" and config == "zat-1 past the boundary" and sid == "zat-1":
                assert fh > 0.0, "the sensor's own 2.5 degC/h rate reaches the SQL"
                continue
            assert fh == pytest.approx(want, abs=1e-9), (config, rid, sid, fh, want)


@pytest.mark.parametrize("config", list(CONFIGS))
def test_pandas_equals_sql_per_sensor(results, config):
    sql = next(iter(results[config]["engines"].values()))
    pandas = results[config]["pandas"]
    tol = Policy().abs_tol_h
    for rid in PANDAS_RULES:
        assert set(pandas[rid]) == set(sql[rid]), (config, rid, sorted(pandas[rid]), sorted(sql[rid]))
        for sid, (fh, _) in sql[rid].items():
            assert pandas[rid][sid] == pytest.approx(fh, abs=tol), (config, rid, sid, pandas[rid][sid], fh)


def test_two_points_of_one_role_are_independent(results):
    """Faulting zat-2 (data) leaves zat-1 clean; overriding zat-1 (config) leaves every zat-2 verdict unchanged."""
    for config in CONFIGS:
        for engine, got in results[config]["engines"].items():
            for rid in RULES:
                assert got[rid]["zat-2"] == results["shipped"]["engines"][engine][rid]["zat-2"], (config, engine, rid)
    for rid in RULES:
        assert results["shipped"]["engines"]["sqlite"][rid]["zat-1"][0] == 0.0, rid


def test_steady_readings_startup_step_and_missing_data_are_not_value_faults(results):
    """Negative controls: a well-controlled reading (0.5 degC span per hour) is not flat; a 17.25 degC startup step of
    the supply air is below its spike limit; a data gap is SV-STALE only (no range, spike or flatline time)."""
    got = results["shipped"]["engines"]["sqlite"]
    for sid in ("zat-1", "discharge_air_temperature-1", "rh-1", "mixed_air_temperature-1"):
        assert got["SV-FLATLINE"][sid][0] == 0.0, sid
    assert got["SV-SPIKE"]["discharge_air_temperature-1"][0] == 0.0 and got["SV-RANGE"]["discharge_air_temperature-1"][0] == 0.0
    assert "dsp-1" not in got["SV-FLATLINE"], "pressure has no flatline tolerance: not assessed"
    for rid in ("SV-RANGE", "SV-SPIKE", "SV-FLATLINE"):
        assert got[rid]["mixed_air_temperature-1"][0] == 0.0, rid
    assert got["SV-STALE"]["mixed_air_temperature-1"][0] > 0.0
