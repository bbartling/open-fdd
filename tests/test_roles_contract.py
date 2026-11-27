"""Rule inputs use roles/openfdd-roles.json names. Legacy keys still resolve (#1812)."""
from __future__ import annotations

import json
import warnings
from pathlib import Path

import pytest

from open_fdd.nf.model import Point, role_score
from open_fdd.role_vocab import (
    CORE_VERSION,
    ambiguous_legacy_names,
    legacy_to_role,
    migrate_saved,
    percent_roles,
    resolve_role,
    rule_input_names,
    wire_unit,
)

ROOT = Path(__file__).resolve().parents[1]


def _contract():
    return json.loads((ROOT / "sql/fdd/input_contract.json").read_text(encoding="utf-8"))


def _catalog():
    return json.loads((ROOT / "nf-app/static/fdd-catalog.json").read_text(encoding="utf-8"))


def _roles():
    return json.loads((ROOT / "roles/openfdd-roles.json").read_text(encoding="utf-8"))


def test_rule_inputs_are_the_canonical_roles():
    doc = _roles()
    assert doc["version"] == "1.1.0-draft.1"
    names = rule_input_names()
    assert len(names) == 76
    assert "supply_fan_speed_command" not in names
    contract = _contract()["roles"]
    # FC1 reads speed. It stays out of the rule_input set and in the history contract.
    assert set(names) | {"supply_fan_speed_command"} == set(contract)
    by_name = {row["role"]: row for row in doc["roles"]}
    for name in names:
        assert contract[name]["scale"] == (wire_unit(by_name[name]) or "boolean")
    assert contract["supply_fan_speed_command"]["scale"] == "PERCENT"
    assert "fraction" not in {spec["scale"] for spec in contract.values()}


def test_position_roles_are_percent_and_commands_are_boolean():
    contract = _contract()["roles"]
    for role in (
        "outdoor_air_intake_damper_position_command",
        "cooling_valve_position_command",
        "heating_valve_position_command",
        "terminal_unit_heating_valve_position_command",
        "damper_position",
        "damper_position_command",
        "supply_fan_speed_command",
    ):
        assert contract[role]["scale"] == "PERCENT"
    for role in (
        "supply_fan_command",
        "return_fan_command",
        "chiller_command",
        "chilled_water_pump_command",
        "condenser_water_pump_command",
        "cooling_tower_fan_command",
    ):
        assert contract[role]["scale"] == "boolean"


def test_legacy_keys_resolve_and_ambiguous_names_do_not():
    assert resolve_role("sat") == "discharge_air_temperature"
    with pytest.warns(DeprecationWarning, match="sat"):
        assert resolve_role("sat", warn=True) == "discharge_air_temperature"
    assert resolve_role("boiler_status") == "boiler_operating_status"
    assert resolve_role("filter_dp") == "filter_air_pressure_delta"
    assert resolve_role("fan_power") == "supply_fan_electric_power"
    assert resolve_role("discharge-air-temp") == "discharge_air_temperature"
    assert resolve_role("fan-cmd") == "supply_fan_command"
    assert resolve_role("fan-status") == "supply_fan_operating_status"
    assert resolve_role("outside-air-damper") == "outdoor_air_intake_damper_position_command"
    for name in ambiguous_legacy_names():
        assert resolve_role(name) == name
        assert name not in legacy_to_role()


def test_catalog_bindings_follow_the_roles_file_and_honor_forbid():
    doc = _roles()
    catalog = _catalog()["roles"]
    by_name = {row["role"]: row for row in doc["roles"]}
    for name, spec in catalog.items():
        hs = by_name[name]["haystack"]
        assert spec["classes"] == (hs.get("classes") or [])
        assert spec["markers"] == (hs.get("markers") or [])
        if hs.get("forbid"):
            assert spec["forbid"] == hs["forbid"]
    setpoint = catalog["discharge_air_volume_flow_rate_setpoint"]
    def point(name, cls, tags):
        return Point(name, name, name, tags, "", "", "", "", "", "", cls, None)

    max_flow = point("max-flow", "air-flow-sp", ["air", "flow", "sp", "max"])
    assert role_score(max_flow, "discharge_air_volume_flow_rate_setpoint", setpoint) == 0
    plain = point("flow-sp", "air-flow-sp", ["air", "flow", "sp"])
    assert role_score(plain, "discharge_air_volume_flow_rate_setpoint", setpoint) == 2
    damper = catalog["damper_position"]
    cmd = point("damper-cmd", "damper-cmd", ["damper", "cmd"])
    assert role_score(cmd, "damper_position", damper) == 0


def test_migrate_saved_is_idempotent():
    points = [
        {"role": "clg_valve_pct", "si_scale": 1},
        {"role": "oa_damper_pct", "si_scale": 0.01},
        {"role": "fan_cmd", "si_scale": 1},
    ]
    configs = [{"parameters": {"eps_vfd_spd": 0.13, "fan_on_min": 0.05, "roles": {"sat": {"lo": 1}}}}]
    once_points, once_configs, version, changed = migrate_saved(points, configs, 4)
    assert changed and version == CORE_VERSION
    assert once_points[0]["role"] == "cooling_valve_position_command" and once_points[0]["si_scale"] == 100
    assert once_points[1]["role"] in percent_roles() and once_points[1]["si_scale"] == 1
    assert once_points[2]["role"] == "supply_fan_command" and once_points[2]["si_scale"] == 1
    assert once_configs[0]["parameters"]["eps_vfd_spd"] == pytest.approx(13.0)
    assert once_configs[0]["parameters"]["fan_on_min"] == pytest.approx(0.05)
    assert "discharge_air_temperature" in once_configs[0]["parameters"]["roles"]
    again = migrate_saved(once_points, once_configs, version)
    assert again[3] is False
    assert again[0][0]["si_scale"] == 100
    assert again[1][0]["parameters"]["eps_vfd_spd"] == pytest.approx(13.0)


def test_fc1_requires_speed_and_speed_is_not_a_rule_input():
    registry_text = (ROOT / "sql/fdd/registry.yaml").read_text(encoding="utf-8")
    assert "supply_fan_speed_command" in registry_text
    sql = (ROOT / "sql/fdd/postgres/rules/fc1_duct_static_low.sql").read_text(encoding="utf-8")
    assert "supply_fan_speed_command AS fan_for_hi" in sql
    assert "100.0 - {{EPS_VFD_SPD}}" in sql
    warnings.filterwarnings("ignore", category=DeprecationWarning)
