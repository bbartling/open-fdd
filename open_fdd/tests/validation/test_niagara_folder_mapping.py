"""Tests for Niagara folder → building mapping helpers."""

from __future__ import annotations

from open_fdd.validation.niagara_folder_mapping import (
    infer_building_folders,
    map_folder_to_site,
    ord_segments,
    preview_import_stats,
)


def test_ord_segments():
    assert ord_segments("slot:/Drivers/BldgA/HVAC") == ["Drivers", "BldgA", "HVAC"]


def test_infer_building_folders():
    nodes = [
        {"ord": "slot:/Drivers", "name": "Drivers", "parent_ord": ""},
        {"ord": "slot:/Drivers/BldgA", "name": "BldgA", "parent_ord": "slot:/Drivers"},
        {"ord": "slot:/Drivers/BldgB", "name": "BldgB", "parent_ord": "slot:/Drivers"},
        {"ord": "slot:/Drivers/BldgA/HVAC", "name": "HVAC", "parent_ord": "slot:/Drivers/BldgA", "type": "folder"},
        {"ord": "slot:/Drivers/BldgA/HVAC/ZN-T", "name": "ZN-T", "parent_ord": "slot:/Drivers/BldgA/HVAC", "type": "point"},
    ]
    buildings = infer_building_folders(nodes, min_children=1)
    ords = {b["folder_ord"] for b in buildings}
    assert "slot:/Drivers" in ords
    assert "slot:/Drivers/BldgA" in ords


def test_preview_import_stats_duplicates():
    points = [
        {"point_ord": "slot:/Drivers/BldgA/ZN-T", "equipment_id": "AHU-1"},
        {"point_ord": "slot:/Drivers/BldgA/ZN-T", "equipment_id": "AHU-1"},
        {"point_ord": "slot:/Drivers/BldgB/ZN-T", "equipment_id": "AHU-2"},
    ]
    stats = preview_import_stats(points, root_ord="slot:/Drivers")
    assert stats["point_count"] == 2
    assert stats["duplicate_ord_count"] == 1
    assert stats["equipment_count"] == 2


def test_map_folder_to_site():
    mapped = map_folder_to_site("slot:/Drivers/BldgA", station_id="campus1", site_id="acme")
    assert mapped["building_id"] == "BldgA"
    assert mapped["site_id"] == "acme"
