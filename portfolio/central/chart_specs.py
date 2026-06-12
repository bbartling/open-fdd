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
        "supports_fault_overlay": True,
        "supports_preview": True,
        "supports_docx": True,
    },
    {
        "chart_id": "vav_zone_temp",
        "title": "Zone temperature vs setpoints",
        "equipment_type": "VAV",
        "required_roles": ["zone_temperature", "zone_cooling_setpoint"],
        "supports_fault_overlay": True,
        "supports_preview": True,
        "supports_docx": True,
    },
    {
        "chart_id": "model_health_summary",
        "title": "BACnet / model health summary",
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
    {"id": "fault_analytics", "label": "Fault analytics"},
    {"id": "ahu_analytics", "label": "AHU analytics"},
    {"id": "vav_analytics", "label": "VAV zone analytics"},
    {"id": "runtime_analytics", "label": "Runtime analytics"},
    {"id": "model_health", "label": "BACnet / model health"},
    {"id": "recommendations", "label": "Recommendations"},
    {"id": "appendix_faults", "label": "Appendix: raw fault table"},
]


def chart_readiness(
    spec: dict[str, Any],
    *,
    roles_present: set[str],
    has_fault_data: bool,
    has_trend_data: bool,
) -> tuple[bool, str]:
    cid = spec["chart_id"]
    if cid in ("fault_hours_by_severity", "fault_hours_by_equipment"):
        return (has_fault_data, "No active faults in selected window")
    if cid == "model_health_summary":
        return (True, "")
    needed = spec.get("required_roles") or []
    if needed:
        missing = [r for r in needed if r not in roles_present]
        if missing:
            return (False, f"Missing {', '.join(missing)}")
        if not has_trend_data:
            return (False, "No trend samples in selected window")
    return (True, "")
