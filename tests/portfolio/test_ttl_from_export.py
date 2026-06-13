"""TTL build from model export."""

from __future__ import annotations

from portfolio.central.ttl_from_export import build_ttl_from_model


def test_build_ttl_maps_ahu_and_vav():
    model = {
        "sites": [{"id": "acme", "name": "Acme"}],
        "equipment": [
            {
                "id": "acme-vm-bbartling-rtu-01",
                "name": "AHU 01",
                "site_id": "acme",
                "brick_type": "AHU",
                "equipment_type": "AHU",
            },
            {
                "id": "acme-vm-bbartling-jci-vav-10",
                "name": "Jci Vav 10",
                "site_id": "acme",
                "brick_type": "VAV",
            },
        ],
        "points": [],
    }
    ttl = build_ttl_from_model(model)
    assert "brick:Air_Handling_Unit" in ttl
    assert "brick:Variable_Air_Volume_Box" in ttl
    assert "brick:Equipment" not in ttl or ttl.count("brick:Equipment") == 0
