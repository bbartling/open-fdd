"""Run-proof gate parity (#1608): pandas == SQL with the gate ON and OFF, equipment off windows never count when it is on,
and an equipment with no proof is SKIPPED on both sides (SQL fault_hours NULL, pandas SKIPPED_NO_RUN_PROOF)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "sql" / "fdd"))

import render_rule  # noqa: E402
from adapters import NodeEngineAdapter  # noqa: E402
from open_fdd.parity import Policy, generate, known_differences, reference  # noqa: E402
from open_fdd.parity.policy import sql_rows_by_equipment  # noqa: E402
from open_fdd.run_proof import run_proof_gated_ids  # noqa: E402
from open_fdd.parity.pandas_ref import PANDAS_ID  # noqa: E402

ROOT = HERE.parents[1]
SQL_FILE = {r["rule_id"]: r["sql_file"] for r in __import__("json").loads((ROOT / "sql/fdd/tuning_catalog.json").read_text(encoding="utf-8"))["rules"]}
TOL = Policy().abs_tol_h
# gated rules whose pandas and SQL twins agree on the default dataset (the known differences are pinned elsewhere)
KNOWN = set(known_differences("all", "stress_only"))


@pytest.fixture(scope="module")
def ds():
    return generate(0, 4, 3, "basic")      # unit 0 own proof, 1 sick own proof, 2 proven by unit 0, 3 NO proof


def _sql(ds, rules, **overrides):
    rule_sql = {r: render_rule.render(r, ds.step_seconds, overrides) for r in rules} if overrides else None
    ad = NodeEngineAdapter("pglite")
    ad.load(ds)
    try:
        return ad.run(list(rules), rule_sql=rule_sql)
    finally:
        ad.close()


def _gated_sql_ids():
    inverse = {v: k for k, v in PANDAS_ID.items()}
    return sorted(inverse.get(r, r) for r in run_proof_gated_ids())


@pytest.fixture(scope="module")
def runs(ds):
    rules = [r for r in _gated_sql_ids() if not r.startswith("SV-")]
    pairs = {}
    for label, params in (("gated", {}), ("ungated", {"require_run_proof": 0})):
        sql = _sql(ds, rules, **params)
        ref = reference(ds, rules=rules, params=params or None)
        pairs[label] = (sql, ref)
    return rules, pairs


def _legacy_toggle_in_sql(rule: str) -> bool:
    """The rule's own pre-#1608 gate also answers to the switch in SQL (19 templates; the other 33 always apply it). In pandas
    require_run_proof=0 leaves the rule's own gate alone, so only rules WITHOUT the coupling compare exactly when ungated."""
    sql = (ROOT / "sql/fdd/postgres/rules" / SQL_FILE[rule]).read_text(encoding="utf-8")
    return sql.count("{{REQUIRE_RUN_PROOF}}") > 2


def test_gated_and_ungated_pandas_equal_sql_for_every_rule_that_matches_by_default(runs):
    rules, pairs = runs
    for label, (sql, ref) in pairs.items():
        bad = []
        for rule in rules:
            if rule in KNOWN or (label == "ungated" and _legacy_toggle_in_sql(rule)):
                continue
            rows = sql_rows_by_equipment(sql.get(rule))
            for equip, r in ref.get(rule, {}).items():
                got = (rows.get(equip) or {}).get("fault_hours")
                if r["status"].startswith("SKIPPED") or got is None or r["pandas"] is None:
                    continue
                if abs(float(got) - float(r["pandas"])) > TOL:
                    bad.append((rule, equip, got, r["pandas"]))
        assert not bad, f"{label}: {bad[:6]}"


def test_the_gate_removes_off_hours_and_never_adds_any(runs):
    rules, pairs = runs
    (sql_on, _), (sql_off, _) = pairs["gated"], pairs["ungated"]
    fewer = 0
    for rule in rules:
        on, off = sql_rows_by_equipment(sql_on.get(rule)), sql_rows_by_equipment(sql_off.get(rule))
        for equip, row in on.items():
            if row.get("fault_hours") is None or off[equip].get("fault_hours") is None:
                continue
            assert float(row["fault_hours"]) <= float(off[equip]["fault_hours"]) + TOL, (rule, equip)
            fewer += float(row["fault_hours"]) < float(off[equip]["fault_hours"]) - TOL
    assert fewer >= 5, "the dataset's equipment-off windows must make gated and ungated differ"


def test_no_proof_is_skipped_on_both_sides_and_only_with_the_gate_on(runs):
    rules, pairs = runs
    (sql_on, ref_on), (sql_off, ref_off) = pairs["gated"], pairs["ungated"]
    for rule in rules:
        assert ref_on[rule]["AHU-4"]["status"] == "SKIPPED_NO_RUN_PROOF", rule
        assert sql_rows_by_equipment(sql_on.get(rule))["AHU-4"]["fault_hours"] is None, rule
        assert not ref_off[rule]["AHU-4"]["status"].startswith("SKIPPED_NO_RUN_PROOF"), rule
        assert sql_rows_by_equipment(sql_off.get(rule))["AHU-4"]["fault_hours"] is not None or rule in ("OAT-METEO",), rule
        # a unit proven by ANOTHER unit's fan (a VAV fed by an AHU) is assessed
        assert ref_on[rule]["AHU-3"]["status"] != "SKIPPED_NO_RUN_PROOF", rule


def test_sweeps_honour_the_gate_in_sql_and_pandas(ds):
    sweeps = ["SV-RANGE", "SV-FLATLINE", "SV-SPIKE", "SV-STALE", "SV-RATE"]
    on, off = _sql(ds, sweeps), _sql(ds, sweeps, require_run_proof=0)
    ref = reference(ds, rules=sweeps)
    for rule in sweeps:
        assert ref[rule]["AHU-4"]["status"] == "SKIPPED_NO_RUN_PROOF"
        rows = [r for r in on[rule] if r["equipment_id"] == "AHU-4"]
        assert rows and all(r["fault_hours"] is None and r["covered_hours"] == 0 for r in rows), rule
        rows_off = [r for r in off[rule] if r["equipment_id"] == "AHU-4"]
        assert rows_off and any(r["covered_hours"] for r in rows_off), rule
