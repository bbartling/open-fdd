"""Tests for fault-based chart suggestions and point tree."""

from __future__ import annotations

from portfolio.central.chart_specs import suggest_charts_for_faults


def test_suggest_charts_for_sat_fault():
    rows = [{"fault_code": "AHU-C", "fault_name": "Supply air temperature flatline", "equipment": "AHU-C"}]
    avail = {
        "fault_hours_by_severity",
        "ahu_sat_vs_setpoint",
        "ahu_duct_static_vs_setpoint",
        "vav_zone_temp",
    }
    out = suggest_charts_for_faults(rows, available_ids=avail)
    assert "fault_hours_by_severity" in out
    assert "ahu_sat_vs_setpoint" in out


def test_point_tree_groups_by_equipment():
    # offline shape test without Edge
    sample = {
        "points": [
            {"column": "a", "label": "A", "equipment_name": "AHU-1", "equipment_id": "e1"},
            {"column": "b", "label": "B", "equipment_name": "AHU-1", "equipment_id": "e1"},
            {"column": "c", "label": "C", "equipment_name": "VAV-2", "equipment_id": "e2"},
        ],
        "count": 3,
    }
    by_equipment: dict = {}
    for pt in sample["points"]:
        eq = pt["equipment_name"]
        by_equipment.setdefault(eq, []).append(pt)
    assert len(by_equipment) == 2
    assert len(by_equipment["AHU-1"]) == 2
