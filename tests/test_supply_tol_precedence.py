"""#1725: a saved eps_sat wins over the legacy supply_tol master in the SQL renderer, as in JS and the pandas runner."""
from __future__ import annotations

import pytest

from sql.fdd.render_rule import render


@pytest.mark.parametrize("rule_id", ["FC8"])
def test_eps_sat_wins_over_supply_tol(rule_id):
    both = render(rule_id, overrides={"eps_sat": 1.666667, "supply_tol": 0.277778})
    assert "1.666667 * 1.666667" in both and "0.277778" not in both


@pytest.mark.parametrize("rule_id", ["FC8"])
def test_supply_tol_alone_still_sets_eps_sat(rule_id):
    sql = render(rule_id, overrides={"supply_tol": 0.277778})
    assert "0.277778 * 0.277778" in sql


def test_fc12_ignores_both_keys():
    """FC12 exposes eps_sat / supply_tol but its SQL uses neither: every combination renders the same."""
    base = render("FC12")
    assert render("FC12", overrides={"eps_sat": 1.666667, "supply_tol": 0.277778}) == base
