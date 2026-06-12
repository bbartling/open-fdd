"""Offline ACME FDD audit: duplicates, equipment roles, fault schema."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
API = REPO / "workspace" / "api"
sys.path.insert(0, str(API))

from openfdd_bridge.acme_fdd_audit import (  # noqa: E402
    duplicate_audit,
    equipment_point_role_audit,
    validate_fault_alert_schema,
    validate_fdd_run_schema,
)


def test_duplicate_audit_clean_model():
    model = {
        "equipment": [{"id": "ahu-1", "bacnet_device_instance": 1100, "equipment_type": "AHU"}],
        "points": [{"id": "p1", "equipment_id": "ahu-1"}],
    }
    out = duplicate_audit(model)
    assert out["ok"] is True


def test_duplicate_audit_flags_dup_point_ids():
    model = {
        "equipment": [],
        "points": [{"id": "dup"}, {"id": "dup"}],
    }
    out = duplicate_audit(model)
    assert out["ok"] is False
    assert out["duplicate_point_ids"] == 1


def test_duplicate_audit_flags_dup_bacnet_equipment_ids():
    model = {
        "equipment": [
            {"id": "eq-a", "bacnet_device_instance": 1100},
            {"id": "eq-b", "bacnet_device_instance": 1100},
        ],
        "points": [],
    }
    out = duplicate_audit(model)
    assert out["ok"] is False
    assert out["duplicate_bacnet_equipment_ids"]


def test_equipment_role_audit_finds_ahu_sat():
    model = {
        "equipment": [{"id": "ahu-c", "equipment_type": "AHU", "name": "AHU-C"}],
        "points": [
            {
                "id": "p1",
                "equipment_id": "ahu-c",
                "brick_type": "Supply_Air_Temperature_Sensor",
                "external_id": "sat",
            }
        ],
    }
    out = equipment_point_role_audit(model)
    assert out["ahu_count"] == 1
    assert "supply_air_temperature" in out["ahu_reports"][0]["roles_found"]


def test_fault_alert_missing_equipment_fails_schema():
    alert = {"source": "fdd", "code": "AHU-C", "title": "SAT flatline", "severity": "medium"}
    errs = validate_fault_alert_schema(alert)
    assert any("equipment" in e for e in errs)


def test_fault_alert_with_model_context_passes():
    alert = {
        "source": "fdd",
        "code": "AHU-C",
        "title": "AHU-C · AHU SAT flatline 1h",
        "severity": "medium",
        "model_context": {
            "equipment": {"id": "ahu-c", "name": "AHU-C", "type": "AHU"},
            "rule_id": "acme-sat-flatline-1h",
        },
    }
    assert not validate_fault_alert_schema(alert)


def test_fdd_run_schema_requires_rule_id():
    assert validate_fdd_run_schema({"rule_name": "x", "site_id": "acme"})


def test_acme_gl36_model_no_duplicates_if_present():
    path = REPO / "workspace/data/acme_gl36_model.json"
    if not path.is_file():
        pytest.skip("fixture missing")
    model = json.loads(path.read_text(encoding="utf-8"))
    out = duplicate_audit(model)
    assert out["duplicate_point_ids"] == 0


def test_acme_rtu_role_audit_covers_sat_and_fan_command():
    path = REPO / "workspace/data/acme_gl36_model.json"
    if not path.is_file():
        pytest.skip("fixture missing")
    model = json.loads(path.read_text(encoding="utf-8"))
    out = equipment_point_role_audit(model)
    rtu = next((r for r in out["rtu_reports"] if r["equipment_id"] == "acme-vm-bbartling-rtu-01"), None)
    assert rtu is not None
    assert rtu["equipment_class"] == "RTU"
    assert "supply_air_temperature" in rtu["roles_found"]
    assert "supply_fan_command" in rtu["roles_found"]
    assert "duct_static_pressure" in rtu["roles_found"]
    assert "supply_air_temperature_setpoint" in rtu["roles_missing_optional"]
