"""RCx chart catalog — required roles, fault overlay support."""

from __future__ import annotations

from typing import Any

CHART_SPECS: list[dict[str, Any]] = [
    {
        "chart_id": "fault_hours_by_severity",
        "title": "Fault hours by severity",
        "equipment_type": "building",
        "required_roles": [],
        "supports_fault_overlay": False,
        "supports_preview": True,
        "supports_docx": True,
    },
    {
        "chart_id": "fault_hours_by_equipment",
        "title": "Fault hours by equipment",
        "equipment_type": "building",
        "required_roles": [],
        "supports_fault_overlay": False,
        "supports_preview": True,
        "supports_docx": True,
    },
    {
        "chart_id": "ahu_sat_vs_setpoint",
        "title": "Supply air temperature vs setpoint",
        "equipment_type": "AHU",
        "required_roles": ["supply_air_temperature", "supply_air_temperature_setpoint"],
        "related_fault_codes": ["SAT", "flatline"],
        "supports_fault_overlay": True,
        "supports_preview": True,
        "supports_docx": True,
    },
    {
        "chart_id": "ahu_duct_static_vs_setpoint",
        "title": "Duct static pressure vs setpoint",
        "equipment_type": "AHU",
        "required_roles": ["duct_static_pressure", "duct_static_pressure_setpoint"],
        "related_fault_codes": ["AHU-A", "duct", "static"],
        "supports_fault_overlay": True,
        "supports_preview": True,
        "supports_docx": True,
    },
    {
        "chart_id": "vav_zone_temp",
        "title": "Zone temperature vs setpoints",
        "equipment_type": "VAV",
        "required_roles": ["zone_temperature", "zone_cooling_setpoint"],
        "related_fault_codes": ["VAV-C", "VAV-E", "zone", "comfort"],
        "supports_fault_overlay": True,
        "supports_preview": True,
        "supports_docx": True,
    },
    {
        "chart_id": "building_inventory",
        "title": "Building inventory & active faults",
        "equipment_type": "building",
        "required_roles": [],
        "supports_fault_overlay": False,
        "supports_preview": True,
        "supports_docx": True,
    },
]

SECTION_SPECS = [
    {"id": "executive_summary", "label": "Executive summary"},
    {"id": "mechanical_summary", "label": "Mechanical summary"},
    {"id": "trend_charts", "label": "Trend charts (selected)"},
    {"id": "fault_analytics", "label": "Fault analytics"},
    {"id": "ahu_analytics", "label": "AHU analytics"},
    {"id": "vav_analytics", "label": "VAV zone analytics"},
    {"id": "analyst_insights", "label": "Analyst insights (plain language)"},
    {"id": "runtime_analytics", "label": "Runtime analytics"},
    {"id": "model_health", "label": "BACnet / model health"},
    {"id": "recommendations", "label": "Recommendations"},
    {"id": "appendix_faults", "label": "Appendix: raw fault table"},
]

TREND_CHART_IDS = {
    "ahu_sat_vs_setpoint",
    "ahu_duct_static_vs_setpoint",
    "vav_zone_temp",
}

_FAULT_KEYWORDS: dict[str, list[str]] = {
    "ahu_sat_vs_setpoint": ["sat", "supply air", "flatline", "ahu-c", "rtu-c"],
    "ahu_duct_static_vs_setpoint": ["duct static", "dsp", "static pressure", "ahu-a"],
    "vav_zone_temp": ["zone temp", "vav-c", "vav-e", "comfort", "reheat"],
}


def chart_readiness(
    spec: dict[str, Any],
    *,
    roles_present: set[str],
    has_fault_data: bool,
    has_trend_data: bool,
    tree: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    cid = spec["chart_id"]
    if cid in ("fault_hours_by_severity", "fault_hours_by_equipment"):
        return (has_fault_data, "No active faults in selected window")
    if cid == "building_inventory":
        return (True, "")
    needed = spec.get("required_roles") or []
    if needed:
        if tree:
            from .trend_charts import resolve_roles_on_tree

            cols, missing = resolve_roles_on_tree(tree, needed)
            if not cols:
                return (False, f"Missing {', '.join(needed)}")
            if missing:
                return (True, f"Partial — missing {', '.join(missing)}")
            if not has_trend_data:
                return (False, "No trend samples in selected window")
            return (True, "")
        missing = [r for r in needed if r not in roles_present]
        if missing:
            return (False, f"Missing {', '.join(missing)}")
        if not has_trend_data:
            return (False, "No trend samples in selected window")
    return (True, "")


def suggest_charts_for_faults(
    fault_rows: list[dict[str, Any]],
    *,
    available_ids: set[str],
) -> list[str]:
    """Pick charts that match active faults; engineer can add more in the gallery."""
    suggested: list[str] = []
    if fault_rows:
        for cid in ("fault_hours_by_severity", "fault_hours_by_equipment"):
            if cid in available_ids:
                suggested.append(cid)

    haystack: list[str] = []
    for row in fault_rows:
        haystack.append(str(row.get("fault_code") or "").lower())
        haystack.append(str(row.get("fault_name") or "").lower())
        haystack.append(str(row.get("equipment") or "").lower())
    blob = " ".join(haystack)

    for spec in CHART_SPECS:
        cid = str(spec.get("chart_id") or "")
        if cid not in available_ids or cid in suggested:
            continue
        keys = [str(k).lower() for k in (spec.get("related_fault_codes") or [])]
        keys.extend(_FAULT_KEYWORDS.get(cid, []))
        if keys and any(k and k in blob for k in keys):
            suggested.append(cid)

    if not suggested:
        for cid in TREND_CHART_IDS:
            if cid in available_ids and cid not in suggested:
                suggested.append(cid)
    for cid in sorted(available_ids):
        if cid not in suggested:
            suggested.append(cid)
    return suggested
