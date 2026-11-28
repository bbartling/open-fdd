"""FC15 applies only when a hot-water coil is actually bound (#1826)."""

from pathlib import Path

import pandas as pd

from open_fdd.rules.cookbook_catalog import RULES_BY_ID
from open_fdd.rules.runner import run_cookbook_rule

ROOT = Path(__file__).resolve().parents[1]
SQL = (ROOT / "sql/fdd/postgres/rules/fc15_hw_coil_dt_inactive.sql").read_text(encoding="utf-8")


def test_gas_rtu_with_mat_sat_and_no_hw_coil_is_skipped():
    rule = RULES_BY_ID["FC15"]
    assert rule.required_roles == [
        "heating_coil_inlet_air_temperature",
        "heating_coil_outlet_air_temperature",
        "outdoor_air_intake_damper_position_command",
        "cooling_valve_position_command",
    ]
    idx = pd.date_range("2026-11-27", periods=6, freq="5min", tz="UTC")
    frame = pd.DataFrame(
        {
            "mixed_air_temperature": [19.4] * 6,
            "discharge_air_temperature": [20.6] * 6,
            "supply_fan_operating_status": [1] * 6,
            "supply_fan_command": [1] * 6,
        },
        index=idx,
    )
    result = run_cookbook_rule(
        rule, frame, equipment_id="RTU-01", equipment_kind="ahu", poll_seconds=300, require_operational_gates=False,
    )
    assert result.status == "SKIPPED_MISSING_ROLES"
    assert "heating_coil_inlet_air_temperature" in result.missing_roles
    assert "heating_coil_outlet_air_temperature" in result.missing_roles
    assert "heating_coil_inlet_air_temperature AS enter_t" in SQL
    assert "COALESCE(heating_coil_inlet_air_temperature, mixed_air_temperature)" not in SQL
    assert "COALESCE(heating_coil_outlet_air_temperature, discharge_air_temperature)" not in SQL
    registry = (ROOT / "sql/fdd/registry.yaml").read_text(encoding="utf-8")
    start = registry.index("rule_id: FC15")
    block = registry[start:registry.index("\n- rule_id:", start + 10)]
    assert "heating_coil_inlet_air_temperature" in block.split("optional_roles:")[0]
    assert "mixed_air_temperature" not in block and "discharge_air_temperature" not in block
