"""Fault alert model_context enrichment."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "workspace" / "api"))

from openfdd_bridge.fault_model_context import enrich_fault_alert  # noqa: E402


def test_enrich_fault_alert_uses_title_equipment_label():
    model = {"sites": [{"id": "acme"}], "equipment": [], "points": []}
    alert = {
        "source": "fdd",
        "code": "AHU-C",
        "severity": "warning",
        "title": "AHU-C · AHU SAT flatline 1h: 1 fault row(s) at acme",
        "rule_id": "acme-sat-flatline-1h",
        "rule_name": "AHU SAT flatline 1h",
    }
    out = enrich_fault_alert(alert, model)
    assert out.get("equipment_name") == "AHU-C"
    ctx = out.get("model_context") or {}
    assert ctx.get("equipment", {}).get("name") == "AHU-C"
    assert ctx.get("equipment", {}).get("type") == "AHU"
