"""Tests for analyst run_fdd pipeline."""

from pathlib import Path

import pandas as pd
import pytest

from open_fdd.analyst.config import AnalystConfig, default_analyst_config
from open_fdd.analyst.run_fdd import run_fdd_pipeline, _filter_rules_by_equipment


def test_filter_rules_by_equipment():
    """Filter rules by equipment type from Brick."""
    rules = [
        {"name": "hp_rule", "equipment_type": ["Heat_Pump"]},
        {"name": "ahu_rule", "equipment_type": ["AHU"]},
        {"name": "any_rule"},  # no equipment_type = applies to all
    ]
    filtered = _filter_rules_by_equipment(rules, ["Heat_Pump"])
    assert len(filtered) == 2  # hp_rule + any_rule
    names = [r["name"] for r in filtered]
    assert "hp_rule" in names
    assert "any_rule" in names
    assert "ahu_rule" not in names


def test_filter_rules_empty_equipment_types():
    """Empty equipment_types returns all rules."""
    rules = [{"name": "x", "equipment_type": ["Heat_Pump"]}]
    filtered = _filter_rules_by_equipment(rules, [])
    assert len(filtered) == 1


@pytest.fixture
def tmp_analyst_dir(tmp_path):
    """Create minimal analyst dir with heat_pumps.csv and brick TTL."""
    data = tmp_path / "data"
    data.mkdir()
    rules = tmp_path / "rules"
    rules.mkdir()

    # Minimal heat pump data
    df = pd.DataFrame(
        {
            "equipment_id": ["hp_1"] * 30,
            "timestamp": pd.date_range("2024-01-15", periods=30, freq="5min"),
            "sat": [72.0] * 15 + [70.0] * 15,  # some < 80 when heating
            "zt": [68.0] * 30,  # zone cold
            "fan_status": [1.0] * 30,  # fan on
        }
    )
    df.to_csv(data / "heat_pumps.csv", index=False)

    # Brick TTL for Heat_Pump (need rdfs:label for brick_resolver column_map)
    ttl = """@prefix brick: <https://brickschema.org/schema/Brick#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ofdd: <http://openfdd.local/ontology#> .
@prefix : <http://openfdd.local/test#> .
:site_1 a brick:Site ; rdfs:label "Test" .
:hp_1 a brick:Heat_Pump ; brick:isPartOf :site_1 ; ofdd:equipmentType "Heat_Pump" .
:hp_1_sat a brick:Supply_Air_Temperature_Sensor ; rdfs:label "sat" ; brick:isPointOf :hp_1 ; ofdd:mapsToRuleInput "sat" .
:hp_1_zt a brick:Zone_Temperature_Sensor ; rdfs:label "zt" ; brick:isPointOf :hp_1 ; ofdd:mapsToRuleInput "zt" .
:hp_1_fan a brick:Supply_Fan_Status ; rdfs:label "fan_status" ; brick:isPointOf :hp_1 ; ofdd:mapsToRuleInput "fan_status" .
"""
    (data / "brick_model.ttl").write_text(ttl)

    # Copy heat pump rules
    rules_src = Path(__file__).resolve().parent.parent.parent / "rules"
    for name in [
        "hp_discharge_cold_when_heating.yaml",
        "sensor_bounds.yaml",
        "sensor_flatline.yaml",
    ]:
        src = rules_src / name
        if src.exists():
            (rules / name).write_text(src.read_text())

    return tmp_path


def test_run_fdd_pipeline(tmp_analyst_dir):
    """Run FDD pipeline on mock heat pump data."""
    cfg = AnalystConfig(
        data_root=tmp_analyst_dir / "data",
        reports_root=tmp_analyst_dir / "reports",
        rules_root=tmp_analyst_dir / "rules",
        rolling_window=3,
    )
    cfg.__post_init__()

    summary, result_by_eq, column_map, rules, flag_cols = run_fdd_pipeline(config=cfg)

    assert len(summary) >= 1
    assert "equipment_id" in summary.columns
    assert "hp_discharge_cold_flag" in flag_cols or "bad_sensor_flag" in flag_cols
    assert "sat" in column_map or "Supply_Air_Temperature_Sensor" in column_map
