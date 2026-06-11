"""Read-only ACME VAV/AHU model and fault-result audits (offline + live API)."""

from __future__ import annotations

from collections import Counter
from typing import Any

from .bacnet_poll_model_sync import duplicate_bacnet_equipment_report, duplicate_point_id_report

# Normalized point roles for ACME VAV/AHU validation (keyword match on brick_type/name/description).
AHU_POINT_ROLES: dict[str, tuple[str, ...]] = {
    "supply_air_temperature": ("supply_air_temperature", "sat", "supply air temp"),
    "supply_air_temperature_setpoint": ("supply_air_temperature_setpoint", "sat_sp", "sat setpoint"),
    "return_air_temperature": ("return_air_temperature", "rat", "return air"),
    "mixed_air_temperature": ("mixed_air_temperature", "mat", "mixed air"),
    "outdoor_air_temperature": ("outdoor_air_temperature", "oat", "outside air", "oa-t"),
    "supply_fan_command": ("supply_fan_command", "fan_cmd", "fan command"),
    "supply_fan_status": ("supply_fan_status", "fan_status", "fan stat"),
    "duct_static_pressure": ("duct_static_pressure", "static", "sap"),
    "duct_static_pressure_setpoint": ("duct_static_pressure_setpoint", "static_sp"),
}

VAV_POINT_ROLES: dict[str, tuple[str, ...]] = {
    "zone_temperature": ("zone_temperature", "zone_temp", "zn-t", "space_temperature"),
    "zone_cooling_setpoint": ("zone_cooling_setpoint", "cooling_sp", "zn-cool"),
    "zone_heating_setpoint": ("zone_heating_setpoint", "heating_sp", "zn-heat"),
    "damper_position": ("damper", "damper_position", "damper command"),
    "airflow": ("airflow", "sa_flow", "supply_air_flow"),
    "reheat_command": ("reheat", "reheat_command", "reheat valve"),
    "discharge_air_temperature": ("discharge_air", "dat", "discharge air"),
}


def _norm(text: str) -> str:
    return str(text or "").strip().lower().replace(" ", "_").replace("-", "_")


def _point_text(pt: dict[str, Any]) -> str:
    parts = [
        pt.get("brick_type"),
        pt.get("description"),
        pt.get("name"),
        pt.get("external_id"),
        pt.get("fdd_input"),
    ]
    return _norm(" ".join(str(p) for p in parts if p))


def _equipment_type(eq: dict[str, Any]) -> str:
    return _norm(str(eq.get("equipment_type") or eq.get("brick_type") or eq.get("name") or ""))


def duplicate_audit(model: dict[str, Any]) -> dict[str, Any]:
    """Aggregate duplicate BACnet device, equipment, and point-id reports."""
    bacnet = duplicate_bacnet_equipment_report(model)
    points = duplicate_point_id_report(model)
    equipment = model.get("equipment") or []
    dev_inst: Counter[str] = Counter()
    for eq in equipment:
        if not isinstance(eq, dict):
            continue
        inst = eq.get("bacnet_device_instance") or eq.get("bacnet_device_id")
        if inst is not None:
            dev_inst[str(inst)] += 1
    dup_inst = {k: v for k, v in dev_inst.items() if v > 1}
    eq_ids = [str(e.get("id")) for e in equipment if isinstance(e, dict) and e.get("id")]
    dup_eq_id = {k: v for k, v in Counter(eq_ids).items() if v > 1}
    return {
        "duplicate_bacnet_device_instances": int(bacnet.get("duplicate_device_instances") or 0),
        "duplicate_bacnet_equipment_ids": bacnet.get("duplicate_equipment_ids") or [],
        "duplicate_point_ids": int(points.get("duplicate_point_ids") or 0),
        "duplicate_point_id_samples": points.get("instances") or {},
        "duplicate_equipment_id_strings": dup_eq_id,
        "duplicate_device_instance_counts": dup_inst,
        "ok": (
            int(bacnet.get("duplicate_device_instances") or 0) == 0
            and int(points.get("duplicate_point_ids") or 0) == 0
            and not dup_eq_id
        ),
    }


def _roles_present(points: list[dict[str, Any]], role_map: dict[str, tuple[str, ...]]) -> dict[str, bool]:
    found = {role: False for role in role_map}
    for pt in points:
        text = _point_text(pt)
        for role, keywords in role_map.items():
            if any(kw in text for kw in keywords):
                found[role] = True
    return found


def equipment_point_role_audit(model: dict[str, Any], *, site_id: str = "acme") -> dict[str, Any]:
    """Report AHU/VAV point role coverage and equipment assignment sanity."""
    equipment = [e for e in model.get("equipment") or [] if isinstance(e, dict)]
    points = [p for p in model.get("points") or [] if isinstance(p, dict)]
    ahurs = [e for e in equipment if "ahu" in _equipment_type(e) or "rtu" in _equipment_type(e)]
    vavs = [e for e in equipment if "vav" in _equipment_type(e)]
    ahu_reports: list[dict[str, Any]] = []
    for eq in ahurs[:20]:
        eid = str(eq.get("id") or "")
        eq_pts = [p for p in points if str(p.get("equipment_id") or "") == eid]
        roles = _roles_present(eq_pts, AHU_POINT_ROLES)
        missing = [r for r, ok in roles.items() if not ok]
        ahu_reports.append(
            {
                "equipment_id": eid,
                "name": eq.get("name"),
                "point_count": len(eq_pts),
                "roles_found": [r for r, ok in roles.items() if ok],
                "roles_missing": missing,
            }
        )
    vav_reports: list[dict[str, Any]] = []
    for eq in vavs[:30]:
        eid = str(eq.get("id") or "")
        eq_pts = [p for p in points if str(p.get("equipment_id") or "") == eid]
        roles = _roles_present(eq_pts, VAV_POINT_ROLES)
        missing = [r for r, ok in roles.items() if not ok]
        vav_reports.append(
            {
                "equipment_id": eid,
                "name": eq.get("name"),
                "point_count": len(eq_pts),
                "roles_found": [r for r, ok in roles.items() if ok],
                "roles_missing": missing,
            }
        )
    orphan_pts = [
        str(p.get("id"))
        for p in points
        if not str(p.get("equipment_id") or "").strip()
    ]
    return {
        "ahu_count": len(ahurs),
        "vav_count": len(vavs),
        "ahu_reports": ahu_reports,
        "vav_reports": vav_reports,
        "orphan_point_count": len(orphan_pts),
        "orphan_point_samples": orphan_pts[:10],
    }


def validate_fault_alert_schema(alert: dict[str, Any]) -> list[str]:
    """Return list of schema violations for a Building Status FDD alert."""
    errors: list[str] = []
    if alert.get("source") != "fdd":
        return errors
    for key in ("code", "title", "severity"):
        if not str(alert.get(key) or "").strip():
            errors.append(f"missing {key}")
    ctx = alert.get("model_context") or {}
    eq = ctx.get("equipment") if isinstance(ctx.get("equipment"), dict) else {}
    eq_name = (
        str(ctx.get("equipment_name") or alert.get("equipment_name") or eq.get("name") or "").strip()
    )
    if not eq_name:
        errors.append("missing equipment context")
    rule_id = str(ctx.get("rule_id") or alert.get("rule_id") or "")
    if not rule_id and "flatline" not in str(alert.get("title") or "").lower():
        errors.append("missing rule_id in context")
    return errors


def validate_fdd_run_schema(run: dict[str, Any]) -> list[str]:
    """Validate persisted FDD batch run row has operator-facing fields."""
    errors: list[str] = []
    for key in ("rule_id", "rule_name", "site_id"):
        if not str(run.get(key) or "").strip():
            errors.append(f"run missing {key}")
    if run.get("flagged") is None and run.get("fault_rows") is None:
        errors.append("run missing flagged/fault_rows count")
    return errors
