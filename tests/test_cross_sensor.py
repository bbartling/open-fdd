"""#1780 cross-sensor consistency (XS-MIX, XS-COPY, XS-CLIP): pandas == SQL on SQLite, DuckDB and, when POSTGRES_TEST_URL
is set, PostgreSQL, over tests/fixtures/cross_sensor_cases.json (envelope and tolerance edges, fan proof, not assessed)."""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from open_fdd.parity.pandas_ref import pandas_rule_result

ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / "tests/fixtures/cross_sensor_cases.json").read_text(encoding="utf-8"))["cases"]
ROLE_MAP = json.loads((ROOT / "sql/fdd/role_map.json").read_text(encoding="utf-8"))
PACKS = {k: json.loads((ROOT / f"nf-app/rules/pack-{k}.json").read_text(encoding="utf-8")) for k in ("sqlite", "postgres")}
START = int(datetime(2026, 7, 1, tzinfo=timezone.utc).timestamp())
STEP, N = 300, 97
RULES = sorted({c["rule"] for c in CASES})


def _value(spec, i, row):
    if isinstance(spec, (int, float)):
        return float(spec)
    if "ramp" in spec:
        return spec["ramp"][0] + spec["ramp"][1] * i
    if "cycle" in spec:
        return float(spec["cycle"][i % len(spec["cycle"])])
    if "copy" in spec:
        return row[spec["copy"]] + spec["plus"]
    return _value(spec["before"] if i < spec["from"] else spec["value"], i, row)


def _samples(case):
    """[(epoch seconds, {sql role: value})]; copies resolve after the plain values."""
    out = []
    for i in range(N):
        row = {}
        specs = sorted(case["row"].items(), key=lambda kv: "copy" in json.dumps(kv[1]))
        for k, spec in specs:
            row[k] = _value(spec, i, row)
        for role, at in case.get("set", {}).items():
            if str(i) in at:
                row[role] = float(at[str(i)])
        out.append((START + i * STEP, row))
    return out


def _create(con, pack, ts_type, text_type, double_type, temp=""):
    cols = pack["contract"]["history"]
    ddl = ", ".join(f'"{c["name"]}" {ts_type if c["type"] == "timestamp" else text_type if c["type"] == "text" else double_type}'
                    for c in cols)
    con.execute(f"CREATE {temp}TABLE history ({ddl})")


def _insert(con, case, ts_value, param):
    for ts, vals in _samples(case):
        names = ["equipment_id", "timestamp_utc", *vals]
        con.execute(f"INSERT INTO history ({', '.join(names)}) VALUES ({', '.join([param] * len(names))})",
                    [case["id"], ts_value(ts), *vals.values()])


def _query(con, sql):
    cur = con.execute(sql)
    names = [d[0] for d in cur.description]
    return {r[0]: dict(zip(names, r)) for r in cur.fetchall()}


def _utc(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def _sqlite(case):
    pack = PACKS["sqlite"]
    con = sqlite3.connect(":memory:")
    try:
        _create(con, pack, "REAL", "TEXT", "REAL")
        _insert(con, case, float, "?")
        return _query(con, pack["rules"][case["rule"]]["sql"])[case["id"]]
    finally:
        con.close()


def _duckdb(case):
    duckdb = pytest.importorskip("duckdb")
    pack = PACKS["postgres"]
    con = duckdb.connect(":memory:")
    try:
        con.execute("SET TimeZone = 'UTC'")
        _create(con, pack, "TIMESTAMPTZ", "VARCHAR", "DOUBLE")
        _insert(con, case, _utc, "?")
        return _query(con, pack["rules"][case["rule"]]["sql"])[case["id"]]
    finally:
        con.close()


def _postgres(case):
    url = os.environ.get("POSTGRES_TEST_URL")
    if not url:
        pytest.skip("POSTGRES_TEST_URL not set")
    psycopg = pytest.importorskip("psycopg")
    pack = PACKS["postgres"]
    with psycopg.connect(url) as con:   # temp table only; rolled back on exit
        _create(con, pack, "TIMESTAMPTZ", "TEXT", "DOUBLE PRECISION", temp="TEMP ")
        _insert(con, case, _utc, "%s")
        out = _query(con, pack["rules"][case["rule"]]["sql"])[case["id"]]
        con.rollback()
    return out


ENGINES = {"sqlite": _sqlite, "duckdb": _duckdb, "postgres": _postgres}


def _pandas(case):
    samples = _samples(case)
    idx = pd.DatetimeIndex([_utc(ts) for ts, _ in samples])
    df = pd.DataFrame([{ROLE_MAP[k]: v for k, v in vals.items()} for _, vals in samples], index=idx)
    df.attrs.update({"equipment_id": case["id"], "site_id": "s", "run_proof_resolved": True})
    return pandas_rule_result(case["rule"], df, None, float(STEP))


def _not_assessed_status(case):
    if case["expect"] == "no_run_proof":
        return "SKIPPED_NO_RUN_PROOF"
    if case["rule"] == "XS-MIX":
        return "SKIPPED_MISSING_ROLES"   # a required temperature role is not bound
    return f"NOT_ASSESSED_{case['expect'].upper()}"


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_pandas_matches_the_fixture(case):
    hours, status, res = _pandas(case)
    if isinstance(case["expect"], str):
        assert status == _not_assessed_status(case), (status, res.notes if res else None)
        assert hours is None
    else:
        assert status in ("FAULT", "PASS"), (status, res.notes if res else None)
        assert hours == pytest.approx(case["expect"], abs=1e-5)


@pytest.mark.parametrize("engine", list(ENGINES))
@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_sql_matches_the_fixture_and_pandas(engine, case):
    row = ENGINES[engine](case)
    if isinstance(case["expect"], str):
        assert row["assessment"] == case["expect"], (engine, row)
        assert row["fault_hours"] is None and row["fault_pct"] is None and row["covered_hours"] == 0, (engine, row)
        return
    assert row["assessment"] == "assessed", (engine, row)
    assert float(row["fault_hours"]) == pytest.approx(case["expect"], abs=1e-5), (engine, row)
    assert float(row["covered_hours"]) == pytest.approx(8.0, abs=1e-9), (engine, row)
    hours, _status, _res = _pandas(case)
    assert float(row["fault_hours"]) == pytest.approx(hours, abs=1e-5), (engine, row, hours)


def test_every_rule_has_cases_and_the_pack_carries_it():
    assert RULES == ["XS-CLIP", "XS-COPY", "XS-MIX"]
    for rule in RULES:
        for kind in ("sqlite", "postgres"):
            assert rule in PACKS[kind]["rules"], (kind, rule)


def test_no_site_specific_names_in_the_sql():
    for name in ("xs_mix", "xs_copy", "xs_clip"):
        sql = (ROOT / f"sql/fdd/postgres/rules/{name}.sql").read_text(encoding="utf-8").lower()
        for banned in ("greatest(", "least(", "stddev", "sqrt("):
            assert banned not in sql, (name, banned)
