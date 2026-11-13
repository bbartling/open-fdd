"""The shared core tables carry the pandas == SQL verdict (Timescale path) and the pinned baseline cannot drift.

Always runs: the baseline on PGlite, the core-row export, the SI identity & native-unit scale/offset checks (no DB).
Needs a disposable TimescaleDB (PGURL + OPENFDD_TS_TEST_DISPOSABLE=1, as nf-app/timescale/test):
- SI ingest path (default): exact same SI fixture as PGlite/SQLite/DuckDB/Postgres, direct row-for-row comparison.
- Native-unit ingestion conversion test: seeds native imperial units and verifies fdd.input_sample affine conversion.
CI's TimescaleDB job sets both and fails when this test is skipped.
"""
import json

import pytest

from adapters import NodeEngineAdapter, TimescaleAdapter, timescale_configured
from open_fdd.parity import Policy, compare, from_imperial, generate, reference, to_imperial
from stress import BASELINE, engines_disagree

_BASE = json.loads(BASELINE.read_text(encoding="utf-8"))["datasets"]
PINNED = next(d for d in _BASE if (d["equips"], d["days"]) == (4, 3))   # the fast size; CI's stress run pins 8 x 7
ARGS = PINNED


@pytest.fixture(scope="module")
def ds():
    return generate(ARGS["seed"], ARGS["equips"], ARGS["days"], ARGS["profile"])


def summary(verdict) -> dict:
    return {k: verdict.to_dict()[k] for k in PINNED["verdict"]}


def test_baseline_file_is_the_documented_verdict():
    assert [d["verdict"] for d in _BASE] == [{"compared": 71, "matched": 47, "known_divergent": 24, "unexpected": 0},
                                             {"compared": 71, "matched": 50, "known_divergent": 21, "unexpected": 0}]


def test_baseline_verdict_on_pglite(ds):
    adapter = NodeEngineAdapter("pglite")
    adapter.load(ds)
    try:
        rows = adapter.run()
    finally:
        adapter.close()
    verdict = compare(rows, reference(ds), Policy.default(ARGS["profile"], stress=True))
    assert summary(verdict) == PINNED["verdict"], verdict.summary()
    assert verdict.ok


def test_core_rows_describe_the_dataset(ds):
    points, samples = ds.to_core_rows()
    keys = {p["point_key"] for p in points}
    assert len(keys) == len(points), "point_key is unique within the site"
    assert {p["site_id"] for p in points} == {"parity"}
    assert {s[1] for s in samples} == keys, "every point has samples and every sample a point"
    series = [p for p in points if p.get("series")]
    assert {p["point_key"] for p in series} == {s["series_id"] for s in ds.series if s["equipment_id"] in {p["equipment_id"] for p in points}}
    assert all(p["kind"] in ("numeric", "bool", "text") for p in points)
    by_key = {}
    for _site, key, ts, value in samples:
        by_key.setdefault(key, {})[ts] = value
    for row in ds.history[:50]:
        for column in ("sat", "oa_t", "fan_status"):
            v = row.get(column)
            assert (by_key.get(f"{row['equipment_id']}/{column}", {}).get(row["ts"])) == v


def test_imperial_round_trip_is_exact_with_the_nf_ingest_constants(ds):
    back = from_imperial(to_imperial(ds))
    for a, b in zip(ds.history, back.history):
        for k, v in a.items():
            w = b[k]
            if isinstance(v, float):
                assert abs(v - w) <= 1e-9 + 1e-9 * abs(v), (k, v, w)
            else:
                assert v == w


def test_si_ingest_scale_is_exact_identity(ds):
    """No database: SI ingest writes si_scale=1 and si_offset=0 with zero skipped roles."""
    adapter = TimescaleAdapter(plan_only=True, ingest="si")
    adapter.load(ds)
    try:
        adapter.run()
    finally:
        adapter.close()
    assert adapter.raw["factor_mismatches"] == []
    assert adapter.raw["skipped"] == {}, "siPlan must not skip any role of the dataset"


def test_native_unit_scale_and_offset_reproduce_the_si_dataset(ds):
    """No database: samples in native units x the scale/offset the loader writes to fdd.point == the SI dataset."""
    adapter = TimescaleAdapter(plan_only=True, ingest="native")
    adapter.load(ds)
    try:
        adapter.run()
    finally:
        adapter.close()
    assert adapter.raw["factor_mismatches"] == []
    assert adapter.raw["skipped"] == {}, "siPlan must not skip any role of the dataset"


@pytest.mark.skipif(not timescale_configured(), reason="PGURL + OPENFDD_TS_TEST_DISPOSABLE=1 (a disposable TimescaleDB) required")
def test_timescale_through_the_core_tables_reproduces_the_verdict(ds):
    """Direct SI parity: Timescale loads the exact same SI fixture as PGlite and agrees row-for-row."""
    pglite = NodeEngineAdapter("pglite")
    pglite.load(ds)
    try:
        pg_rows = pglite.run()
    finally:
        pglite.close()
    adapter = TimescaleAdapter(ingest="si")
    adapter.load(ds)
    try:
        ts_rows = adapter.run()
    finally:
        adapter.close()
    raw = adapter.raw
    assert raw["errors"] == {}
    assert raw["ingest"] == "si"
    assert raw["schema_version"] == 4 and raw["signature_ok"] is True
    assert raw["history_mismatches"] == [], "history == SI dataset cell for cell (1e-9 relative)"
    assert raw["factor"]["factor_mismatches"] == []
    assert raw["stored"]["after"] == raw["stored"]["before"] > 0, "re-running writes no new rows"
    assert raw["index_ok"] is True, f"the loader query can use NF's (point_id, time) index: {raw.get('index_plan')}"
    bad = engines_disagree({"pglite": pg_rows, "timescale": ts_rows}, "timescale", ref_engine="pglite")
    assert bad == [], bad
    verdict = compare(ts_rows, reference(ds), Policy.default(ARGS["profile"], stress=True))
    assert summary(verdict) == PINNED["verdict"], verdict.summary()


@pytest.mark.skipif(not timescale_configured(), reason="PGURL + OPENFDD_TS_TEST_DISPOSABLE=1 (a disposable TimescaleDB) required")
def test_timescale_native_unit_ingestion_conversion_reproduces_the_si_dataset(ds):
    """Ingestion conversion test: native imperial samples in public.data convert cleanly via fdd.input_sample."""
    pglite = NodeEngineAdapter("pglite")
    pglite.load(ds)
    try:
        pg_rows = pglite.run()
    finally:
        pglite.close()
    adapter = TimescaleAdapter(ingest="native")
    adapter.load(ds)
    try:
        ts_rows = adapter.run()
    finally:
        adapter.close()
    raw = adapter.raw
    assert raw["errors"] == {}
    assert raw["ingest"] == "native"
    assert raw["history_mismatches"] == [], "history == SI dataset cell for cell (1e-9 relative)"
    assert raw["factor"]["factor_mismatches"] == []
    same = NodeEngineAdapter("pglite")
    same.load(adapter.loaded_dataset(ds))
    try:
        pg_same = same.run()
    finally:
        same.close()
    bad = engines_disagree({"pglite": pg_same, "timescale": ts_rows}, "timescale", ref_engine="pglite")
    assert bad == [], bad
    tie_only = engines_disagree({"pglite": pg_rows, "timescale": pg_same}, "timescale", ref_engine="pglite")
    assert all(not r.startswith(("UTIL-", "OAT-METEO")) for r in tie_only), tie_only
    verdict = compare(ts_rows, reference(ds), Policy.default(ARGS["profile"], stress=True))
    assert summary(verdict) == PINNED["verdict"], verdict.summary()
