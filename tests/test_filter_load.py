"""#1783 FILTER-LOAD: pandas, DuckDB and (when configured) PostgreSQL give the answers of tests/fixtures/filter_load_cases.json.

PGlite and SQLite run the same cases in nf-app/tests/filter-load.test.mjs. pandas and DuckDB must also agree on the
per-timestamp confirmed mask.
"""
from __future__ import annotations

import json
import os
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from open_fdd.parity.pandas_ref import pandas_rule_result

ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / "tests/fixtures/filter_load_cases.json").read_text(encoding="utf-8"))["cases"]
ROLE_MAP = json.loads((ROOT / "sql/fdd/role_map.json").read_text(encoding="utf-8"))
PACK = json.loads((ROOT / "nf-app/rules/pack-postgres.json").read_text(encoding="utf-8"))
RULE = PACK["rules"]["FILTER-LOAD"]
START = datetime(2026, 1, 1, tzinfo=timezone.utc)
STATUS = {"no_filter_inputs": "SKIPPED_MISSING_ROLES", "insufficient_baseline": "NOT_ASSESSED_INSUFFICIENT_BASELINE"}


def _rows(case):
    n = case.get("n", 97)
    pattern = dict(case.get("pattern", {}))
    block = pattern.pop("block", 1)
    out = []
    for i in range(n):
        vals = dict(case["row"])
        vals.update({k: seq[(i // block) % len(seq)] for k, seq in pattern.items()})
        if i >= n // 2:
            vals.update(case.get("second_half", {}))
            vals.update({k: vals[k] * f for k, f in case.get("second_half_scale", {}).items()})
        out.append((START + pd.Timedelta(minutes=5 * i), {k: None if v is None else float(v) for k, v in vals.items()}))
    return out


def _frame(case):
    rows = _rows(case)
    d = pd.DataFrame([{ROLE_MAP[k]: v for k, v in vals.items()} for _, vals in rows],
                     index=pd.DatetimeIndex([ts for ts, _ in rows]))
    d.attrs.update({"equipment_id": "ahu-1", "site_id": "s", "run_proof_resolved": True})
    return d


def _check(case, row):
    if isinstance(case["expect"], str):
        assert row["assessment"] == case["expect"]
        assert row["fault_hours"] is None and row["covered_hours"] == 0
    else:
        assert row["assessment"] == "assessed" and row["filter_path"] == case["path"]
        assert row["fault_hours"] == pytest.approx(case["expect"], abs=1e-5)


def _history_cols():
    return [c["name"] for c in PACK["contract"]["history"]]


@pytest.fixture(scope="module")
def duck():
    duckdb = pytest.importorskip("duckdb")
    sys.path.insert(0, str(ROOT / "tests" / "parity"))
    from adapters import DUCKDB_HELPERS_SQL

    con = duckdb.connect(":memory:")
    con.execute("SET TimeZone = 'UTC'")
    con.execute(DUCKDB_HELPERS_SQL)
    ddl = ", ".join(f'"{c["name"]}" {"TIMESTAMPTZ" if c["type"] == "timestamp" else "VARCHAR" if c["type"] == "text" else "DOUBLE"}'
                    for c in PACK["contract"]["history"])
    out = {}
    for case in CASES:
        con.execute("DROP TABLE IF EXISTS history")
        con.execute(f"CREATE TABLE history ({ddl})")
        for ts, vals in _rows(case):
            cols = ["equipment_id", "timestamp_utc", *vals]
            con.execute(f"INSERT INTO history ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                        ["ahu-1", ts, *vals.values()])
        cur = con.execute(RULE["sql"])
        names = [d[0] for d in cur.description]
        row = dict(zip(names, cur.fetchone()))
        cur = con.execute(RULE["timeline_sql"])
        names = [d[0] for d in cur.description]
        timeline = [dict(zip(names, r)) for r in cur.fetchall()]
        out[case["id"]] = (row, {int(round(t["ts_epoch"])) for t in timeline if t["confirmed"] == 1})
    con.close()
    return out


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_pandas_matches_the_cases(case):
    hours, status, res = pandas_rule_result("FILTER-LOAD", _frame(case), None, 300.0)
    if isinstance(case["expect"], str):
        assert status == STATUS[case["expect"]], (status, res.notes if res else None)
        assert hours is None
    else:
        assert status in ("FAULT", "PASS"), status
        assert res.metrics["assessment"] == "assessed" and res.metrics["filter_path"] == case["path"]
        assert hours == pytest.approx(case["expect"], abs=1e-5)


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_duckdb_matches_the_cases_and_pandas(duck, case):
    row, sql_conf = duck[case["id"]]
    _check(case, row)
    _, _, res = pandas_rule_result("FILTER-LOAD", _frame(case), None, 300.0)
    if not isinstance(case["expect"], str):
        pd_conf = {int(ts.timestamp()) for ts, v in res.confirmed_fault.items() if v}
        assert pd_conf == sql_conf


def test_dp_threshold_is_tunable():
    case = next(c for c in CASES if c["id"] == "dp_low_pass")
    hours, status, _ = pandas_rule_result("FILTER-LOAD", _frame(case), None, 300.0, params={"dp_dirty": 74.652})
    assert status == "FAULT" and hours == pytest.approx(7.75, abs=1e-5)


def test_a_clean_filter_is_judged_like_with_like():
    """#1783 review: one baseline across every airflow would flag the clean filter's high-flow hours (kW per L/s at
    2000 L/s is 1.6 x that at 1000 L/s); the per-bin baseline does not, and still flags the loaded filter."""
    clean = next(c for c in CASES if c["id"] == "clean_filter_flow_swing")
    p = clean["pattern"]
    effort = [w / q for w, q in zip(p["fan_power"], p["zone_flow"])]
    assert max(effort) > 1.3 * min(effort)
    assert pandas_rule_result("FILTER-LOAD", _frame(clean), None, 300.0)[1] == "PASS"


@pytest.mark.skipif(not (os.environ.get("POSTGRES_TEST_URL") and os.environ.get("OPENFDD_PG_TEST_DISPOSABLE") == "1"),
                    reason="needs a disposable PostgreSQL (POSTGRES_TEST_URL, OPENFDD_PG_TEST_DISPOSABLE=1)")
def test_postgres_matches_the_cases():
    psycopg = pytest.importorskip("psycopg")
    from urllib.parse import urlparse, urlunparse

    base = os.environ["POSTGRES_TEST_URL"]
    db = f"openfdd_filter_load_{secrets.token_hex(4)}"
    with psycopg.connect(base, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{db}"')
    try:
        with psycopg.connect(urlunparse(urlparse(base)._replace(path=f"/{db}")), autocommit=True) as conn:
            conn.execute("SET TIME ZONE 'UTC'")
            conn.execute((ROOT / "sql/fdd/postgres/postgres_helpers.sql").read_text(encoding="utf-8"))
            ddl = ", ".join(f'"{c["name"]}" {"TIMESTAMPTZ" if c["type"] == "timestamp" else "VARCHAR" if c["type"] == "text" else "DOUBLE PRECISION"}'
                            for c in PACK["contract"]["history"])
            for case in CASES:
                conn.execute("DROP TABLE IF EXISTS history")
                conn.execute(f"CREATE TABLE history ({ddl})")
                for ts, vals in _rows(case):
                    cols = ["equipment_id", "timestamp_utc", *vals]
                    conn.execute(f"INSERT INTO history ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})",
                                 ["ahu-1", ts, *vals.values()])
                cur = conn.execute(RULE["sql"])
                names = [d[0] for d in cur.description]
                row = dict(zip(names, cur.fetchone()))
                row = {k: float(v) if hasattr(v, "as_integer_ratio") and not isinstance(v, (int, float)) else v
                       for k, v in row.items()}
                _check(case, row)
    finally:
        with psycopg.connect(base, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{db}" WITH (FORCE)')
