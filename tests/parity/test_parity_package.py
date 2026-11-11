"""open_fdd.parity: generator properties, hash stability, policy, imperial round trip, adapter conformance."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from open_fdd.parity import (GENERATOR_VERSION, Policy, compare, conformance_errors, from_imperial, generate,
                             known_differences, published_hashes, run_adapter, to_imperial)

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


# ---- hash stability --------------------------------------------------------------------------------------------------

def test_same_seed_same_hash_different_seed_different_hash():
    a, b = generate(0, 2, 1), generate(0, 2, 1)
    assert a.content_hash() == b.content_hash()
    assert generate(1, 2, 1).content_hash() != a.content_hash()
    assert generate(0, 2, 1, "edge").content_hash() != a.content_hash()
    assert generate(0, 2, 1, "edge").content_hash() == generate(0, 2, 1, "edge").content_hash()
    assert generate(1, 2, 1, "edge").content_hash() != generate(0, 2, 1, "edge").content_hash()


def test_published_hashes_match_this_version():
    pub = published_hashes()
    assert json.loads((ROOT / "open_fdd/data/parity_hashes.json").read_text())["generator"] == GENERATOR_VERSION
    for key in ("basic/0/2/3", "edge/0/2/3"):
        profile, seed, equips, days = key.split("/")
        ds = generate(int(seed), int(equips), int(days), profile)
        assert ds.content_hash() == pub[key], f"{key}: generator output changed; bump GENERATOR_VERSION and republish"


def test_contract_data_matches_the_pack():
    pack = json.loads((ROOT / "nf-app/rules/pack-postgres.json").read_text(encoding="utf-8"))
    cols = [c["name"] for c in pack["contract"]["history"] if c["name"] not in ("equipment_id", "timestamp_utc")]
    assert [c["name"] for c in generate(0, 1, 1).history_columns] == cols


def test_dataset_shapes_and_long_format():
    ds = generate(0, 2, 1)
    assert len(ds.history) == 2 * 288 and ds.model["site"]["id"] == "site-1"
    assert {p["equipment_id"] for p in ds.model["points"]} == {"AHU-1", "AHU-2"}
    assert ds.role_map["sat"] == "discharge-air-temp"
    first = next(iter(ds.samples()))
    assert first[:2] == ("AHU-1", ds.history_columns[0]["name"])
    assert sum(1 for _ in ds.samples()) == len(ds.history) * len(ds.history_columns)


# ---- edge profile ----------------------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def edge():
    return generate(0, 2, 4, "edge")


def _rows(ds, equip):
    return [r for r in ds.history if r["equipment_id"] == equip]


def test_edge_has_nulls_gap_dupes_out_of_order_jitter_and_dst(edge):
    basic = generate(0, 2, 4, "basic")
    cols = ("mat", "rat", "zone_t", "oa_h", "duct_static")
    nulls = lambda ds: sum(1 for r in ds.history for k in cols if r[k] is None)  # noqa: E731
    assert edge.meta["null_cells"] > 0 and nulls(edge) > nulls(basic) - 0 and nulls(edge) >= edge.meta["null_cells"] // 2
    # long gap (> 2 h) in the sorted unique timestamps of equipment 0
    ts = sorted({r["ts"] for r in _rows(edge, "AHU-1")})
    assert max(b - a for a, b in zip(ts, ts[1:])) > 2 * 3600 * 1000
    # duplicates (identical equipment/timestamp) and out-of-order rows
    rows = _rows(edge, "AHU-1")
    assert len({r["ts"] for r in rows}) < len(rows)
    assert any(b["ts"] < a["ts"] for a, b in zip(rows, rows[1:]))
    # jitter: timestamps are off the 5-minute grid by at most 60 s
    offs = {(r["ts"] - edge.meta["t0_ms"]) % 300000 for r in edge.history}
    assert len(offs) > 10 and all(o <= 60000 or o >= 300000 - 60000 for o in offs)
    # DST week: the run crosses the US spring-forward, and occupancy follows local time (UTC hour shifts by 1)
    assert edge.meta["dst"]["in_range"]
    transition = edge.meta["dst"]["transition_ms"]

    def first_on_utc_hour(day_start_ms):
        on = sorted(r["ts"] for r in _rows(edge, "AHU-1") if day_start_ms + 8 * 3600000 <= r["ts"] < day_start_ms + 86400000
                    and r["fan_cmd"] is not None and r["fan_cmd"] > 0)
        return round((on[0] - day_start_ms) / 3600000)

    t0 = edge.meta["t0_ms"]
    assert first_on_utc_hour(t0 + 86400000) == 12          # CST: 06:00 local = 12:00 UTC
    assert first_on_utc_hour(t0 + 3 * 86400000) == 11      # CDT: 06:00 local = 11:00 UTC
    assert t0 + 2 * 86400000 < transition < t0 + 3 * 86400000


def test_edge_planted_faults_have_known_windows(edge):
    kinds = {f["kind"] for f in edge.faults}
    assert kinds == {"flatline", "out_of_range"}
    for f in edge.faults:
        rows = [r for r in _rows(edge, f["equipment_id"]) if f["start_ms"] <= r["ts"] < f["end_ms"] - 60000 + 60000]
        vals = [r[f["column"]] for r in rows if f["start_ms"] + 60000 <= r["ts"] < f["end_ms"] - 60000]
        assert vals and all(v == f["value"] for v in vals), f["id"]


def test_dst_offsets():
    from open_fdd.parity import chicago_offset_hours as off
    assert off(1772956799000) == -6 and off(1772956800000) == -5   # 2026-03-08 07:59:59Z / 08:00:00Z
    assert off(1793000000000) == -5 and off(1794000000000) == -6   # October / mid November


# ---- policy ----------------------------------------------------------------------------------------------------------

def _ref(hours):
    return {"R": {"E": {"pandas": hours, "status": "FAULT"}}}


def _sql(hours):
    return {"R": [{"equipment_id": "E", "fault_hours": hours}]}


def test_policy_zero_compared_fails():
    v = compare({}, {}, Policy())
    assert v.compared == 0 and not v.ok
    v = compare({"R": [{"equipment_id": "E", "fault_hours": None}]}, _ref(1.0), Policy())
    assert v.compared == 0 and not v.ok


def test_policy_unexpected_fails_and_known_passes():
    assert compare(_sql(1.0), _ref(1.0 + 1e-9), Policy()).ok
    bad = compare(_sql(1.0), _ref(2.0), Policy())
    assert not bad.ok and bad.unexpected_rules == ["R"] and "unexpected=1" in bad.summary()
    known = compare(_sql(1.0), _ref(2.0), Policy(known={"R": "different gate"}))
    assert known.ok and known.known_divergent == 1 and known.summary().endswith("-> OK")


def test_policy_short_comparison_fails_unless_relaxed():
    ref = {**_ref(1.0), "S": {"E": {"pandas": 0.0, "status": "PASS"}}}
    assert not compare(_sql(1.0), ref, Policy()).ok
    assert compare(_sql(1.0), ref, Policy(require_all_twins=False)).ok


def test_known_differences_are_scoped_and_documented():
    allk, stress, edge = known_differences("all"), known_differences("stress_only"), known_differences("edge")
    assert len(allk) == 22 and set(stress) == {"TRIM-3", "VAV-REHEAT"} and not set(allk) & set(stress)
    assert all(reason for reason in {**allk, **stress, **edge}.values())
    assert set(Policy.default("basic", stress=True).known) == set(allk) | set(stress)
    assert set(Policy.default("basic", stress=False).known) == set(allk)
    assert set(Policy.default("edge").known) == set(allk) | set(stress) | set(edge)


# ---- imperial round trip ---------------------------------------------------------------------------------------------

def test_imperial_round_trip():
    ds = generate(0, 2, 1)
    imp = to_imperial(ds)
    assert imp.meta["unit_system"] == "imperial" and imp.units["oa_t"] == "°F" and imp.units["duct_static"] == "inH2O"
    r0, r1 = ds.history[10], imp.history[10]
    assert r1["oa_t"] == pytest.approx(r0["oa_t"] * 9 / 5 + 32)
    assert r1["fan_cmd"] == pytest.approx(r0["fan_cmd"] * 100)
    assert r1["fan_status"] == r0["fan_status"] and r1["oa_h"] == r0["oa_h"]       # unchanged scales
    back = from_imperial(imp)
    for a, b in zip(ds.history, back.history):
        for k, v in a.items():
            if isinstance(v, float):
                assert b[k] == pytest.approx(v, abs=1e-9, rel=1e-9), k
            else:
                assert b[k] == v
    for a, b in zip(ds.weather, back.weather):
        assert b["oa_t"] == pytest.approx(a["oa_t"], abs=1e-9)
    assert back.units == ds.units and back.meta == ds.meta
    with pytest.raises(ValueError):
        to_imperial(imp)


# ---- adapter conformance ---------------------------------------------------------------------------------------------

class _FakeAdapter:
    name = "fake"

    def __init__(self, bad=False):
        self.bad, self.closed = bad, False

    def load(self, dataset):
        self.ds = dataset

    def run(self, rule_ids=None):
        if self.bad:
            return {r: [{"fault_hours": 1.0}] for r in rule_ids}
        return {r: [{"equipment_id": e["equipment_id"], "fault_hours": 0.0} for e in self.ds.equipment] for r in rule_ids}

    def close(self):
        self.closed = True


def test_adapter_conformance_checker():
    ds = generate(0, 1, 1)
    ok = _FakeAdapter()
    assert conformance_errors(ok, ds, ["A", "B"]) == [] and ok.closed
    assert conformance_errors(_FakeAdapter(bad=True), ds, ["A"])
    assert run_adapter(_FakeAdapter(), ds, ["A"])["A"][0]["equipment_id"] == "AHU-1"


@pytest.mark.skipif(not shutil.which("node"), reason="node required")
@pytest.mark.parametrize("kind", ["pglite", "sqlite"])
def test_in_repo_engines_conform(kind):
    sys.path.insert(0, str(HERE))
    from adapters import NodeEngineAdapter
    from open_fdd.parity import EngineAdapter
    ad = NodeEngineAdapter(kind)
    assert isinstance(ad, EngineAdapter)
    ds = generate(0, 2, 1)
    assert conformance_errors(ad, ds, ["FC1", "SV-RANGE", "CHW-1"]) == []
    with pytest.raises(RuntimeError):
        ad.run()           # run before load


# ---- the stress CLI on both profiles ---------------------------------------------------------------------------------

@pytest.mark.skipif(not shutil.which("node"), reason="node required")
@pytest.mark.parametrize("profile", ["basic", "edge"])
def test_stress_cli_runs_on_both_profiles(profile, tmp_path):
    out = tmp_path / "rep.json"
    proc = subprocess.run([sys.executable, str(HERE / "stress.py"), "--equips", "2", "--days", "3", "--profile", profile,
                           "--out", str(out)], capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
    rep = json.loads(out.read_text(encoding="utf-8"))
    assert rep["profile"] == profile and rep["dataset_hash"] == published_hashes()[f"{profile}/0/2/3"]
    assert not rep["sql_errors"] and not rep["pglite_vs_sqlite_mismatches"], rep
    assert "verdict" in rep and rep["verdict"]["compared"] > 0
    if profile == "basic":
        assert proc.returncode == 0, proc.stdout[-800:]
        assert "-> OK" in proc.stdout
