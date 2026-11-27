"""The SI parity suite: pandas oracle == SQL pack, and both SQL engines agree.

Run:  python -m pytest tests/parity -q      (needs node + `npm ci` in nf-app, and pandas/numpy/pyyaml)

Everything is SI. The dataset is nf-app/tests/fixtures/synthetic_dataset.js (deterministic; AHU-1 mostly healthy,
AHU-2 "sick" with injected fault windows), run through Node DuckDB by tests/parity/sql_run.mjs.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import harness as h

ROOT = h.ROOT

# Known differences live in open_fdd/data/parity_known_differences.json (rule, scope, reason), shipped with the package
# so downstream apps and stress.py use the same list. Rules whose pandas twin and SQL rule are *different algorithms or
# gates* on this dataset (none is a unit problem: thresholds were checked in SI). Keep the set exact: a fix removes an
# entry, a regression adds one, and either way this test says so.
# scope "all" is asserted exactly on the 2x3 pytest dataset; "stress_only" (#1582) only shows on the longer stress
# datasets (tests/parity/stress.py), so it is NOT in KNOWN_DIVERGENT.
from open_fdd.parity import known_differences  # noqa: E402

KNOWN_DIVERGENT = known_differences("all")
STRESS_ONLY_DIVERGENT = known_differences("stress_only")


NO_TWIN = {"AVG-ZONE-TEMP", "FAN-RUNTIME-HOURS", "FAULT-ELAPSED-HOURS", "UTIL-INTERVAL", "UTIL-MONTHLY", "ZONE-COMFORT-PCT"}
SWEEP_RULES = ("SV-RATE", "SV-RANGE", "SV-FLATLINE", "SV-SPIKE", "SV-STALE")


@pytest.fixture(scope="session")
def data(tmp_path_factory):
    out = tmp_path_factory.mktemp("parity") / "sql.json"
    d = h.run_sql(equips=2, days=3, out=out)
    assert not d["errors"], d["errors"]
    return d


@pytest.fixture(scope="session")
def report(data):
    return h.compare(data)


def test_dataset_is_si(data):
    # every declared unit is an SI unit (or the two deliberate probes: missing and °F, which the SQL gate masks)
    declared = set(data["units"].values())
    assert declared <= {"°C", "%", "Pa", "°F", None}, declared
    pg = data["results"]["duckdb"]
    assert len(pg) == 83


def test_dataset_follows_the_declared_scales(data):
    """Roles 1.1.0: damper, valve and speed columns are PERCENT 0-100; commands and statuses are boolean 0/1."""
    scales = json.loads((ROOT / "sql/fdd/role_scales.json").read_text(encoding="utf-8"))["roles"]
    seen = {"PERCENT": 0, "boolean": 0}
    for equip, cols in data["history"].items():
        for role, vals in cols.items():
            sc = scales.get(role)
            nums = [v for v in vals if isinstance(v, (int, float))] if sc in seen else []
            if not nums:
                continue
            seen[sc] += 1
            lo, hi = min(nums), max(nums)
            if sc == "PERCENT":
                assert 0.0 <= lo and hi <= 100.0, (equip, role, sc, lo, hi)
            else:
                assert 0.0 <= lo and hi <= 1.0, (equip, role, sc, lo, hi)
                assert set(nums) <= {0, 1, 0.0, 1.0}, (equip, role)
    assert seen["PERCENT"] >= 6 and seen["boolean"] >= 10, seen


def test_duckdb_returns_every_rule(data):
    pg = data["results"]["duckdb"]
    assert len(pg) == 83
    assert all(isinstance(rows, list) for rows in pg.values())


def test_sweep_rows_retain_series_identity_and_coverage(data):
    for rule in SWEEP_RULES:
        rows = data["results"]["duckdb"][rule]
        assert rows, rule
        assert all({"equipment_id", "series_id", "sensor_role", "fault_hours", "covered_hours"} <= set(row) for row in rows), rule
        identities = [h.sql_result_key(row) for row in rows]
        assert len(identities) == len(set(identities)), (rule, "duplicate series identity", identities)


def test_pandas_equals_sql_in_si(report):
    diverged = {r for r, per in report["compared"].items() if not h.rule_matches(per)}
    matched = set(report["compared"]) - diverged
    assert diverged == set(KNOWN_DIVERGENT), (
        f"newly diverging: {sorted(diverged - set(KNOWN_DIVERGENT))}; now matching (drop from KNOWN_DIVERGENT): "
        f"{sorted(set(KNOWN_DIVERGENT) - diverged)}")
    assert len(matched) >= 49, sorted(matched)
    # the matched set must actually trip faults, otherwise equality proves nothing
    tripped = [r for r in matched if any(v["sql"] > 0 for v in report["compared"][r].values())]
    assert len(tripped) >= 20, tripped


def test_rules_without_pandas_twin_are_listed(report):
    # SQL-only rules (no open_fdd.rules twin): listed by stress.py in the report, never silently skipped
    assert set(report["no_twin"]) == NO_TWIN
    assert len(report["twins"]) + len(report["no_twin"]) == 83


# ---- SI-only contract (no imperial anywhere in the pack or the oracle) -------------------------------------------

def test_catalog_units_are_si():
    cat = json.loads((ROOT / "sql/fdd/tuning_catalog.json").read_text(encoding="utf-8"))["rules"]
    allowed = {"DEG_C", "K", "K-PER-HR", "PA", "L-PER-SEC", "KiloW-HR", "MIN", "HR", "PERCENT", "PPM",
               "boolean", "x", "NUM", "unit"}
    for r in cat:
        for k, d in r["parameters"].items():
            assert d["unit"] in allowed, (r["rule_id"], k, d["unit"])
            assert not re.search(r"(_f|_cfm|_gpm|_inwc|_psi)$", k), (r["rule_id"], k)
    dflt = json.loads((ROOT / "sql/fdd/runtime_defaults.json").read_text(encoding="utf-8"))
    assert dflt["FREE_COOL_OAT"] == pytest.approx(18.333333) and dflt["SETBACK_HI"] == 20.0
    assert all(not k.endswith(("_F", "_CFM")) for k in dflt)


def test_no_imperial_literals_in_sql():
    for f in (ROOT / "sql/fdd/postgres/rules").glob("*.sql"):
        text = f.read_text(encoding="utf-8")
        code = "\n".join(line.split("--")[0] for line in text.splitlines())
        assert not re.search(r"\b(68\.0|76\.0|65\.0)\b", code), f.name


def test_unit_gate_rejects_imperial_and_unknown():
    from open_fdd.rules.sensor_sweep_catalog import sweep_assessable_role as ok
    assert ok("zone_air_temperature", "°C") and ok("discharge_air_static_pressure", "Pa") and ok("zone_air_relative_humidity", "%")
    for bad in ("°F", "degF", None, "", "kPa"):
        assert not ok("zone_air_temperature", bad), bad
    for bad in ("inH2O", "inWC", "kPa", None):
        assert not ok("discharge_air_static_pressure", bad), bad


def test_pandas_defaults_equal_sql_catalog(report):
    """Every shared tuning parameter has the same SI default in the pandas oracle and the SQL catalog."""
    bad = []
    for rid, rule in h.RULES_BY_ID.items():
        sql = h.CATALOG.get(rid) or h.CATALOG.get(next((k for k, v in h.PANDAS_ID.items() if v == rid), rid))
        if not sql:
            continue
        for p in rule.params:
            q = sql["parameters"].get(p.key)
            if q and q["unit"] in ("degC", "degC_delta", "L_per_s", "Pa"):
                if abs(float(p.default) - float(q["default"])) > 1e-4 * max(1.0, abs(float(q["default"]))):
                    bad.append((rid, p.key, p.default, q["default"]))
    assert not bad, bad[:10]


def test_sensor_sweep_parity_keeps_per_role_evidence(report):
    """SQL series rows aggregate by original Haystack role for pandas comparison; totals stay worst-role hours."""
    for rule in SWEEP_RULES:
        per = report["compared"][rule]
        assert per, rule
        for equip, result in per.items():
            sql_roles = result.get("sql_sensor_fault_hours")
            pandas_roles = result.get("pandas_sensor_fault_hours")
            silence_hours = result.get("pandas_sensor_silence_hours")
            assert sql_roles is not None and pandas_roles is not None, (rule, equip, result)
            if rule == "SV-RATE" and not pandas_roles:
                # SV-RATE deliberately remains algorithmically divergent and does not expose the same per-role oracle evidence.
                assert rule in KNOWN_DIVERGENT and sql_roles, (rule, equip, result)
                assert result["sql"] == pytest.approx(max(sql_roles.values(), default=0.0))
                continue
            assert set(sql_roles) == set(pandas_roles), (rule, equip, sql_roles, pandas_roles)
            assert silence_hours is not None and set(silence_hours) == set(pandas_roles), (rule, equip, result)
            assert all(value >= 0 for value in silence_hours.values()), (rule, equip, silence_hours)
            assert result["sql"] == pytest.approx(max(sql_roles.values(), default=0.0))
            assert result["pandas"] == pytest.approx(max(pandas_roles.values(), default=0.0))
            if rule not in KNOWN_DIVERGENT:
                assert h.rule_matches({equip: result}), (rule, equip, result)


@pytest.fixture(scope="session")
def duplicate_sensor_data(tmp_path_factory):
    out = tmp_path_factory.mktemp("parity-duplicate-sensor") / "sql.json"
    d = h.run_sql(equips=1, days=1, out=out, rules=",".join(SWEEP_RULES), duplicate_role=True)
    assert not d["errors"], d["errors"]
    return d


def test_duplicate_role_sensor_series_are_distinct(duplicate_sensor_data):
    """Two points with the same SAT role must survive SQL authorization as separate identities."""
    pg = duplicate_sensor_data["results"]["duckdb"]
    assert set(pg) == set(SWEEP_RULES)
    for rule in SWEEP_RULES:
        a = sorted(pg[rule], key=h.sql_result_key)
        discharge_air_temperature = [row for row in a if row["equipment_id"] == "AHU-1" and row.get("sensor_role") == "discharge_air_temperature"]
        ids = {row["series_id"] for row in discharge_air_temperature}
        assert len(discharge_air_temperature) == 2 and len(ids) == 2, (rule, discharge_air_temperature)
        assert all(row.get("covered_hours") is not None for row in discharge_air_temperature), (rule, discharge_air_temperature)


def test_stress_verdict_fails_on_unexpected_divergence_or_short_comparison():
    from open_fdd.parity.policy import verdict_from_counts as verdict
    known = {"SV-RATE"}
    assert verdict(70, 70, {"SV-RATE"}, known)["ok"]
    bad = verdict(70, 70, {"SV-RATE", "SOME-RULE"}, known)
    assert not bad["ok"] and bad["unexpected_rules"] == ["SOME-RULE"] and bad["unexpected"] == 1
    assert not verdict(0, 70, set(), known)["ok"]
    assert not verdict(60, 70, set(), known)["ok"]


# --- #1582 regression fixtures: one tiny SI frame per stress-only divergence ---------------------------------------------
STEP_S = 300


def _fixture_frame(n, **cols):
    idx = h.pd.date_range("2026-01-05", periods=n, freq="5min", tz="UTC", name="timestamp_utc")
    df = h.pd.DataFrame({k: h.pd.Series(v, index=idx, dtype=float) for k, v in cols.items()}, index=idx)
    df.attrs["equipment_id"] = "FIXTURE"
    df.attrs["role_units"] = {}
    return df


def _sql_confirmed_hours(raw, confirm_s):
    """The SQL pack's confirmation model: forward sample-and-hold, a streak confirms once its elapsed seconds reach confirm_s."""
    total, elapsed = 0.0, 0.0
    for i, flag in enumerate(raw):
        held = STEP_S if i + 1 < len(raw) else 0.0
        elapsed = elapsed + held if flag else 0.0
        if flag and elapsed >= confirm_s:
            total += held
    return total / 3600.0


def test_vav_reheat_difference_is_exactly_the_startup_holdoff(monkeypatch):
    from dataclasses import replace
    from open_fdd.rules import operational_gate as og

    n = 30
    fan = [0] * 4 + [1] * 26
    rise_bad = [0.5] * 22 + [2.5] * 8  # the fault is present from the first fan-on sample, then ends
    df = _fixture_frame(n, **{"supply_fan_operating_status": fan, "discharge_air_volume_flow_rate": [50.0] * n, "terminal_unit_heating_valve_position_command": [70.0] * n,
                              "terminal_unit_inlet_air_temperature": [15.0] * n,
                              "terminal_unit_discharge_air_temperature": [15.0 + r for r in rise_bad]})
    raw = [f == 1 and r < 1.666667 for f, r in zip(fan, rise_bad)]
    sql_hours = _sql_confirmed_hours(raw, CATALOG_CONFIRM["VAV-REHEAT"])
    pandas_hours, status = h.pandas_fault_hours("VAV-REHEAT", df.copy(), None)
    assert status == "FAULT"
    assert sql_hours - pandas_hours == pytest.approx(STEP_S / 3600)  # one sample later in pandas
    # the 600 s startup holdoff is the whole difference: with it removed pandas equals the SQL confirmation model
    gate = og.RULE_GATES["VAV-REHEAT"]
    assert gate.startup_delay_seconds == 600
    monkeypatch.setitem(og.RULE_GATES, "VAV-REHEAT", replace(gate, startup_delay_seconds=0.0))
    assert h.pandas_fault_hours("VAV-REHEAT", df.copy(), None)[0] == pytest.approx(sql_hours)


def test_trim3_is_aligned_with_the_sql_contract_and_differs_only_by_the_startup_holdoff():
    """#1588: pandas TRIM-3 reads the contract role, faults at request sum <= request_lo like SQL, and skips when the
    request sum is absent (SQL has no rows then); what is left is the pandas 600 s hydronic-proof startup holdoff."""
    n = 24
    common = {"supply_hot_water_temperature": [75.0] * n, "pump_operating_status": [1] * n}
    df = _fixture_frame(n, **common, **{"hot_water_reset_request_count": [1.0] * n})     # exactly at request_lo
    pandas_hours, status = h.pandas_fault_hours("TRIM-3", df, None)
    assert not str(status).startswith("SKIPPED") and pandas_hours > 0.0
    sql_hours = _sql_confirmed_hours([True] * n, CATALOG_CONFIRM["TRIM-3"])
    assert sql_hours >= pandas_hours and sql_hours - pandas_hours <= 600 / 3600 + 1e-9, (sql_hours, pandas_hours)
    df = _fixture_frame(n, **common, **{"hot_water_reset_request_count": [2.0] * n})     # above request_lo: no fault
    assert h.pandas_fault_hours("TRIM-3", df, None)[0] == 0.0
    df = _fixture_frame(n, **common)                                                    # absent: not assessed
    assert str(h.pandas_fault_hours("TRIM-3", df, None)[1]).startswith("SKIPPED")


CATALOG_CONFIRM = {rid: h.CATALOG[rid]["parameters"]["confirm_min"]["default"] * 60 for rid in ("VAV-REHEAT", "TRIM-3")}


def test_pinned_delta_band_catches_a_widened_known_difference():
    """#1590: a known difference carries an expected delta on canonical datasets; widening it (e.g. an edit to the rule's
    SQL that faults more) fails the verdict even though the rule is still on the known list."""
    from open_fdd.parity.policy import Policy, compare, expected_deltas
    ref = {"RULE-X": {"E1": {"pandas": 1.0}, "E2": {"pandas": 0.0}}}
    pinned = Policy(known={"RULE-X": "test"}, pins={"RULE-X": {"hours": 0.5, "tol": 0.01}})
    as_pinned = compare({"RULE-X": [{"equipment_id": "E1", "fault_hours": 1.5}, {"equipment_id": "E2", "fault_hours": 0.0}]}, ref, pinned)
    assert as_pinned.ok and as_pinned.pin_violations == [] and as_pinned.deltas == {"RULE-X": 0.5}
    widened = compare({"RULE-X": [{"equipment_id": "E1", "fault_hours": 1.5}, {"equipment_id": "E2", "fault_hours": 0.25}]}, ref, pinned)
    assert not widened.ok and widened.unexpected == 0
    assert widened.pin_violations == ["RULE-X: delta 0.7500 h, pinned 0.5000 +/- 0.0100 h"]
    tightened = compare({"RULE-X": [{"equipment_id": "E1", "fault_hours": 1.25}, {"equipment_id": "E2", "fault_hours": 0.0}]}, ref, pinned)
    assert not tightened.ok and tightened.unexpected == 0
    assert tightened.pin_violations == ["RULE-X: delta 0.2500 h, pinned 0.5000 +/- 0.0100 h"]
    matching = compare({"RULE-X": [{"equipment_id": "E1", "fault_hours": 1.0}, {"equipment_id": "E2", "fault_hours": 0.0}]}, ref, pinned)
    assert not matching.ok and matching.unexpected == 0
    assert matching.pin_violations == ["RULE-X: delta 0.0000 h, pinned 0.5000 +/- 0.0100 h"]
    unpinned = Policy(known={"RULE-X": "test"}, pins={"OTHER": {"hours": 0.0, "tol": 0.01}})
    assert compare({"RULE-X": [{"equipment_id": "E1", "fault_hours": 1.5}]}, ref, unpinned).pin_violations == [
        "RULE-X: no expected delta pinned for this dataset"]
    # every known difference of the stress scopes is pinned on both canonical stress datasets
    for key in ("basic/0/8/7", "basic/0/4/3"):
        assert set(expected_deltas(key)) == set(Policy.default("basic", stress=True).known), key
