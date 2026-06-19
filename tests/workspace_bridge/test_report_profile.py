"""Model-driven RCx report profile selection (bench vs central plant)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def _bench_model() -> tuple[list, list]:
    model = json.loads((REPO / "workspace" / "data" / "bench_dual_source_model.json").read_text(encoding="utf-8"))
    return model.get("equipment") or [], model.get("points") or []


def _acme_like_model() -> tuple[list, list]:
    """Minimal Acme topology: 1 AHU, many VAVs, hot-water plant — no site hardcoding."""
    equipment = [
        {"id": "rtu-01", "brick_type": "AHU", "name": "Rtu 01"},
        {"id": "hw-plant", "brick_type": "Hot_Water_Plant", "name": "Hw Plant"},
    ]
    equipment.extend(
        {"id": f"vav-{i}", "brick_type": "VAV", "name": f"VAV {i}"}
        for i in range(1, 31)
    )
    points = [
        {
            "id": "ahu-sat",
            "equipment_id": "rtu-01",
            "brick_type": "Supply_Air_Temperature_Sensor",
            "external_id": "supply_air_temperature_local",
        },
        {
            "id": "ahu-dsp",
            "equipment_id": "rtu-01",
            "brick_type": "Supply_Air_Static_Pressure_Sensor",
            "external_id": "duct_static_pressure_local",
        },
        {
            "id": "ahu-mat",
            "equipment_id": "rtu-01",
            "brick_type": "Mixed_Air_Temperature_Sensor",
            "external_id": "mixed_air_temperature_local",
        },
        {
            "id": "hws-t",
            "equipment_id": "hw-plant",
            "brick_type": "Point",
            "external_id": "hot_water_supply_temperature",
        },
    ]
    points.extend(
        {
            "id": f"vav-{i}-zn",
            "equipment_id": f"vav-{i}",
            "brick_type": "Zone_Air_Temperature_Sensor",
            "external_id": "zn-t",
        }
        for i in range(1, 31)
    )
    return equipment, points


def test_select_profile_bench_zone_monitoring():
    from openfdd_bridge.rcx.report_profile import (
        PROFILE_ZONE_MONITORING,
        select_report_profile,
    )

    eq, pts = _bench_model()
    profile = select_report_profile(equipment=eq, points=pts)
    assert profile["profile_id"] == PROFILE_ZONE_MONITORING
    assert "zone" in profile["profile_label"].lower() or "Zone" in profile["profile_label"]
    topo = profile.get("topology") or {}
    assert int(topo.get("zone_temp_points") or 0) >= 1
    assert int(topo.get("ahu_count") or 0) == 0
    assert "trend_charts" in profile.get("sections", [])
    assert "analyst_insights" in profile.get("sections", [])
    assert "fault_analytics" not in profile.get("sections", [])


def test_select_profile_acme_full_central():
    from openfdd_bridge.rcx.report_profile import (
        PROFILE_FULL_CENTRAL,
        select_report_profile,
    )

    eq, pts = _acme_like_model()
    profile = select_report_profile(equipment=eq, points=pts)
    assert profile["profile_id"] == PROFILE_FULL_CENTRAL
    topo = profile.get("topology") or {}
    assert topo.get("ahu_count") == 1
    assert topo.get("vav_count") == 30
    assert topo.get("hws_count") == 1
    assert "ashrae_g36_faults" in (profile.get("emphasis") or [])
    sections = profile.get("sections") or []
    assert "ahu_analytics" in sections
    assert "vav_analytics" in sections
    assert "fdd_rule_trends" in sections


def test_plan_report_from_model_includes_report_type():
    from openfdd_bridge.rcx.report_profile import plan_report_from_model

    eq, pts = _bench_model()
    plan = plan_report_from_model(
        mechanical_summary={"counts": {"zones": 2}},
        report_bundles=None,
        equipment=eq,
        points=pts,
        fault_rows=[],
        available_chart_ids={"vav_zone_temp", "building_inventory"},
        custom_columns=["oa-t"],
    )
    assert plan.get("report_type") == "rcx_zone_monitoring"
    assert "custom_oa-t" in (plan.get("charts") or [])
    assert plan.get("profile_id") == "zone_monitoring"


def test_fallback_insights_zone_profile():
    from openfdd_bridge.rcx.rcx_ai_insights import build_fallback_insights

    out = build_fallback_insights(
        site_name="Bench Lab",
        window={"hours": 168},
        fault_rows=[],
        overview={"active_faults": 0},
        chart_previews=[],
        report_context={"assigned_rules": [], "motor_runtime": [], "overrides": {"override_count": 0, "overrides": []}},
        mechanical_summary={"counts": {"zones": 2}},
        report_profile={
            "profile_id": "zone_monitoring",
            "profile_label": "Zone temperature monitoring",
            "topology": {"zone_temp_points": 3},
        },
    )
    joined = " ".join(out.get("paragraphs") or [])
    assert out.get("profile_id") == "zone_monitoring"
    assert "zone" in joined.lower()
    assert "duct-static" not in joined.lower() or "rather than duct-static" in joined.lower()
