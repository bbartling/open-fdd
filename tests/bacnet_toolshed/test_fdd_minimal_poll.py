"""Tests for FDD-minimal BACnet poll filtering."""

from __future__ import annotations

import csv
import io
import json

from bacnet_toolshed.fdd_minimal_poll import collect_fdd_poll_requirements, filter_points_for_fdd_rules


def test_collect_requirements_from_rules():
    rules = [
        {
            "enabled": True,
            "bindings": {"brick_types": ["Zone_Air_Temperature_Sensor"], "point_ids": ["1100-analog-output-1"]},
            "config": {"fan_speed_col": "supply-fan-speed-command"},
        }
    ]
    req = collect_fdd_poll_requirements(rules)
    assert "Zone_Air_Temperature_Sensor" in req["brick_types"]
    assert "1100-analog-output-1" in req["point_ids"]
    assert "supply-fan-speed-command" in req["column_hints"]


def test_filter_points_minimal():
    rules = [{"enabled": True, "bindings": {"brick_types": ["Zone_Air_Temperature_Sensor"]}, "config": {}}]
    rows = [
        {"point_id": "1-ai-1", "brick_class": "Zone_Air_Temperature_Sensor", "enabled": "0"},
        {"point_id": "1-ai-2", "brick_class": "Damper_Position_Sensor", "enabled": "1"},
    ]
    out, manifest = filter_points_for_fdd_rules(rows, rules)
    assert len(out) == 1
    assert out[0]["point_id"] == "1-ai-1"
    assert out[0]["enabled"] == "1"
    assert manifest["matched_rows"] == 1
