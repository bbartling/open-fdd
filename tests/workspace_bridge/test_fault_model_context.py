"""Fault alert model_context enrichment."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "workspace" / "api"))

from openfdd_bridge.fault_model_context import enrich_fault_alert  # noqa: E402


def test_enrich_fault_alert_uses_title_equipment_label():
    model = {
        "sites": [{"id": "acme"}],
        "equipment": [{"id": "ahu-1", "site_id": "acme", "name": "AHU-1", "equipment_type": "Air_Handler_Unit"}],
        "points": [],
    }
    alert = {
        "source": "fdd",
        "severity": "warning",
        "title": "AHU-1 — Temperature reading is outside the configured range.",
        "rule_id": "acme-sat-flatline-1h",
        "rule_name": "Temperature out of bounds",
        "short_description": "Temperature reading is outside the configured range.",
        "equipment_name": "AHU-1",
        "equipment_id": "ahu-1",
    }
    out = enrich_fault_alert(alert, model)
    assert out.get("equipment_name") == "AHU-1"
    ctx = out.get("model_context") or {}
    assert ctx.get("equipment", {}).get("name") == "AHU-1"
    assert "Air Handler" in ctx.get("equipment", {}).get("type", "") or ctx.get("equipment", {}).get("type")


def test_enrich_fault_alert_uses_short_description_symptom():
    model = {"sites": [{"id": "acme"}], "equipment": [], "points": []}
    alert = {
        "source": "fdd",
        "severity": "warning",
        "title": "Building — Outdoor air temp flatline 1h",
        "rule_id": "acme-oat-flatline-1h",
        "short_description": "Outdoor air temperature has not changed for one hour.",
    }
    out = enrich_fault_alert(alert, model)
    ctx = out.get("model_context") or {}
    assert ctx.get("symptom") == "Outdoor air temperature has not changed for one hour."
