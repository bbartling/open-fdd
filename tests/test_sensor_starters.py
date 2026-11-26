"""#1763: SI sensor starters (role entry, then quantity starter), per-sensor overrides, and saved tuning winning over
every starter. The SQL / pandas engine checks of the same contract are in tests/parity/test_sensor_starters_parity.py."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sql" / "fdd"))
sys.path.insert(0, str(ROOT / "tests"))

import render_rule  # noqa: E402
from open_fdd.rules import RULES_BY_ID  # noqa: E402
from open_fdd.rules import role_limit_overrides as o  # noqa: E402
from open_fdd.rules import sensor_sweep_catalog as cat  # noqa: E402
from test_role_limit_overrides import _Cursor  # noqa: E402

TUNING = {r["rule_id"]: r for r in json.loads((ROOT / "sql" / "fdd" / "tuning_catalog.json").read_text(encoding="utf-8"))["rules"]}


def test_starter_profile_picks_role_then_quantity_and_names_the_source():
    zat = cat.starter_profile("zone-air-temp", "degC")
    assert zat["assessed"] and (zat["lo"], zat["hi"]) == (4.444444, 37.777778)
    assert zat["sources"] == {"lo": "role", "hi": "role", "spike_delta": "role", "flat_tol": "rule tuner", "rate_per_h": "rule tuner"}
    assert zat["flat_tol"] == TUNING["SV-FLATLINE"]["parameters"]["flatline_tol"]["default"]
    rh = cat.starter_profile("zone-air-humidity", "%RH")
    assert rh["flat_tol"] == 0.1 and rh["sources"]["flat_tol"] == "role", "a %RH role never takes the degC tuner"
    # a temperature role with no entry: the quantity starter band; rate stays role-specific (no universal rate)
    other = cat.starter_profile("preheat-leaving-temp", "degC")
    assert other["assessed"] and other["sources"]["lo"] == "quantity starter" and other["lo"] == -51.111111
    assert other["rate_per_h"] is None and other["sources"]["rate_per_h"] == "none"
    chws = cat.starter_profile("chilled-water-supply-temp", "degC")
    assert chws["rate_per_h"] is None, "the air-temperature rate never applies to a water loop"
    assert cat.starter_profile("chw-flow", "L/s")["hi"] == 1500.0


@pytest.mark.parametrize("role, unit, reason", [
    ("zone-air-temp-sp", "degC", "step by design"),
    ("cooling-valve-cmd", "%", "step by design"),
    ("zone-co2", "ppm", "unknown quantity"),
    ("zone-air-temp", "degF", "not the SI unit"),
    ("zone-air-humidity", "degC", "not the SI unit"),
])
def test_unknown_or_unqualified_sensors_are_unassessed_never_pass(role, unit, reason):
    prof = cat.starter_profile(role, unit)
    assert prof["assessed"] is False and reason in prof["reason"]


def test_sensor_override_is_per_point_and_validated():
    limits = o.effective_role_limits(equipment={"version": 1, "roles": {}, "sensors": {
        "zat-2": {"role": "zone-air-temp", "hi": 26.0, "flat_tol": 0.2}}})
    two = cat.starter_profile("zone-air-temp", "degC", series_id="zat-2", limits=limits)
    one = cat.starter_profile("zone-air-temp", "degC", series_id="zat-1", limits=limits)
    assert (two["hi"], two["flat_tol"]) == (26.0, 0.2) and two["sources"]["hi"] == "sensor"
    assert one == cat.starter_profile("zone-air-temp", "degC"), "the other point of the role is untouched"
    # the sensor's own value is matched by series id AND role
    assert cat.sensor_override("zone-air-temp", "zat-2", "hi", limits) == 26.0
    assert cat.sensor_override("return-air-temp", "zat-2", "hi", limits) is None
    for bad in (
        {"version": 1, "roles": {}, "sensors": {"zat'; DROP": {"role": "zone-air-temp", "hi": 26.0}}},
        {"version": 1, "roles": {}, "sensors": {"zat-1\n": {"role": "zone-air-temp", "hi": 26.0}}},
        {"version": 1, "roles": {}, "sensors": {"zat-1": {"role": "nope", "hi": 26.0}}},
        {"version": 1, "roles": {}, "sensors": {"zat-1": {"role": "zone-air-temp"}}},
        {"version": 1, "roles": {}, "sensors": {"zat-1": {"role": "zone-air-temp", "source": 1.0}}},
        {"version": 1, "roles": {}, "sensors": {"zat-1": {"role": "zone-air-temp", "hi": float("nan")}}},
        {"version": 1, "roles": {}, "sensors": []},
    ):
        with pytest.raises(ValueError):
            o.normalize_override(bad)
    with pytest.raises(ValueError, match="must be < hi"):
        o.effective_role_limits(equipment={"version": 1, "roles": {}, "sensors": {"zat-1": {"role": "zone-air-temp", "lo": 30.0, "hi": 20.0}}})
    with pytest.raises(ValueError, match="at one scope"):
        o.merge(None, {"version": 1, "roles": {}, "sensors": {"x-1": {"role": "zone-air-temp", "hi": 26.0}}},
                {"version": 1, "roles": {}, "sensors": {"x-1": {"role": "mixed-air-temp", "hi": 26.0}}})


def test_saved_site_and_equipment_config_wins_over_starters():
    """Saved tuning (rule tuner, site and equipment role overrides, sensor overrides) loaded from fdd.rule_config wins
    over every starter, and keeps winning when the shipped starters change later."""
    cur = _Cursor()
    o.save_override(cur, "s1", "site", {"version": 1, "roles": {"zone-air-temp": {"hi": 30.0, "flat_tol": 0.2}},
                                        "sensors": {"zat-1": {"role": "zone-air-temp", "hi": 25.0, "spike_delta": 3.0}}}, "t")
    o.save_override(cur, "s1", "equip:AHU-1", {"version": 1, "roles": {"zone-air-temp": {"lo": 10.0}},
                                               "sensors": {"zat-1": {"role": "zone-air-temp", "hi": 24.0}}}, "t")
    active = o.active_overrides(cur, "s1")
    site, equip = active["site"]["parameters"], active["equip:AHU-1"]["parameters"]
    saved_tuner = 0.3   # a saved SV-FLATLINE flatline_tol
    for shipped in (None, _shipped_with(lo=0.0, hi=35.0, flat_tol=0.15)):   # today's starters, then changed starters
        limits = o.effective_role_limits(shipped, site, equip)
        zat1 = cat.starter_profile("zone-air-temp", "degC", series_id="zat-1", limits=limits, flatline_tol=saved_tuner)
        assert (zat1["lo"], zat1["hi"], zat1["spike_delta"], zat1["flat_tol"]) == (10.0, 24.0, 3.0, 0.2)
        zat2 = cat.starter_profile("zone-air-temp", "degC", series_id="zat-2", limits=limits, flatline_tol=saved_tuner)
        assert (zat2["lo"], zat2["hi"], zat2["flat_tol"]) == (10.0, 30.0, 0.2)
        oat = cat.starter_profile("outside-air-temp", "degC", limits=limits, flatline_tol=saved_tuner)
        assert oat["flat_tol"] == saved_tuner and oat["sources"]["flat_tol"] == "rule tuner"
        _, sources = o.merge(shipped, site, equip)
        assert sources["sensor:zat-1"]["hi"] == "equipment" and sources["sensor:zat-1"]["spike_delta"] == "site"
        assert sources["sensor:zat-1"]["lo"] == "role"
        sql = render_rule.render("SV-FLATLINE", overrides={"flatline_tol": saved_tuner}, role_limits=limits)
        assert "WHEN sensor_role IN ('zone_t') THEN 0.2" in sql and "ELSE 0.3 END" in sql
        rng = render_rule.render("SV-RANGE", role_limits=limits)
        assert "(series_id = 'zat-1' AND sensor_role = 'zone_t' AND (value < (17.0 - 7.0 * 1) OR value > (17.0 + 7.0 * 1)))" in rng
        assert "(sensor_role = 'zone_t' AND series_id NOT IN ('zat-1') AND (value < (20.0 - 10.0 * 1)" in rng


def _shipped_with(**fields) -> dict:
    doc = copy.deepcopy(o.shipped_document())
    next(e for e in doc["roles"] if e["role"] == "zone-air-temp").update(fields)
    return doc


def test_no_sensor_override_keeps_the_shipped_sql_byte_for_byte():
    limits = o.effective_role_limits(equipment={"version": 1, "roles": {}, "sensors": {}})
    for rid in o.SWEEP_RULES:
        assert render_rule.render(rid, role_limits=limits) == render_rule.render(rid)
    # a sensor value only reaches the rules that use that field
    only_flat = o.effective_role_limits(equipment={"version": 1, "roles": {}, "sensors": {"z-1": {"role": "zone-air-temp", "flat_tol": 0.2}}})
    assert render_rule.render("SV-RANGE", role_limits=only_flat) == render_rule.render("SV-RANGE")
    assert render_rule.render("SV-FLATLINE", role_limits=only_flat) != render_rule.render("SV-FLATLINE")
    assert o.config_hash({"version": 1, "roles": {"zone-air-temp": {"hi": 30.0}}}, None) == \
        o.config_hash({"version": 1, "roles": {"zone-air-temp": {"hi": 30.0}}, "sensors": {}}, None)


def test_fc13_full_cooling_default_is_in_range_and_matches_sql():
    """The pandas clg_full_min default was 0.01, below its own 0.5 minimum; it is the SQL FC13-SAT-HIGH default now."""
    param = next(p for p in RULES_BY_ID["FC13"].params if p.key == "clg_full_min")
    sql = TUNING["FC13-SAT-HIGH"]["parameters"]["clg_full_min"]
    assert param.min <= param.default <= param.max
    assert (param.default, param.min, param.max) == (sql["default"], sql["min"], sql["max"]) == (0.9, 0.5, 1.0)
    for rule in RULES_BY_ID.values():
        for p in rule.params or []:
            assert p.min <= p.default <= p.max, (rule.id, p.key, p.min, p.default, p.max)
