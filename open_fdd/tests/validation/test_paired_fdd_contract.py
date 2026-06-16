"""Paired FDD smoke contract — SQL builders and rule payloads."""

from __future__ import annotations

from open_fdd.validation.paired_fdd_contract import (
    ACME_LOCAL_OAT_POINT_ID,
    ACME_SPREAD_CFG,
    CONFIRMATION_CFG,
    PHASE_BLATANT,
    PHASE_NORMAL,
    acme_rules_for_phase,
    bench_rules_for_phase,
    oat_spread_sql,
    zn_t_bounds_sql,
)


def test_confirmation_defaults_five_minutes():
    assert CONFIRMATION_CFG["min_elapsed_minutes"] == 5
    assert CONFIRMATION_CFG["min_true_rows"] == 5


def test_bench_bounds_sql_matches_phases():
    normal = zn_t_bounds_sql(65, 75)
    blatant = zn_t_bounds_sql(99, 100)
    assert "65" in normal and "75" in normal
    assert "99" in blatant and "100" in blatant


def test_acme_spread_sql_tight_vs_normal():
    loose = oat_spread_sql(10.0)
    tight = oat_spread_sql(0.001)
    assert "10.0" in loose and "IS NOT NULL" in loose
    assert "0.001" in tight


def test_bench_rules_include_both_backends():
    rules = bench_rules_for_phase(PHASE_NORMAL)
    backends = {r["backend"] for r in rules}
    assert "arrow" in backends
    assert "datafusion_sql" in backends
    assert all(
        CONFIRMATION_CFG["min_elapsed_minutes"] == r["config"]["min_elapsed_minutes"] for r in rules
    )


def test_acme_rules_pair():
    rules = acme_rules_for_phase(PHASE_BLATANT)
    assert len(rules) == 2
    assert rules[0]["bindings"]["point_ids"] == [ACME_LOCAL_OAT_POINT_ID]
    assert float(rules[0]["config"]["max_spread_f"]) == float(ACME_SPREAD_CFG[PHASE_BLATANT]["max_spread_f"])
