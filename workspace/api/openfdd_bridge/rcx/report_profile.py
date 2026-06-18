"""Model-driven RCx report profiles — sections, charts, and AI emphasis from BRICK topology."""

from __future__ import annotations

from typing import Any

from ..equipment_classify import is_ahu, is_chiller, is_hws, is_vav, report_family
from .chart_specs import SECTION_SPECS, suggest_charts_for_faults

# Profile ids are stable API surface for agents (MCP, intent, docs).
PROFILE_ZONE_MONITORING = "zone_monitoring"
PROFILE_AHU_STANDALONE = "ahu_standalone"
PROFILE_AHU_VAV = "ahu_vav"
PROFILE_AHU_VAV_PLANT = "ahu_vav_plant"
PROFILE_FULL_CENTRAL = "ahu_vav_full"

_ALL_SECTION_IDS = [s["id"] for s in SECTION_SPECS]

_PROFILE_SECTIONS: dict[str, list[str]] = {
    PROFILE_ZONE_MONITORING: [
        "executive_summary",
        "mechanical_summary",
        "trend_charts",
        "analyst_insights",
        "model_health",
        "recommendations",
        "appendix_missing_roles",
    ],
    PROFILE_AHU_STANDALONE: [
        "executive_summary",
        "mechanical_summary",
        "trend_charts",
        "fault_analytics",
        "ahu_analytics",
        "analyst_insights",
        "runtime_analytics",
        "model_health",
        "fdd_rule_trends",
        "recommendations",
        "appendix_faults",
        "appendix_missing_roles",
    ],
    PROFILE_AHU_VAV: [
        "executive_summary",
        "mechanical_summary",
        "trend_charts",
        "fault_analytics",
        "ahu_analytics",
        "vav_analytics",
        "analyst_insights",
        "runtime_analytics",
        "model_health",
        "fdd_rule_trends",
        "recommendations",
        "appendix_faults",
        "appendix_missing_roles",
    ],
    PROFILE_AHU_VAV_PLANT: [
        "executive_summary",
        "mechanical_summary",
        "trend_charts",
        "fault_analytics",
        "ahu_analytics",
        "vav_analytics",
        "analyst_insights",
        "runtime_analytics",
        "model_health",
        "fdd_rule_trends",
        "recommendations",
        "appendix_faults",
        "appendix_missing_roles",
    ],
    PROFILE_FULL_CENTRAL: list(_ALL_SECTION_IDS),
}

_PROFILE_LABELS: dict[str, str] = {
    PROFILE_ZONE_MONITORING: "Zone temperature monitoring",
    PROFILE_AHU_STANDALONE: "AHU / RTU performance",
    PROFILE_AHU_VAV: "AHU with VAV terminals",
    PROFILE_AHU_VAV_PLANT: "AHU, VAV, and central plant",
    PROFILE_FULL_CENTRAL: "Full central HVAC (ASHRAE G36 depth)",
}

_PROFILE_EMPHASIS: dict[str, list[str]] = {
    PROFILE_ZONE_MONITORING: [
        "zone_comfort",
        "sensor_health",
        "outdoor_air_context",
        "poll_reliability",
    ],
    PROFILE_AHU_STANDALONE: [
        "duct_static",
        "supply_air_temp",
        "economizer",
        "fan_runtime",
        "ashrae_g36_faults",
    ],
    PROFILE_AHU_VAV: [
        "ahu_performance",
        "vav_comfort",
        "simultaneous_heat_cool",
        "fan_runtime",
        "ashrae_g36_faults",
    ],
    PROFILE_AHU_VAV_PLANT: [
        "ahu_performance",
        "vav_comfort",
        "plant_reset",
        "boiler_chiller_efficiency",
        "ashrae_g36_faults",
    ],
    PROFILE_FULL_CENTRAL: [
        "ahu_performance",
        "vav_comfort",
        "plant_reset",
        "ashrae_g36_faults",
        "bacnet_override_hygiene",
        "fdd_rule_coverage",
    ],
}


def _family_counts(
    equipment: list[dict[str, Any]],
    report_bundles: dict[str, Any] | None,
) -> dict[str, int]:
    counts = {"ahu": 0, "vav": 0, "zone": 0, "hws": 0, "chiller": 0, "oat_weather": 0, "other": 0}
    if report_bundles:
        fam = report_bundles.get("families") if isinstance(report_bundles.get("families"), dict) else {}
        for key in ("ahu", "vav", "zone", "hws", "chiller", "oat_weather"):
            row = fam.get(key) if isinstance(fam.get(key), dict) else {}
            counts[key] = int(row.get("count") or 0)
        if any(counts.values()):
            return counts

    for eq in equipment:
        if not isinstance(eq, dict):
            continue
        fam = report_family(eq)
        if fam in counts:
            counts[fam] += 1
        else:
            counts["other"] += 1
    return counts


def _mech_counts(mechanical_summary: dict[str, Any] | None) -> dict[str, int]:
    mech = mechanical_summary if isinstance(mechanical_summary, dict) else {}
    raw = mech.get("counts") if isinstance(mech.get("counts"), dict) else {}
    out: dict[str, int] = {}
    for key in ("ahu", "ahus", "vav", "vavs", "zone", "zones", "hws", "chiller"):
        if key in raw:
            out[key] = int(raw[key] or 0)
    if not out:
        ahus = mech.get("ahus") if isinstance(mech.get("ahus"), list) else []
        vavs = mech.get("vavs") if isinstance(mech.get("vavs"), list) else []
        rtus = mech.get("rtus") if isinstance(mech.get("rtus"), list) else []
        out["ahus"] = len(ahus) + len(rtus)
        out["vavs"] = len(vavs)
    return out


def _zone_sensor_points(points: list[dict[str, Any]]) -> int:
    n = 0
    for pt in points:
        if not isinstance(pt, dict):
            continue
        bt = str(pt.get("brick_type") or pt.get("brick_class") or "").lower()
        ext = str(pt.get("external_id") or pt.get("fdd_input") or "").lower()
        if "zone_air_temperature" in bt or "space_temperature" in bt or "zn-t" in ext or "stat_zn" in ext:
            n += 1
    return n


def _ahu_sensor_points(points: list[dict[str, Any]]) -> int:
    n = 0
    for pt in points:
        if not isinstance(pt, dict):
            continue
        bt = str(pt.get("brick_type") or "").lower()
        if any(
            tok in bt
            for tok in (
                "supply_air",
                "mixed_air",
                "return_air",
                "duct_static",
                "outside_air_temperature",
            )
        ):
            n += 1
    return n


def select_report_profile(
    *,
    mechanical_summary: dict[str, Any] | None = None,
    report_bundles: dict[str, Any] | None = None,
    equipment: list[dict[str, Any]] | None = None,
    points: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Infer RCx profile from BRICK equipment topology — no site-specific hardcoding."""
    eq_rows = equipment if isinstance(equipment, list) else []
    pt_rows = points if isinstance(points, list) else []
    fam = _family_counts(eq_rows, report_bundles)
    mech = _mech_counts(mechanical_summary)

    ahu_n = max(fam["ahu"], int(mech.get("ahus") or mech.get("ahu") or 0))
    vav_n = max(fam["vav"], int(mech.get("vavs") or mech.get("vav") or 0))
    zone_n = max(fam["zone"], int(mech.get("zones") or mech.get("zone") or 0))
    hws_n = fam["hws"]
    chiller_n = fam["chiller"]
    zone_pts = _zone_sensor_points(pt_rows)
    ahu_pts = _ahu_sensor_points(pt_rows)

    rationale: list[str] = []
    if ahu_n:
        rationale.append(f"{ahu_n} air-handling unit(s) in model")
    if vav_n:
        rationale.append(f"{vav_n} VAV terminal(s)")
    if zone_n:
        rationale.append(f"{zone_n} zone-level equipment bundle(s)")
    if hws_n:
        rationale.append(f"{hws_n} hot-water plant equipment")
    if chiller_n:
        rationale.append(f"{chiller_n} chiller plant equipment")
    if zone_pts and not ahu_pts:
        rationale.append(f"{zone_pts} zone/space temperature point(s), no AHU supply-air sensors")

    profile_id = PROFILE_ZONE_MONITORING
    if ahu_n and vav_n and (hws_n or chiller_n):
        profile_id = PROFILE_FULL_CENTRAL
    elif ahu_n and vav_n:
        profile_id = PROFILE_AHU_VAV
        if hws_n or chiller_n:
            profile_id = PROFILE_AHU_VAV_PLANT
    elif ahu_n:
        profile_id = PROFILE_AHU_STANDALONE
    elif vav_n and not ahu_n:
        profile_id = PROFILE_AHU_VAV
        rationale.append("VAV terminals without modeled AHU — VAV-centric report")
    elif zone_pts and not ahu_n and not vav_n:
        profile_id = PROFILE_ZONE_MONITORING
        rationale.append("Zone/outdoor sensor focus — lightweight comfort report")

    sections = list(_PROFILE_SECTIONS.get(profile_id, _PROFILE_SECTIONS[PROFILE_ZONE_MONITORING]))
    emphasis = list(_PROFILE_EMPHASIS.get(profile_id, []))

    return {
        "profile_id": profile_id,
        "profile_label": _PROFILE_LABELS.get(profile_id, profile_id),
        "sections": sections,
        "emphasis": emphasis,
        "rationale": rationale,
        "topology": {
            "ahu_count": ahu_n,
            "vav_count": vav_n,
            "zone_equipment_count": zone_n,
            "hws_count": hws_n,
            "chiller_count": chiller_n,
            "zone_temp_points": zone_pts,
            "ahu_sensor_points": ahu_pts,
        },
    }


def plan_report_from_model(
    *,
    mechanical_summary: dict[str, Any] | None,
    report_bundles: dict[str, Any] | None,
    equipment: list[dict[str, Any]] | None,
    points: list[dict[str, Any]] | None,
    fault_rows: list[dict[str, Any]] | None,
    available_chart_ids: set[str] | None = None,
    custom_columns: list[str] | None = None,
    include_analytics: bool = True,
) -> dict[str, Any]:
    """Sections + default charts for agents from model profile."""
    profile = select_report_profile(
        mechanical_summary=mechanical_summary,
        report_bundles=report_bundles,
        equipment=equipment,
        points=points,
    )
    sections = list(profile["sections"])
    if not include_analytics:
        sections = [s for s in sections if s not in {"fault_analytics", "appendix_faults"}]

    charts: list[str] = []
    if custom_columns:
        charts.extend(f"custom_{col}" for col in custom_columns)

    bundles = (report_bundles or {}).get("bundles") if isinstance(report_bundles, dict) else []
    if isinstance(bundles, list):
        default_ids = (report_bundles or {}).get("default_bundle_ids") or []
        from .report_bundles import chart_ids_for_bundles

        for cid in chart_ids_for_bundles(bundles, list(default_ids)):
            if cid not in charts:
                charts.append(cid)

    avail = available_chart_ids or set()
    if fault_rows and avail:
        for cid in suggest_charts_for_faults(fault_rows, available_ids=avail):
            if cid not in charts:
                charts.append(cid)

    pid = profile["profile_id"]
    if pid == PROFILE_ZONE_MONITORING and not charts:
        for pref in ("vav_zone_temp", "building_inventory"):
            if pref in avail and pref not in charts:
                charts.append(pref)

    return {
        **profile,
        "sections": sections,
        "charts": charts[:24],
        "report_type": f"rcx_{pid}",
    }
