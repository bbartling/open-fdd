"""Registry diff guard: optional_roles additions must match rule SQL (#1405 / #1284)."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "ci"))

from unit_contract_lib import validate_registry_role_declarations_diff  # noqa: E402


def _trim3_master_rule() -> dict:
    return {
        "rule_id": "TRIM-3",
        "sql_file": "trim3_hwst.sql",
        "required_roles": ["hw_supply_t"],
        "optional_roles": ["pump_status", "chiller_status", "chw_flow", "chw_pump_cmd"],
        "description": "HWST trim advisory",
    }


def test_rejects_unjustified_optional_roles_addition() -> None:
    master = {"rules": [_trim3_master_rule()]}
    branch = copy.deepcopy(master)
    branch["rules"][0]["optional_roles"] = list(branch["rules"][0]["optional_roles"]) + [
        "totally_fake_role"
    ]
    with pytest.raises(AssertionError, match="optional_roles addition `totally_fake_role`"):
        validate_registry_role_declarations_diff(master, branch)


def test_rejects_required_roles_change() -> None:
    master = {"rules": [_trim3_master_rule()]}
    branch = copy.deepcopy(master)
    branch["rules"][0]["required_roles"] = ["hw_supply_t", "chw_flow"]
    with pytest.raises(AssertionError, match="required_roles changed"):
        validate_registry_role_declarations_diff(master, branch)


def test_allows_sql_justified_optional_roles_addition() -> None:
    master = {"rules": [_trim3_master_rule()]}
    branch = copy.deepcopy(master)
    branch["rules"][0]["optional_roles"] = list(branch["rules"][0]["optional_roles"]) + [
        "hw_reset_request_sum"
    ]
    validate_registry_role_declarations_diff(master, branch)
