"""The SI parity suite: pandas oracle == SQL pack, and both SQL engines agree.

Run:  python -m pytest tests/parity -q      (needs node + `npm ci` in nf-app, and pandas/numpy/pyyaml)

Everything is SI. The dataset is nf-app/hooks/lib/synthetic_dataset.js (deterministic; AHU-1 mostly healthy,
AHU-2 "sick" with injected fault windows), run through PGlite + sql.js by tests/parity/sql_run.mjs.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import harness as h

ROOT = h.ROOT

# Rules whose pandas twin and SQL rule are *different algorithms or gates* on this dataset. None of these is a unit
# problem (their threshold equations were checked in SI: same constants on both sides); they differ by how the
# operational gate / equipment proof / weather join / fan proof is defined. Keep the set exact: a fix removes an
# entry, a regression adds one, and either way this test says so. Reasons are grouped by cause.
# #1541 (one declared scale per column: fractions in, no magnitude guess on either side) removed AHU-SIMUL, CHW-2 and
# FCU-VALVE-PASS-CLG: their old differences were the SQL element-wise vs pandas series-level percent guess.
_EDGE = ("SQL holds the fan-restart / mode-delay window over rolling rows, pandas GL36 suppresses after a mode change: "
         "differs by a few samples at fault edges")
_PROOF = "pandas proves equipment/cooling from typed roles (mechanical_proof_mask, equipment_type); SQL ORs chiller status / valve"
_WX = "weather source: SQL prefers equipment web_oa_* then as-of weather rows; pandas resolves its own web columns"
_GATE = "SQL and pandas gate 'equipment on' with different fan/pump proof order and thresholds"
KNOWN_DIVERGENT = {
    "AHU-SATDEV": _GATE, "CHW-1": _EDGE, "CHW-NOLOAD-1": _PROOF,
    "ECON-3": _WX, "ECON-4": _EDGE, "ECON-7": _WX, "FC13-SAT-HIGH": _GATE, "FC14": _GATE, "FC5": _EDGE, "FC6": _GATE, "FC7": _GATE,
    "FCU-HTG-COIL": _GATE, "FCU-MODE-CYCLE": _EDGE, "HP-1": _GATE,
    "MECH-OAT-1": _PROOF, "OA-1": _EDGE, "OAT-METEO": _WX,
    "SV-RATE": "documented in sql/fdd/KNOWN_DIFFERENCES.md: pandas uses profile/median/persistence logic, SQL two consecutive exceedances",
    "TRIM-1": _GATE, "TRIM-4": "pandas skips (missing roles: reset requests); SQL treats absent requests as zero",
    "VAV-6": _EDGE, "VAV-AHU-LEAVE": _EDGE,
}


NO_TWIN = {"AVG-ZONE-TEMP", "FAN-RUNTIME-HOURS", "FAULT-ELAPSED-HOURS", "UTIL-INTERVAL", "UTIL-MONTHLY", "ZONE-COMFORT-PCT"}


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
    pg = data["results"]["pglite"]
    assert len(pg) == 77


def test_dataset_follows_the_declared_scales(data):
    """Issue #1541: both oracles are fed fractions 0-1 for command/position roles and 0/1 for statuses."""
    scales = json.loads((ROOT / "sql/fdd/role_scales.json").read_text(encoding="utf-8"))["roles"]
    seen = {"fraction": 0, "boolean": 0}
    for equip, cols in data["history"].items():
        for role, vals in cols.items():
            sc = scales.get(role)
            nums = [v for v in vals if isinstance(v, (int, float))] if sc in seen else []
            if not nums:
                continue
            seen[sc] += 1
            lo, hi = min(nums), max(nums)
            assert 0.0 <= lo and hi <= 1.0, (equip, role, sc, lo, hi)
            if sc == "boolean":
                assert set(nums) <= {0, 1, 0.0, 1.0}, (equip, role)
    assert seen["fraction"] >= 20 and seen["boolean"] >= 10, seen


def test_sql_engines_agree(data):
    pg, lite = data["results"]["pglite"], data["results"]["sqlite"]
    bad = []
    for rule in pg:
        a = sorted(pg[rule], key=h.sql_result_key)
        b = sorted(lite[rule], key=h.sql_result_key)
        if len(a) != len(b):
            bad.append(f"{rule}: {len(a)} vs {len(b)} rows")
            continue
        for ra, rb in zip(a, b):
            for k in ra:
                x, y = ra[k], rb.get(k)
                if isinstance(x, (int, float)) and isinstance(y, (int, float)):
                    if abs(x - y) > 1e-9 + 1e-6 * max(abs(x), abs(y)):
                        bad.append(f"{rule}.{ra['equipment_id']}.{k}: {x} vs {y}")
                elif x != y:
                    bad.append(f"{rule}.{ra['equipment_id']}.{k}: {x} vs {y}")
    assert not bad, bad[:10]


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
    assert len(report["twins"]) + len(report["no_twin"]) == 77


# ---- SI-only contract (no imperial anywhere in the pack or the oracle) -------------------------------------------

def test_catalog_units_are_si():
    cat = json.loads((ROOT / "sql/fdd/tuning_catalog.json").read_text(encoding="utf-8"))["rules"]
    allowed = {"degC", "degC_delta", "degC_delta_per_h", "Pa", "L_per_s", "kWh", "min", "frac", "pct", "bool", "x", "count",
               "h", "sec", "unit", "ppm", "%"}
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
    assert ok("zone-air-temp", "°C") and ok("duct-static-pressure", "Pa") and ok("zone-air-humidity", "%")
    for bad in ("°F", "degF", None, "", "kPa"):
        assert not ok("zone-air-temp", bad), bad
    for bad in ("inH2O", "inWC", "kPa", None):
        assert not ok("duct-static-pressure", bad), bad


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
    """Per-role sweep rows must match pandas evidence; equipment totals stay worst-sensor hours."""
    for rule in ("SV-RANGE", "SV-FLATLINE", "SV-SPIKE", "SV-STALE"):
        per = report["compared"][rule]
        assert per, rule
        for equip, result in per.items():
            sql_roles = result.get("sql_sensor_fault_hours")
            pandas_roles = result.get("pandas_sensor_fault_hours")
            silence_hours = result.get("pandas_sensor_silence_hours")
            assert sql_roles is not None and pandas_roles is not None, (rule, equip, result)
            assert set(sql_roles) == set(pandas_roles), (rule, equip, sql_roles, pandas_roles)
            assert silence_hours is not None and set(silence_hours) == set(pandas_roles), (rule, equip, result)
            assert all(value >= 0 for value in silence_hours.values()), (rule, equip, silence_hours)
            assert result["sql"] == pytest.approx(max(sql_roles.values(), default=0.0))
            assert result["pandas"] == pytest.approx(max(pandas_roles.values(), default=0.0))
            assert h.rule_matches({equip: result}), (rule, equip, result)
