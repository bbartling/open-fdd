"""RCx placeholder hint resolution (data model → DOCX instructions)."""

from __future__ import annotations

import json
from pathlib import Path

FIXTURE_DIR = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "rcx"


def test_chart_placeholder_equipment_columns():
    from open_fdd.reports.rcx_placeholders import chart_placeholder_spec

    catalog = json.loads((FIXTURE_DIR / "chart_catalog.json").read_text(encoding="utf-8"))
    spec = chart_placeholder_spec(
        "eq:acme-vm-bbartling-rtu-01:sat_vs_sp",
        equipment_charts=catalog["equipment_charts"],
        catalog=catalog["available_charts"],
    )
    assert spec["family"] == "ahu"
    assert "supply_air_temperature_local" in spec["instruction"]
    assert spec["title"].startswith("AHU 01")


def test_chart_placeholder_building_roles():
    from open_fdd.reports.rcx_placeholders import chart_placeholder_spec

    catalog = json.loads((FIXTURE_DIR / "chart_catalog.json").read_text(encoding="utf-8"))
    spec = chart_placeholder_spec("ahu_sat_vs_setpoint", catalog=catalog["available_charts"])
    assert "supply_air_temperature" in spec["instruction"]
    assert spec["equipment_type"] == "AHU"


def test_disabled_chart_notes():
    from open_fdd.reports.rcx_placeholders import disabled_chart_notes

    catalog = json.loads((FIXTURE_DIR / "chart_catalog.json").read_text(encoding="utf-8"))
    notes = disabled_chart_notes(catalog["disabled_charts"])
    assert len(notes) == 1
    assert "zone_cooling_setpoint" in notes[0]
    assert "missing BRICK" in notes[0]


def test_rule_sensor_placeholder():
    from open_fdd.reports.rcx_placeholders import rule_sensor_placeholder

    ctx = json.loads((FIXTURE_DIR / "report_context.json").read_text(encoding="utf-8"))
    rule = ctx["assigned_rules"][0]
    rows = rule_sensor_placeholder(rule)
    assert len(rows) == 1
    assert rows[0]["column"] == "space_temperature_local"
    assert "Paste screenshot" in rows[0]["instruction"]
