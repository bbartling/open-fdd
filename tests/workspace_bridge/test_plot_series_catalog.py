from __future__ import annotations

import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[2] / "workspace" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from openfdd_bridge.timeseries_api import (  # noqa: E402
    build_plot_series_catalog,
    plot_column_name,
    resolve_plot_columns,
)


def test_plot_column_name_from_point_id():
    pt = {"id": "12035-analog-input-1", "external_id": "", "fdd_input": ""}
    assert plot_column_name(pt) == "analog-input-1"


def test_build_plot_series_catalog_groups_by_equipment():
    model = {
        "equipment": [
            {"id": "eq-a", "site_id": "s1", "name": "VAV 1", "bacnet_device_instance": 101},
            {"id": "eq-b", "site_id": "s1", "name": "VAV 2", "bacnet_device_instance": 102},
        ],
        "points": [
            {
                "id": "p1",
                "equipment_id": "eq-a",
                "external_id": "oa-t",
                "name": "Zone temp",
            },
            {
                "id": "p2",
                "equipment_id": "eq-b",
                "external_id": "oa-t",
                "name": "Other zone temp",
            },
            {"id": "p3", "equipment_id": "eq-a", "external_id": "oa-h", "name": "RH"},
        ],
    }
    columns = ["oa-t", "oa-h"]
    labels = {"oa-t": "Temp", "oa-h": "Humidity"}
    options, groups, unassigned = build_plot_series_catalog("s1", columns, model, labels)
    assert len(options) == 3
    assert len(groups) == 2
    assert groups[0]["bacnet_device_instance"] == 101
    assert "p1" in groups[0]["keys"]
    assert "p3" in groups[0]["keys"]
    assert unassigned == []


def test_resolve_plot_columns_maps_point_ids():
    model = {
        "equipment": [{"id": "eq-a", "site_id": "s1", "name": "Bench"}],
        "points": [
            {"id": "p-zone", "site_id": "s1", "equipment_id": "eq-a", "external_id": "oa-t"},
        ],
    }
    assert resolve_plot_columns(["p-zone"], model, "s1") == ["oa-t"]
    assert resolve_plot_columns(["oa-t"], model, "s1") == ["oa-t"]
