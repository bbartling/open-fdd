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
        "heating-coil-entering-temp",
        "heating-coil-leaving-temp",
        "outside-air-damper",
        "cooling-valve",
    ]
    idx = pd.date_range("2026-11-27", periods=6, freq="5min", tz="UTC")
    frame = pd.DataFrame(
        {
            "mat": [19.4] * 6,
            "sat": [20.6] * 6,
            "fan-status": [1] * 6,
            "fan-cmd": [1] * 6,
        },
        index=idx,
    )
    result = run_cookbook_rule(
        rule, frame, equipment_id="RTU-01", equipment_kind="ahu", poll_seconds=300, require_operational_gates=False,
    )
    assert result.status == "SKIPPED_MISSING_ROLES"
    assert "heating-coil-entering-temp" in result.missing_roles
    assert "heating-coil-leaving-temp" in result.missing_roles
    assert "heating_coil_entering_temp AS enter_t" in SQL
    assert "COALESCE(heating_coil_entering_temp, mat)" not in SQL
    assert "COALESCE(heating_coil_leaving_temp, sat)" not in SQL
    registry = (ROOT / "sql/fdd/registry.yaml").read_text(encoding="utf-8")
    start = registry.index("rule_id: FC15")
    block = registry[start:registry.index("\n  - rule_id:", start + 10)]
    assert "heating_coil_entering_temp" in block.split("optional_roles:")[0]
    assert " mat," not in block and " sat," not in block
