"""Dashboard analytics aggregation for operator UI and RCx reports (read-only)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from open_fdd.reports.fault_hours import (
    aggregate_fault_hours,
    fault_hours_from_alerts,
    fault_hours_from_fdd_runs,
)

CHART_CATALOG = [
    {"id": "fault_hours_by_severity", "label": "Fault hours by severity", "roles": []},
    {"id": "fault_hours_by_equipment", "label": "Fault hours by equipment", "roles": []},
    {"id": "fault_hours_by_code", "label": "Fault hours by fault code", "roles": []},
    {"id": "active_faults_table", "label": "Active faults table", "roles": []},
    {
        "id": "ahu_sat_vs_setpoint",
        "label": "AHU supply air temperature vs setpoint",
        "roles": ["supply_air_temperature", "supply_air_temperature_setpoint"],
    },
    {
        "id": "ahu_duct_static_vs_setpoint",
        "label": "AHU duct static pressure vs setpoint",
        "roles": ["duct_static_pressure", "duct_static_pressure_setpoint"],
    },
    {
        "id": "ahu_fan_runtime",
        "label": "AHU fan status / speed / runtime",
        "roles": ["supply_fan_status", "supply_fan_speed"],
    },
    {
        "id": "vav_zone_temp",
        "label": "VAV zone temperature vs setpoints",
        "roles": ["zone_temperature", "zone_heating_setpoint", "zone_cooling_setpoint"],
    },
    {
        "id": "vav_airflow",
        "label": "VAV airflow vs setpoint",
        "roles": ["airflow", "airflow_setpoint"],
    },
    {"id": "model_health_summary", "label": "BACnet / model health summary", "roles": []},
]

SECTION_CATALOG = [
    {"id": "executive_summary", "label": "Executive summary"},
    {"id": "fault_analytics", "label": "Fault analytics"},
    {"id": "ahu_analytics", "label": "AHU analytics"},
    {"id": "vav_analytics", "label": "VAV zone analytics"},
    {"id": "runtime_analytics", "label": "Runtime analytics"},
    {"id": "model_health", "label": "BACnet / model health"},
    {"id": "recommendations", "label": "Recommendations"},
    {"id": "appendix_faults", "label": "Appendix: raw fault table"},
    {"id": "appendix_missing_roles", "label": "Appendix: missing point roles"},
]


def _parse_window(hours: int | None) -> tuple[str | None, str | None]:
    if not hours or hours <= 0:
        return None, None
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=hours)
    return start.isoformat(), end.isoformat()


def _site_name(site_id: str) -> str:
    try:
        from .model_service import ModelService

        model = ModelService().load()
        meta = model.get("meta") if isinstance(model.get("meta"), dict) else {}
        name = str(meta.get("site_name") or meta.get("name") or "").strip()
        if name:
            return name
    except Exception:
        pass
    return site_id or "Edge instance"


def _load_fdd_runs() -> list[dict[str, Any]]:
    try:
        from .fdd_results import load_results

        doc = load_results()
        return [r for r in doc.get("runs", []) if isinstance(r, dict)]
    except Exception:
        return []


def _collect_status() -> dict[str, Any]:
    from .building_status import collect_status

    return collect_status()


def _model_health_counts(health: dict[str, Any]) -> dict[str, Any]:
    counts = health.get("counts") if isinstance(health.get("counts"), dict) else {}
    return {
        "device_count": counts.get("devices"),
        "point_count": counts.get("points"),
        "equipment_count": counts.get("equipment"),
        "stale_point_count": health.get("stale_point_count"),
        "issue_count": len(health.get("issues") or []),
    }


def build_overview(*, site_id: str | None = None) -> dict[str, Any]:
    status = _collect_status()
    alerts = [a for a in status.get("alerts", []) if isinstance(a, dict)]
    fdd_alerts = [a for a in alerts if str(a.get("source")) == "fdd"]
    fault_rows = fault_hours_from_alerts(fdd_alerts)
    if not fault_rows:
        fault_rows = fault_hours_from_fdd_runs(_load_fdd_runs())

    total_hours = round(sum(float(r.get("elapsed_hours") or 0) for r in fault_rows), 2)
    critical = sum(1 for r in fault_rows if str(r.get("severity")) == "critical")
    high = sum(1 for r in fault_rows if str(r.get("severity")) in ("critical", "warning"))

    mh = status.get("model_health") if isinstance(status.get("model_health"), dict) else {}
    poll_stale = sum(
        1 for a in alerts if str(a.get("source")) == "poll_health" and a.get("severity") != "info"
    )

    return {
        "site_id": site_id or "",
        "site_name": _site_name(site_id or ""),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "kpis": {
            "active_faults": len(fault_rows),
            "critical_high_faults": critical + high,
            "total_fault_hours": total_hours,
            "online_edge_instances": 1,
            "bacnet_stale_points": poll_stale,
            "model_warnings": len(mh.get("issues") or []),
            "equipment_with_faults": len({r.get("equipment") for r in fault_rows}),
            "validation_status": status.get("status"),
        },
        "faults_by_severity": aggregate_fault_hours(fault_rows, group_by="severity"),
        "fault_hours_by_equipment": aggregate_fault_hours(fault_rows, group_by="equipment")[:15],
        "fault_hours_by_code": aggregate_fault_hours(fault_rows, group_by="fault_code")[:15],
        "top_faults": _top_faults_table(fault_rows),
        "traffic": status.get("traffic"),
        "model_health": _model_health_counts(mh),
    }


def _top_faults_table(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda r: -(float(r.get("elapsed_hours") or 0)))[:25]:
        out.append(
            {
                "equipment": row.get("equipment"),
                "equipment_type": row.get("equipment_type"),
                "fault_name": row.get("fault_name") or row.get("fault_code"),
                "severity": row.get("severity"),
                "elapsed_fault_hours": row.get("elapsed_hours"),
                "samples_flagged": row.get("samples_flagged"),
                "samples_evaluated": row.get("samples_evaluated"),
                "last_seen": row.get("last_seen"),
                "recommended_next_step": _next_step(row),
            }
        )
    return out


def _next_step(row: dict[str, Any]) -> str:
    name = str(row.get("fault_name") or "").lower()
    if "flatline" in name:
        return "Verify sensor and historian feed"
    if "static" in name or "pressure" in name:
        return "Review duct static reset and setpoint tracking"
    if "comfort" in name or "zone" in name:
        return "Inspect VAV damper/reheat at zone"
    return "Review rule thresholds and point mapping"


def build_fault_analytics(
    *,
    hours: int = 24,
    severity: str | None = None,
    equipment_type: str | None = None,
) -> dict[str, Any]:
    overview = build_overview()
    rows = fault_hours_from_fdd_runs(_load_fdd_runs())
    if not rows:
        status = _collect_status()
        rows = fault_hours_from_alerts(
            [a for a in status.get("alerts", []) if str(a.get("source")) == "fdd"]
        )
    if severity:
        rows = [r for r in rows if str(r.get("severity")) == severity]
    if equipment_type:
        et = equipment_type.upper()
        rows = [r for r in rows if et in str(r.get("equipment_type") or "").upper()]

    start, end = _parse_window(hours)
    return {
        "window": {"start": start, "end": end, "hours": hours},
        "fault_count_by_severity": aggregate_fault_hours(rows, group_by="severity"),
        "fault_hours_by_severity": aggregate_fault_hours(rows, group_by="severity"),
        "fault_hours_by_equipment": aggregate_fault_hours(rows, group_by="equipment")[:20],
        "fault_hours_by_code": aggregate_fault_hours(rows, group_by="fault_code")[:20],
        "top_equipment": aggregate_fault_hours(rows, group_by="equipment")[:10],
        "faults": rows,
    }


def build_model_health() -> dict[str, Any]:
    status = _collect_status()
    mh = status.get("model_health") if isinstance(status.get("model_health"), dict) else {}
    issues = mh.get("issues") or []
    return {
        "configured": mh.get("configured"),
        "counts": _model_health_counts(mh),
        "issues": issues[:50],
        "stack": status.get("stack"),
        "duplicate_warnings": [i for i in issues if "duplicate" in str(i.get("title", "")).lower()],
        "missing_roles": [
            str(i.get("title") or i.get("detail") or "")
            for i in issues
            if "fdd_input" in str(i.get("detail", "")).lower()
            or "role" in str(i.get("title", "")).lower()
        ],
    }


def _chart_readiness(scope: dict[str, Any]) -> tuple[list[dict], list[dict]]:
    available: list[dict] = []
    disabled: list[dict] = []
    fault_rows = scope.get("fault_rows") or []
    has_faults = bool(fault_rows)
    roles_present = set(scope.get("roles_present") or [])

    for chart in CHART_CATALOG:
        cid = chart["id"]
        needed = chart.get("roles") or []
        if cid in ("fault_hours_by_severity", "fault_hours_by_equipment", "fault_hours_by_code"):
            if has_faults:
                available.append(chart)
            else:
                disabled.append({**chart, "reason": "No active faults in selected window"})
        elif cid == "active_faults_table":
            if has_faults:
                available.append(chart)
            else:
                disabled.append({**chart, "reason": "No active faults"})
        elif cid == "model_health_summary":
            available.append(chart)
        elif needed:
            missing = [r for r in needed if r not in roles_present]
            if missing:
                disabled.append({**chart, "reason": f"Missing {', '.join(missing)}"})
            else:
                available.append(chart)
        else:
            available.append(chart)
    return available, disabled


def build_rcx_preview(
    *,
    site_id: str = "",
    hours: int = 24,
    scope: str = "building",
    equipment_ids: list[str] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    from .rcx.chart_preview import build_rcx_preview as _build

    return _build(
        site_id=site_id,
        hours=hours,
        scope=scope,
        equipment_ids=equipment_ids,
        **kwargs,
    )
