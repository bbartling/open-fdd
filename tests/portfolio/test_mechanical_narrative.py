"""Tests for HVAC count supplement from equipment_to_points."""

from __future__ import annotations

from openfdd_bridge.rcx.mechanical_narrative import _count_hvac_row


def test_count_hvac_row_rtu_equipment_id():
    da, dv, dz = _count_hvac_row(
        {
            "equipment_id": "acme-vm-bbartling-rtu-01",
            "equipment_type": None,
            "name": "1100",
        }
    )
    assert da == 1
    assert dv == 0
    assert dz == 0


def test_count_hvac_row_vav_name():
    da, dv, dz = _count_hvac_row(
        {
            "equipment_id": "acme-vm-bbartling-trane-vav-12035",
            "equipment_type": None,
            "name": "Trane Vav 12035",
        }
    )
    assert da == 0
    assert dv == 1
    assert dz == 0
