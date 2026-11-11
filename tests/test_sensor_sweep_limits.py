"""One typed SI role-limit source (open_fdd/data/sensor_sweep_limits.json) feeds the SQL renderer and the pandas sweeps (#1581)."""
from __future__ import annotations

import copy
import json
import math
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sql" / "fdd"))

import render_rule  # noqa: E402
from open_fdd.rules import RULES_BY_ID  # noqa: E402
from open_fdd.rules import sensor_sweep_catalog as cat  # noqa: E402
from open_fdd.rules.runner import run_cookbook_rule  # noqa: E402

LIMITS_FILE = ROOT / "open_fdd" / "data" / "sensor_sweep_limits.json"
PLANT_ROLES = ("chw-flow", "chw-diff-pressure", "condenser-water-supply-temp", "condenser-water-return-temp", "chiller-power")


def _doc() -> dict:
    return json.loads(LIMITS_FILE.read_text(encoding="utf-8"))


def _entry(doc: dict, role: str) -> dict:
    return next(e for e in doc["roles"] if e["role"] == role)


def test_global_defaults_equal_the_sql_tuning_catalog():
    """The shipped defaults block is the same SI number the SQL tuners start from (no second copy drifting)."""
    catalog = {r["rule_id"]: r["parameters"] for r in json.loads((ROOT / "sql/fdd/tuning_catalog.json").read_text(encoding="utf-8"))["rules"]}
    defaults = cat.ROLE_LIMITS["defaults"]
    assert defaults["flat_tol_temperature"] == catalog["SV-FLATLINE"]["flatline_tol"]["default"]
    assert defaults["stale_tol_temperature"] == catalog["SV-STALE"]["stale_tol"]["default"]
    assert defaults["rate_per_h"] == catalog["SV-RATE"]["steady_fault_per_hour"]["default"]
    assert defaults["flat_s"] == catalog["SV-FLATLINE"]["flatline_hours"]["default"] * 3600
    assert defaults["stale_s"] == catalog["SV-STALE"]["stale_hours"]["default"] * 3600


def test_every_allowlisted_role_has_a_limits_entry_with_a_quantity():
    roles = cat.ROLE_LIMITS["roles"]
    for rule_id, names in cat.ASSESSABLE_ROLES_BY_SWEEP.items():
        for name in names:
            assert name in roles, (rule_id, name)
    for entry in roles.values():
        assert entry["source"]


def test_default_render_keeps_the_legacy_sql_literals():
    """The default rendering is the 5.0.12 SQL: same center/half-width, deltas and humidity tolerances."""
    rng = render_rule.render("SV-RANGE")
    assert "(sensor_role = 'oa_t' AND (value < (1.666667 - 52.777778 * 1) OR value > (1.666667 + 52.777778 * 1)))" in rng
    assert "(sensor_role = 'duct_static' AND (value < (870.94 - 1119.78 * 1)" in rng
    assert "{{" not in rng
    assert "ABS(value - previous_value) > 20.0 * 1" in render_rule.render("SV-SPIKE")
    assert "CASE WHEN sensor_role IN ('oa_h','ra_h','zone_rh','ma_h','sa_h') THEN 0.1 ELSE 0.055556 END" in render_rule.render("SV-FLATLINE")
    assert "CASE WHEN sensor_role IN ('oa_h','ra_h','zone_rh','ma_h','sa_h') THEN 0.05 ELSE 0.027778 END" in render_rule.render("SV-STALE")
    assert "(3.333333 * 100 / 100.0)" in render_rule.render("SV-RATE")


def test_plant_roles_are_si_and_conservative():
    roles = cat.ROLE_LIMITS["roles"]
    expected_quantity = {"chw-flow": "volume_flow", "chw-diff-pressure": "air_pressure", "chiller-power": "power",
                         "condenser-water-supply-temp": "absolute_temperature", "condenser-water-return-temp": "absolute_temperature"}
    for role in PLANT_ROLES:
        assert roles[role]["quantity"] == expected_quantity[role]
        assert role in cat.ASSESSABLE_ROLES_BY_SWEEP["SV-RANGE"]
    assert cat.unit_declares_quantity("L/s", "volume_flow") and not cat.unit_declares_quantity("gpm", "volume_flow")
    assert cat.unit_declares_quantity("kW", "power") and not cat.unit_declares_quantity("W", "power")
    rng = render_rule.render("SV-RANGE")
    for sql_role in ("chw_flow", "chw_dp", "cw_supply_t", "cw_return_t", "chiller_power"):
        assert f"sensor_role = '{sql_role}'" in rng


@pytest.mark.parametrize("mutate, message", [
    (lambda d: _entry(d, "zone-air-temp").update(lo=40.0), "must be < hi"),
    (lambda d: _entry(d, "zone-air-temp").update(hi=float("nan")), "finite"),
    (lambda d: _entry(d, "zone-air-temp").update(hi=float("inf")), "finite"),
    (lambda d: _entry(d, "zone-air-temp").update(lo=True), "finite"),
    (lambda d: _entry(d, "zone-air-temp").update(hi="38"), "finite"),
    (lambda d: _entry(d, "zone-air-temp").update(spike_delta=0.0), "> 0"),
    (lambda d: _entry(d, "zone-air-temp").update(spike_delta=None), "needs spike_delta"),
    (lambda d: _entry(d, "zone-air-temp").update(quantity="kelvin"), "unknown quantity"),
    (lambda d: _entry(d, "zone-air-temp").update(source=""), "source"),
    (lambda d: _entry(d, "zone-air-humidity").update(flat_tol=None), "needs flat_tol"),
    (lambda d: _entry(d, "zone-air-temp").update(rate_per_h=-1.0), "> 0"),
    (lambda d: d["roles"].append(copy.deepcopy(_entry(d, "zone-air-temp"))), "duplicate"),
    (lambda d: d["roles"].remove(_entry(d, "return-air-temp")), "no limits entry"),
    (lambda d: _entry(d, "zone-air-temp").update(extra=1), "exactly"),
    (lambda d: d["defaults"].update(rate_per_h=0), "> 0"),
    (lambda d: d.update(version=2), "version"),
])
def test_invalid_limits_are_rejected(mutate, message):
    doc = _doc()
    mutate(doc)
    with pytest.raises(ValueError, match=message):
        cat.load_role_limits(doc)


def _frame(role: str, values, unit: str) -> pd.DataFrame:
    idx = pd.date_range("2026-01-05", periods=len(values), freq="5min", tz="UTC", name="timestamp_utc")
    df = pd.DataFrame({role: pd.Series(values, index=idx, dtype=float)}, index=idx)
    df.attrs.update({"equipment_id": "FIXTURE", "equipment_type": "AHU", "units_map": {role: unit}, "role_units": {role: unit}})
    return df


def _range_hours(df: pd.DataFrame, role: str, limits: dict | None = None) -> float:
    if limits is not None:
        df.attrs["sweep_limits"] = limits
    res = run_cookbook_rule(RULES_BY_ID["SV-RANGE"], df, equipment_id="FIXTURE", equipment_kind="ahu", poll_seconds=300.0,
                            params_by_rule={"SV-RANGE": {"confirm_min": 0.0}}, weather=None, require_operational_gates=True)
    evidence = {e["role"]: e["fault_hours"] for e in (res.metrics.get("sv_sweep_evidence") or [])}
    return float(evidence.get(role, 0.0))


def test_chw_flow_out_of_range_faults():
    n = 36
    healthy = _frame("chw-flow", [120.0] * n, "L/s")
    assert _range_hours(healthy, "chw-flow") == 0.0
    over = _frame("chw-flow", [120.0] * 12 + [2000.0] * 12 + [120.0] * 12, "L/s")
    assert _range_hours(over, "chw-flow") > 0.0
    negative = _frame("chw-flow", [120.0] * 12 + [-50.0] * 12 + [120.0] * 12, "L/s")
    assert _range_hours(negative, "chw-flow") > 0.0
    # a non-SI flow unit is never assessed or converted
    gpm = _frame("chw-flow", [2000.0] * n, "gpm")
    assert _range_hours(gpm, "chw-flow") == 0.0


def test_override_changes_the_rendered_sql_and_the_pandas_result_identically():
    doc = _doc()
    _entry(doc, "zone-air-temp").update(lo=10.0, hi=22.0)  # centre 16, half-width 6
    limits = cat.load_role_limits(doc)

    default_sql, override_sql = render_rule.render("SV-RANGE"), render_rule.render("SV-RANGE", role_limits=limits)
    assert default_sql != override_sql
    assert "(sensor_role = 'zone_t' AND (value < (16.0 - 6.0 * 1) OR value > (16.0 + 6.0 * 1)))" in override_sql
    assert "(sensor_role = 'zone_t' AND (value < (21.111111 - 16.666667" in default_sql
    # roles that were not overridden render exactly as before
    assert "(sensor_role = 'rat' AND (value < (21.111111 - 16.666667" in override_sql

    values = [20.0] * 12 + [23.0] * 12 + [20.0] * 12  # 23 degC is inside the default band, outside the override
    assert _range_hours(_frame("zone-air-temp", values, "degC"), "zone-air-temp") == 0.0
    over = _range_hours(_frame("zone-air-temp", values, "degC"), "zone-air-temp", limits)
    assert over == pytest.approx(12 * 300 / 3600)


def test_per_role_tolerance_and_spike_overrides_render_and_apply():
    doc = _doc()
    _entry(doc, "zone-air-temp").update(flat_tol=0.2, stale_tol=0.3, spike_delta=2.5)
    _entry(doc, "outside-air-temp").update(rate_per_h=1.5)
    limits = cat.load_role_limits(doc)
    flat = render_rule.render("SV-FLATLINE", role_limits=limits)
    assert "WHEN sensor_role IN ('zone_t') THEN 0.2" in flat and "THEN 0.1" in flat and "ELSE 0.055556 END" in flat
    assert "WHEN sensor_role IN ('zone_t') THEN 0.3" in render_rule.render("SV-STALE", role_limits=limits)
    assert "(sensor_role = 'zone_t' AND previous_value IS NOT NULL" in render_rule.render("SV-SPIKE", role_limits=limits)
    assert "ABS(value - previous_value) > 2.5 * 1" in render_rule.render("SV-SPIKE", role_limits=limits)
    assert "WHEN sensor_role = 'oa_t' THEN (1.5 * 100 / 100.0)" in render_rule.render("SV-RATE", role_limits=limits)
    # pandas reads the same numbers
    assert cat.flatline_tolerance_for_role("zone-air-temp", 0.055556, limits) == 0.2
    assert cat.stale_tolerance_for_role("zone-air-temp", 0.027778, limits) == 0.3
    assert cat.limits_for_haystack_role("zone-air-temp", limits)["spike"] == 2.5
    # untouched roles keep following the rule tuner (temperature) or their declared value (humidity)
    assert cat.flatline_tolerance_for_role("return-air-temp", 0.07, limits) == 0.07
    assert cat.flatline_tolerance_for_role("zone-air-humidity", 0.07, limits) == 0.1
    assert cat.stale_tolerance_for_role("zone-air-humidity", 0.07, limits) == 0.05


def test_render_is_deterministic_and_finite():
    for rule_id in cat.ASSESSABLE_ROLES_BY_SWEEP:
        sql = render_rule.render(rule_id)
        assert sql == render_rule.render(rule_id)
        assert "{{" not in sql
    assert all(math.isfinite(e["lo"]) and math.isfinite(e["hi"]) for e in cat.ROLE_LIMITS["roles"].values())
