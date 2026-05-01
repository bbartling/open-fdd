from __future__ import annotations

from open_fdd.engine.column_map_from_model import build_column_map_from_model_points


def test_build_column_map_from_model_points_maps_brick_and_fdd_input() -> None:
    model = {
        "points": [
            {
                "site_id": "s1",
                "external_id": "RTU_11_DA_T(°F)",
                "brick_type": "Supply_Air_Temperature_Sensor",
                "fdd_input": "FDD_Supply_Temp",
            },
            {
                "site_id": "s1",
                "external_id": "RTU_11_MA_T(°F)",
                "brick_type": "Mixed_Air_Temperature_Sensor",
                "fdd_input": "FDD_Mixed_Temp",
            },
        ],
    }
    m = build_column_map_from_model_points(model, "s1")
    assert m["Supply_Air_Temperature_Sensor"] == "RTU_11_DA_T(°F)"
    assert m["Mixed_Air_Temperature_Sensor"] == "RTU_11_MA_T(°F)"
    assert m["FDD_Supply_Temp"] == "RTU_11_DA_T(°F)"
    assert m["FDD_Mixed_Temp"] == "RTU_11_MA_T(°F)"


def test_build_column_map_from_model_points_filters_by_site() -> None:
    model = {
        "points": [
            {"site_id": "s1", "external_id": "a", "brick_type": "B1"},
            {"site_id": "s2", "external_id": "b", "brick_type": "B2"},
        ],
    }
    assert build_column_map_from_model_points(model, "s1") == {"B1": "a"}
    assert build_column_map_from_model_points(model, "") == {"B1": "a", "B2": "b"}
