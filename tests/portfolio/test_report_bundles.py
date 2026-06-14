"""Tests for data-model report bundles."""

from __future__ import annotations

from openfdd_bridge.rcx.report_bundles import build_report_bundles, chart_ids_for_bundles


def _rows_for(eid: str, points: list[tuple[str, str]]) -> list[dict]:
    return [
        {
            "equipment_id": eid,
            "point_id": f"p{i}",
            "brick_class": brick,
            "external_id": ext,
            "equipment_type": "",
        }
        for i, (brick, ext) in enumerate(points)
    ]


def test_build_ahu_and_vav_bundles():
    rows = _rows_for(
        "acme-vm-bbartling-rtu-01",
        [
            ("Supply_Air_Temperature_Sensor", "supply_air_temperature_local"),
            ("Discharge_Air_Temperature_Setpoint", "discharge_air_temperature_setpoint_active"),
            ("Supply_Air_Static_Pressure_Sensor", "duct_static_pressure_local"),
            ("Supply_Air_Static_Pressure_Setpoint", "duct_static_pressure_setpoint_active"),
        ],
    )
    rows += _rows_for(
        "acme-vm-bbartling-jci-vav-39",
        [
            ("Zone_Air_Temperature_Sensor", "space_temperature_local"),
            ("Cooling_Temperature_Setpoint", "active_cool_setpoint"),
        ],
    )
    meta = {
        "acme-vm-bbartling-rtu-01": {"id": "acme-vm-bbartling-rtu-01", "name": "AHU 01"},
        "acme-vm-bbartling-jci-vav-39": {"id": "acme-vm-bbartling-jci-vav-39", "name": "Jci Vav 39"},
    }
    out = build_report_bundles(equipment_rows=rows, equipment_meta=meta, fault_rows=[])
    bundles = out["bundles"]
    families = out["families"]
    assert families["ahu"]["count"] == 1
    assert families["vav"]["count"] == 1
    assert out["default_bundle_ids"] == ["building", "ahu:acme-vm-bbartling-rtu-01"]
    ahu = next(b for b in bundles if b["family"] == "ahu")
    assert ahu["chart_count"] >= 2
    ids = chart_ids_for_bundles(bundles, ["building", "ahu:acme-vm-bbartling-rtu-01"])
    assert "building_inventory" in ids
    assert any(cid.startswith("eq:acme-vm-bbartling-rtu-01:") for cid in ids)
