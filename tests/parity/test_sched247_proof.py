"""#1670: SCHED-247 on DuckDB and the pandas reference over tests/fixtures/sched247_cases.json.

PGlite and SQLite run the same scenarios in nf-app/tests/sched247-proof.test.mjs. Here the DuckDB rendering of the
Postgres pack and the pandas rule must agree on assessment status, every duration, fault hours and the
per-timestamp confirmed mask, and both must match the expected values in the fixture.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd
import pytest

from open_fdd.rules import run_rule

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = json.loads((ROOT / "tests" / "fixtures" / "sched247_cases.json").read_text(encoding="utf-8"))
PACK = json.loads((ROOT / "nf-app" / "rules" / "pack-postgres.json").read_text(encoding="utf-8"))
TOL = FIXTURE["tolerance_hours"]
CASES = FIXTURE["cases"]
PARAMS = {"always_on_pct": FIXTURE["params"]["ALWAYS_ON_PCT"], "confirm_seconds": FIXTURE["params"]["CONFIRM_SECONDS"]}
DURATIONS = ("window_hours", "proven_on_hours", "proven_off_hours", "unknown_hours")


@pytest.fixture(scope="module")
def duck():
    duckdb = pytest.importorskip("duckdb")
    from adapters import DUCKDB_HELPERS_SQL

    con = duckdb.connect(":memory:")
    con.execute("SET TimeZone = 'UTC'")
    con.execute(DUCKDB_HELPERS_SQL)
    cols = PACK["contract"]["history"]
    ddl = ", ".join(f'"{c["name"]}" {"TIMESTAMPTZ" if c["type"] == "timestamp" else "VARCHAR" if c["type"] == "text" else "DOUBLE"}'
                    for c in cols)
    con.execute(f"CREATE TABLE history ({ddl})")
    from datetime import datetime, timezone

    for case in CASES:
        con.executemany(
            "INSERT INTO history (equipment_id, timestamp_utc, supply_fan_operating_status, supply_fan_command) VALUES (?, ?, ?, ?)",
            [(case["equipment_id"], datetime.fromtimestamp(r["ts"] / 1000, tz=timezone.utc), r["supply_fan_operating_status"], r["supply_fan_command"])
             for r in case["rows"]],
        )
    rule = PACK["rules"]["SCHED-247"]
    cur = con.execute(rule["sql"])
    names = [d[0] for d in cur.description]
    rows = {r[0]: dict(zip(names, r)) for r in cur.fetchall()}
    cur = con.execute(rule["timeline_sql"])
    names = [d[0] for d in cur.description]
    timeline = [dict(zip(names, r)) for r in cur.fetchall()]
    con.close()
    return rows, timeline


def _pandas(case):
    df = pd.DataFrame(case["rows"])
    df.index = pd.to_datetime(df.pop("ts"), unit="ms", utc=True)
    df = df.rename(columns={"supply_fan_operating_status": "supply_fan_operating_status", "supply_fan_command": "supply_fan_command"}).astype(float)
    df.attrs["equipment_id"] = case["equipment_id"]
    df.attrs["equipment_type"] = "ahu"
    return run_rule("SCHED-247", df, params=PARAMS)


def _close(a, b):
    if a is None or b is None:
        return a is None and b is None
    return math.isclose(float(a), float(b), abs_tol=TOL)


@pytest.mark.parametrize("case", CASES, ids=[c["equipment_id"] for c in CASES])
def test_duckdb_matches_expected(duck, case):
    row = duck[0][case["equipment_id"]]
    for key, want in case["expected"].items():
        if want is None and key == "window_hours":
            continue
        assert _close(row[key], want) if not isinstance(want, str) else row[key] == want, (key, row[key], want)


@pytest.mark.parametrize("case", CASES, ids=[c["equipment_id"] for c in CASES])
def test_pandas_matches_duckdb(duck, case):
    row = duck[0][case["equipment_id"]]
    res = _pandas(case)
    if res.status == "SKIPPED_MISSING_ROLES":
        # no proof role has a value anywhere: pandas skips before the rule runs, SQL reports no_proof
        assert row["assessment"] == "no_proof" and row["fault_hours"] is None and res.fault_hours is None
        return
    proof = res.metrics
    assert proof["assessment"] == row["assessment"]
    for key in DURATIONS:
        assert _close(proof[key], row[key]), (key, proof[key], row[key])
    if row["assessment"] == "assessed":
        assert res.status in ("PASS", "FAULT")
        # the public RuleResult rounds hours to 0.01 h; the exact samples are compared through the masks below
        assert math.isclose(res.fault_hours, row["fault_hours"], abs_tol=0.005), (res.fault_hours, row["fault_hours"])
    else:
        assert res.status == "NOT_ASSESSED_INSUFFICIENT_PROOF"
        assert res.fault_hours is None and row["fault_hours"] is None
    # per-timestamp confirmed mask: the same samples are fault samples on both sides
    sql_conf = {int(round(t["ts_epoch"])) for t in duck[1] if t["equipment_id"] == case["equipment_id"] and t["confirmed"] == 1}
    if res.confirmed_fault is not None and row["assessment"] == "assessed":
        pd_conf = {int(ts.timestamp()) for ts, v in res.confirmed_fault.items() if v}
        assert pd_conf == sql_conf
    else:
        assert not sql_conf


def test_unknown_proof_is_not_off(duck):
    """The #1670 core: all-missing proof is not an assessed zero, and is distinct from proven OFF."""
    rows = duck[0]
    assert rows["off_full_day"]["assessment"] == "assessed" and rows["off_full_day"]["fault_hours"] == 0
    assert rows["proof_missing_full_day"]["assessment"] == "no_proof"
    assert rows["proof_missing_full_day"]["fault_hours"] is None
    assert rows["proof_missing_full_day"]["covered_hours"] == 0
