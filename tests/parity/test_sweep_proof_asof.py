"""#1631 on DuckDB: proof is the latest proof row at or before a sensor sample (held at most MAX_GAP_HOURS); absent or
older proof is unknown and cannot create a fault. PGlite and SQLite run the same scenarios in
nf-app/tests/sweep-proof-asof.test.mjs. The pandas reference shares one index for proof and sensor values, so it is
the aligned special case of this rule (proof at the same timestamp)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PACK = json.loads((ROOT / "nf-app" / "rules" / "pack-postgres.json").read_text(encoding="utf-8"))
START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _run(proof, offset_s=60, rules=("SV-RANGE", "SV-FLATLINE", "SV-SPIKE", "SV-RATE")):
    duckdb = pytest.importorskip("duckdb")
    from adapters import DUCKDB_HELPERS_SQL

    con = duckdb.connect(":memory:")
    con.execute("SET TimeZone = 'UTC'")
    con.execute(DUCKDB_HELPERS_SQL)
    kinds = {"double": "DOUBLE", "text": "VARCHAR", "timestamp": "TIMESTAMPTZ"}
    for table, cols in PACK["contract"].items():
        # Python 3.11: no reuse of the outer quote inside a nested f-string.
        column_defs = ", ".join('"%s" %s' % (c["name"], kinds[c["type"]]) for c in cols)
        con.execute(f"CREATE TABLE {table} ({column_defs})")
    for m in range(0, 1440, 5):
        t = START + timedelta(minutes=m)
        p = proof(m)
        if p is not ...:
            con.execute("INSERT INTO history (equipment_id, timestamp_utc, operating_status) VALUES ('eq-1', ?, ?)", [t, p])
        con.execute("INSERT INTO sensor_history VALUES ('eq-1', 'discharge_air_temperature-1', 'discharge_air_temperature', '°C', ?, 90.0)", [t + timedelta(seconds=offset_s)])
    out = {}
    for rid in rules:
        cur = con.execute(PACK["rules"][rid]["sql"])
        names = [d[0] for d in cur.description]
        out[rid] = next(dict(zip(names, r)) for r in cur.fetchall() if r[names.index("series_id")] == "discharge_air_temperature-1")
    con.close()
    return out


def test_proof_off_with_offset_sensor_timestamps_does_not_fault():
    for rid, row in _run(lambda m: 0.0).items():
        assert row["fault_hours"] == 0, (rid, row)


def test_proof_on_with_offset_still_faults_and_stale_proof_is_unknown():
    assert _run(lambda m: 1.0, rules=("SV-RANGE",))["SV-RANGE"]["fault_hours"] > 23.8
    gap = _run(lambda m: ... if 360 <= m < 720 else 1.0, rules=("SV-RANGE",))["SV-RANGE"]["fault_hours"]
    assert 18 < gap < 24 - 4.9, gap


def test_no_history_rows_is_no_run_proof():
    row = _run(lambda m: ..., rules=("SV-RANGE",))["SV-RANGE"]
    assert row["fault_hours"] is None and row["covered_hours"] == 0
