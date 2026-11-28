"""#1782 HW-OAT-1 (hot-water summer lockout): pandas == SQL on DuckDB and, when POSTGRES_TEST_URL is set,
PostgreSQL, over tests/fixtures/hw_oat1_cases.json (threshold edges, proof choices, weather sidecar, not assessed)."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from open_fdd.parity.pandas_ref import pandas_rule_result

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads((ROOT / "tests/fixtures/hw_oat1_cases.json").read_text(encoding="utf-8"))
CASES = FIXTURE["cases"]
ROLE_MAP = {**json.loads((ROOT / "sql/fdd/role_map.json").read_text(encoding="utf-8")), "web_oa_t": "web-outside-air-temp"}
PACK = json.loads((ROOT / "nf-app/rules/pack-postgres.json").read_text(encoding="utf-8"))
START = int(datetime(2026, 7, 1, tzinfo=timezone.utc).timestamp())
STEP, N = 300, 49
RULE = "HW-OAT-1"


def _samples(case):
    """[(epoch seconds, {sql role: value})] for one case."""
    out = []
    for i in range(N):
        row = dict(case["row"])
        if "after" in case and i >= case["after"]["at"]:
            row.update(case["after"]["row"])
        out.append((START + i * STEP, row))
    return out


def _weather(case):
    return [(START + i * STEP, case["weather"]) for i in range(0, N, 3)] if "weather" in case else []


def _cols(pack, table):
    return [c for c in pack["contract"][table]]


def _sql_rows(run_sql, ts_value):
    """Each case in its own database (the weather sidecar is site-wide); {case id: result row}."""
    out = {}
    for case in CASES:
        rows = {"history": [(case["id"], ts_value(ts), vals) for ts, vals in _samples(case)],
                "weather": [(ts_value(ts), v) for ts, v in _weather(case)]}
        out[case["id"]] = run_sql(rows).get(case["id"])
    return out


def _create(con, pack, table, ts_type, text_type, double_type, temp=""):
    ddl = ", ".join(f'"{c["name"]}" {ts_type if c["type"] == "timestamp" else text_type if c["type"] == "text" else double_type}'
                    for c in _cols(pack, table))
    con.execute(f"CREATE {temp}TABLE {table} ({ddl})")


def _insert(con, rows, param):
    for eid, ts, vals in rows.get("history", []):
        names = ["equipment_id", "timestamp_utc", *vals]
        con.execute(f"INSERT INTO history ({', '.join(names)}) VALUES ({', '.join([param] * len(names))})",
                    [eid, ts, *[None if v is None else float(v) for v in vals.values()]])
    for ts, v in rows.get("weather", []):
        con.execute(f"INSERT INTO weather (timestamp_utc, web_oa_t) VALUES ({param}, {param})", [ts, float(v)])


def _query(con, rule):
    """The rule's result rows by equipment, each with its timeline rows (the FDD tab's fault lane) under "_timeline"."""
    cur = con.execute(rule["sql"])
    names = [d[0] for d in cur.description]
    out = {r[0]: {**dict(zip(names, r)), "_timeline": []} for r in cur.fetchall()}
    cur = con.execute(rule["timeline_sql"])
    names = [d[0] for d in cur.description]
    for r in cur.fetchall():
        row = dict(zip(names, r))
        out[row["equipment_id"]]["_timeline"].append(row)
    return out


def _duckdb(rows):
    duckdb = pytest.importorskip("duckdb")
    pack = PACK
    con = duckdb.connect(":memory:")
    try:
        con.execute("SET TimeZone = 'UTC'")
        for t in ("history", "weather"):
            _create(con, pack, t, "TIMESTAMPTZ", "VARCHAR", "DOUBLE")
        _insert(con, rows, "?")
        return _query(con, pack["rules"][RULE])
    finally:
        con.close()


def _postgres(rows):
    url = os.environ.get("POSTGRES_TEST_URL")
    if not url:
        pytest.skip("POSTGRES_TEST_URL not set")
    psycopg = pytest.importorskip("psycopg")
    pack = PACK
    with psycopg.connect(url) as con:   # temp tables only; rolled back on exit
        for t in ("history", "weather"):
            _create(con, pack, t, "TIMESTAMPTZ", "TEXT", "DOUBLE PRECISION", temp="TEMP ")
        _insert(con, rows, "%s")
        out = _query(con, pack["rules"][RULE])
        con.rollback()
    return out


def _utc(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc)


ENGINES = {"duckdb": lambda: _sql_rows(_duckdb, _utc), "postgres": lambda: _sql_rows(_postgres, _utc)}


@pytest.fixture(scope="module", params=list(ENGINES))
def engine_rows(request):
    return request.param, ENGINES[request.param]()


def _pandas(case):
    samples = _samples(case)
    idx = pd.DatetimeIndex([_utc(ts) for ts, _ in samples])
    df = pd.DataFrame([{ROLE_MAP[k]: float("nan") if v is None else float(v) for k, v in vals.items()} for _, vals in samples],
                      index=idx)
    df.attrs.update({"equipment_id": case["id"], "site_id": "s"})
    wx = _weather(case)
    weather = (pd.DataFrame({"web-outside-air-temp": [float(v) for _, v in wx]}, index=pd.DatetimeIndex([_utc(t) for t, _ in wx]))
               if wx else None)
    return pandas_rule_result(RULE, df, weather, float(STEP))


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_pandas_matches_the_fixture(case):
    hours, status, res = _pandas(case)
    if isinstance(case["expect"], str):
        assert status == "SKIPPED_MISSING_ROLES", (status, res.notes if res else None)
        assert hours is None
    else:
        assert status in ("FAULT", "PASS"), (status, res.notes if res else None)
        assert hours == pytest.approx(case["expect"], abs=1e-5)
        assert res.metrics.get("weather_source") == "web_dry_bulb"


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_sql_matches_the_fixture_and_pandas(engine_rows, case):
    engine, rows = engine_rows
    row = rows[case["id"]]
    if isinstance(case["expect"], str):
        assert row["assessment"] == case["expect"], (engine, row)
        assert row["fault_hours"] is None and row["fault_pct"] is None and row["covered_hours"] == 0, (engine, row)
        # never drawn as a clean no-fault lane: no timeline sample holds any time (the hook drops held_seconds 0)
        assert not [t for t in row["_timeline"] if float(t["held_seconds"]) > 0], (engine, row["_timeline"][:3])
        return
    assert row["assessment"] == "assessed", (engine, row)
    # the timeline (fault lane) carries exactly the confirmed fault time of the summary row
    lane = sum(float(t["held_seconds"]) for t in row["_timeline"] if t["confirmed"] == 1) / 3600.0
    assert lane == pytest.approx(float(row["fault_hours"]), abs=1e-6), (engine, lane)
    assert float(row["fault_hours"]) == pytest.approx(case["expect"], abs=1e-5), (engine, row)
    # an unknown sample (no OAT, or neither proof value) is not covered time
    assert float(row["covered_hours"]) == pytest.approx(case.get("covered", 4.0), abs=1e-9), (engine, row)
    hours, _status, _res = _pandas(case)
    assert float(row["fault_hours"]) == pytest.approx(hours, abs=1e-5), (engine, row, hours)


def test_pandas_proof_nulled_by_quality_is_skipped_not_pass():
    """A dead HW supply sensor reading a sentinel is quality-nulled: no proof left -> SKIPPED, never a PASS."""
    from open_fdd.rules import run_rule

    idx = pd.date_range("2026-07-01", periods=N, freq="5min", tz="UTC")
    df = pd.DataFrame({"web-outside-air-temp": [25.0] * N, "hot-water-supply-temp": [-999.0] * N}, index=idx)
    df.attrs.update({"equipment_id": "blr-1", "equipment_type": "boiler"})
    res = run_rule(RULE, df)
    assert res.status == "SKIPPED_MISSING_ROLES", (res.status, res.notes)
    assert res.fault_hours is None
    # a real pump-off 0 is still valid proof: assessed, no fault
    ok = pd.DataFrame({"web-outside-air-temp": [25.0] * N, "pump-status": [0.0] * N}, index=idx)
    ok.attrs.update({"equipment_id": "blr-1", "equipment_type": "boiler"})
    assert run_rule(RULE, ok).status == "PASS"
