"""Tests for historian column + role resolution."""

from __future__ import annotations

from portfolio.central.trend_charts import (
    _role_matches,
    columns_for_roles,
    historian_column_for_point,
    resolve_roles_on_tree,
)


def test_historian_column_uses_point_id():
    pt = {"id": "1100-unknown-1", "name": "Supply Air Temperature Local", "external_id": ""}
    assert historian_column_for_point(pt) == "1100-unknown-1"


def test_role_matches_supply_air_brick_type():
    pt = {
        "brick_type": "Supply_Air_Temperature_Sensor",
        "brick_tag": "SAT",
        "id": "1100-unknown-1",
    }
    assert _role_matches(pt, "supply_air_temperature")


def test_role_matches_duct_static_brick_type():
    pt = {"brick_type": "Supply_Air_Static_Pressure_Sensor", "brick_tag": "SAP", "id": "1100-unknown-5"}
    assert _role_matches(pt, "duct_static_pressure")


def test_columns_for_roles_from_tree():
    tree = {
        "points": [
            {
                "id": "1100-unknown-1",
                "brick_type": "Supply_Air_Temperature_Sensor",
                "brick_tag": "SAT",
            },
            {
                "id": "1100-unknown-5",
                "brick_type": "Supply_Air_Static_Pressure_Sensor",
                "brick_tag": "SAP",
            },
        ]
    }
    sat_cols = columns_for_roles(tree, ["supply_air_temperature"])
    dsp_cols = columns_for_roles(tree, ["duct_static_pressure"])
    assert sat_cols == ["1100-unknown-1"]
    assert dsp_cols == ["1100-unknown-5"]


def test_resolve_roles_partial_setpoint_missing():
    tree = {
        "points": [
            {"id": "1100-unknown-1", "brick_type": "Supply_Air_Temperature_Sensor", "brick_tag": "SAT"},
        ]
    }
    cols, missing = resolve_roles_on_tree(
        tree, ["supply_air_temperature", "supply_air_temperature_setpoint"]
    )
    assert cols == ["1100-unknown-1"]
    assert "supply_air_temperature_setpoint" in missing
