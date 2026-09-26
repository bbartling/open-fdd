"""Load history_wide.csv + column_map.json for anomaly screening."""

from __future__ import annotations

from pathlib import Path

from open_fdd.analytics.anomaly.io import iter_ahu_io_points, load_device_folder

FIXTURE = Path(__file__).parent / "fixtures" / "mini_ahu"


def test_iter_ahu_io_points_points_override_column_roles():
    column_map = {
        "equipType": "ahu",
        "column_roles": {
            "mixed-air-temp": "MAT",
            "discharge-air-temp": "DAT_OLD",
        },
        "points": {"discharge-air-temp": "DAT"},
    }
    pairs = iter_ahu_io_points(column_map)
    assert ("mixed-air-temp", "MAT") in pairs
    assert ("discharge-air-temp", "DAT") in pairs
    assert ("discharge-air-temp", "DAT_OLD") not in pairs


def test_haystack_equip_object_when_equipment_missing():
    column_map = {
        "equip": {
            "AHU_1": {"equipType": "ahu", "points": {"discharge-air-temp": "SAT"}},
            "VAV_1": {"equipType": "vav", "points": {"zone-air-temp": "ZT"}},
        }
    }
    assert iter_ahu_io_points(column_map) == [("discharge-air-temp", "SAT")]


def test_empty_equipment_falls_back_to_haystack_equip_object():
    column_map = {
        "equipment": {},
        "equip": {
            "AHU_1": {"equipType": "ahu", "points": {"mixed-air-temp": "MAT"}},
        },
    }
    assert iter_ahu_io_points(column_map) == [("mixed-air-temp", "MAT")]


def test_string_equip_id_keeps_flat_points():
    column_map = {
        "equip": "AHU_1",
        "equipType": "ahu",
        "points": {"discharge-air-temp": "DAT"},
    }
    assert iter_ahu_io_points(column_map) == [("discharge-air-temp", "DAT")]


def test_iter_ahu_io_points_nested_equipment_keeps_ahu_only():
    column_map = {
        "equipment": {
            "AHU_1": {
                "equipType": "ahu",
                "points": {"discharge-air-temp": "SAT", "fan-status": "SF_S"},
            },
            "VAV_1": {
                "equipType": "vav",
                "points": {"zone-air-temp": "ZT"},
            },
        }
    }
    assert iter_ahu_io_points(column_map) == [
        ("discharge-air-temp", "SAT"),
        ("fan-status", "SF_S"),
    ]


def test_load_mini_fixture_resolves_roles_and_skips_missing():
    device = load_device_folder(FIXTURE)
    assert device.frame.index.tz is not None
    assert str(device.frame.index.tz) == "UTC"
    assert ("discharge-air-temp", "DAT") in device.points
    assert ("mixed-air-temp", "MAT") in device.points
    assert ("fan-status", "SF_S") in device.points
    assert all(role != "return-air-temp" for role, _col in device.points)
    assert ("return-air-temp", "RAT_MISSING") in device.missing
    assert "DAT" in device.frame.columns
    assert "RAT_MISSING" not in device.frame.columns
