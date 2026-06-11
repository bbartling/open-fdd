"""Fault alert model_context enrichment for Building Status."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
API_ROOT = REPO / "workspace" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


def test_enrich_fdd_alert_adds_point_and_equipment():
    from openfdd_bridge.fault_model_context import enrich_fault_alert

    model = {
        "sites": [{"id": "acme", "name": "Acme"}],
        "equipment": [
            {
                "id": "ahu-c",
                "site_id": "acme",
                "name": "AHU-C",
                "equipment_type": "Air_Handling_Unit",
            }
        ],
        "points": [
            {
                "id": "1100-analog-input-1234",
                "site_id": "acme",
                "equipment_id": "ahu-c",
                "external_id": "AHU-C-SAT",
                "brick_type": "Supply_Air_Temperature_Sensor",
                "description": "Supply Air Temperature",
                "bacnet_device_id": 1100,
                "object_identifier": "analog-input,1234",
            }
        ],
    }
    alert = {
        "id": "fdd-1",
        "severity": "warning",
        "source": "fdd",
        "title": "AHU-C · acme-sat-flatline-1h · AHU SAT flatline 1h: 1 fault row(s) at acme",
        "detail": "1/24 samples flagged",
        "code": "acme-sat-flatline-1h",
        "rule_id": "acme-sat-flatline-1h",
        "rule_name": "AHU SAT flatline 1h",
        "equipment_name": "AHU-C",
        "analytics": {"flagged_columns": ["AHU-C-SAT"], "fault_samples": 1, "total_samples": 24},
    }
    out = enrich_fault_alert(alert, model)
    ctx = out["model_context"]
    assert ctx["equipment"]["name"] == "AHU-C"
    assert ctx["point"]["name"] == "Supply Air Temperature"
    assert ctx["historian_column"] == "AHU-C-SAT"
    assert "1100" in ctx["bacnet_summary"]


def test_enrich_graceful_when_unmapped():
    from openfdd_bridge.fault_model_context import enrich_fault_alert

    alert = {
        "source": "fdd",
        "title": "mystery fault",
        "rule_id": "r1",
        "analytics": {},
    }
    out = enrich_fault_alert(alert, {"sites": [], "equipment": [], "points": []})
    assert out["model_context"]["point"]["name"] == "not mapped"
