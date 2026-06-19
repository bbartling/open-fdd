"""RCx chart narrative templates."""

from __future__ import annotations


def test_ahu_duct_static_narrative_with_faults():
    from openfdd_bridge.rcx.rcx_narrative import build_chart_narrative

    text = build_chart_narrative(
        chart_id="ahu_duct_static_vs_setpoint",
        title="Duct static",
        stats={"fault_percent": 8.0, "fault_hours": 2.0, "total_hours": 24},
        fault_summary={"active_faults": 2},
    )
    assert "duct static" in text.lower()
    assert "8.0%" in text


def test_vav_zone_narrative_low_faults():
    from openfdd_bridge.rcx.rcx_narrative import build_chart_narrative

    text = build_chart_narrative(
        chart_id="vav_zone_temp",
        title="Zone temp",
        stats={"fault_percent": 0.5, "total_hours": 168},
        fault_summary={"active_faults": 0},
    )
    assert "zone" in text.lower()
    assert "sparse" in text.lower() or "reasonable" in text.lower()


def test_custom_chart_narrative():
    from openfdd_bridge.rcx.rcx_narrative import build_chart_narrative

    text = build_chart_narrative(
        chart_id="custom_oat_local",
        title="OAT",
        stats={"fault_percent": 0, "total_hours": 24},
        fault_summary={"active_faults": 0},
    )
    assert "Custom trend" in text
