"""Resolve BRICK/BACnet context for FDD fault alerts shown on Building Status."""

from __future__ import annotations

from typing import Any

from .fdd_equipment import column_to_equipment_map, equipment_labels_for_columns
from .timeseries_api import historian_column_candidates, plot_column_name


def _equipment_index(model: dict[str, Any], site_id: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for eq in model.get("equipment") or []:
        if not isinstance(eq, dict):
            continue
        if str(eq.get("site_id") or "") not in {"", site_id}:
            continue
        eid = str(eq.get("id") or "").strip()
        if eid:
            out[eid] = eq
    return out


def _column_to_point(model: dict[str, Any], site_id: str) -> dict[str, dict[str, Any]]:
    mapping: dict[str, dict[str, Any]] = {}
    for pt in model.get("points") or []:
        if not isinstance(pt, dict) or str(pt.get("site_id") or "") not in {"", site_id}:
            continue
        for col in historian_column_candidates(pt):
            if col and col not in mapping:
                mapping[col] = pt
        col = plot_column_name(pt)
        if col and col not in mapping:
            mapping[col] = pt
    return mapping


def _equipment_type_label(eq: dict[str, Any]) -> str:
    for key in ("equipment_type", "brick_type", "type"):
        val = str(eq.get(key) or "").strip()
        if val:
            return val.replace("_", " ")
    return ""


def _point_context(pt: dict[str, Any]) -> dict[str, Any]:
    meta = pt.get("metadata") if isinstance(pt.get("metadata"), dict) else {}
    bacnet_dev = pt.get("bacnet_device_id")
    if bacnet_dev is None:
        bacnet_dev = meta.get("device_instance") or pt.get("device_instance")
    oid = str(pt.get("object_identifier") or pt.get("bacnet_object_id") or "").strip()
    return {
        "id": str(pt.get("id") or ""),
        "name": str(pt.get("description") or pt.get("name") or pt.get("brick_type") or pt.get("id") or ""),
        "external_id": str(pt.get("external_id") or plot_column_name(pt) or ""),
        "fdd_input": str(pt.get("fdd_input") or ""),
        "brick_type": str(pt.get("brick_type") or ""),
        "bacnet_device_id": bacnet_dev,
        "object_identifier": oid,
    }


def resolve_fault_model_context(
    *,
    model: dict[str, Any],
    site_id: str,
    rule_id: str = "",
    rule_name: str = "",
    fault_code: str = "",
    equipment_id: str = "",
    equipment_name: str = "",
    flagged_columns: list[str] | None = None,
) -> dict[str, Any]:
    """Flat operator-facing context for one FDD fault alert."""
    eq_index = _equipment_index(model, site_id)
    col_map = column_to_equipment_map(model, site_id)
    pt_by_col = _column_to_point(model, site_id)

    cols = [str(c).strip() for c in (flagged_columns or []) if str(c).strip()]
    pt: dict[str, Any] | None = None
    for col in cols:
        pt = pt_by_col.get(col)
        if pt:
            break

    eid = str(equipment_id or "").strip()
    ename = str(equipment_name or "").strip()
    if not eid and cols:
        eid = str((col_map.get(cols[0]) or {}).get("equipment_id") or "")
    if not ename and eid:
        ename = str((eq_index.get(eid) or {}).get("name") or eid)
    if not ename and cols:
        names = equipment_labels_for_columns(model, site_id, cols)
        ename = names[0] if names else ""

    eq = eq_index.get(eid) if eid else None
    eq_type = _equipment_type_label(eq) if eq else ""

    point_ctx = _point_context(pt) if pt else None
    bacnet_line = ""
    if point_ctx:
        dev = point_ctx.get("bacnet_device_id")
        oid = point_ctx.get("object_identifier")
        if dev is not None and oid:
            bacnet_line = f"device {dev} · {oid}"
        elif dev is not None:
            bacnet_line = f"device {dev}"

    return {
        "severity": "",
        "rule_id": rule_id,
        "rule_name": rule_name,
        "fault_code": fault_code,
        "site_id": site_id,
        "equipment": {
            "id": eid or ename or "—",
            "name": ename or eid or "—",
            "type": eq_type or "—",
        },
        "point": point_ctx
        or {
            "id": "",
            "name": "not mapped",
            "external_id": cols[0] if cols else "",
            "fdd_input": "",
            "brick_type": "",
            "bacnet_device_id": None,
            "object_identifier": "",
        },
        "bacnet_summary": bacnet_line or "not available",
        "historian_column": cols[0] if cols else (point_ctx or {}).get("external_id", ""),
    }


def enrich_fault_alert(alert: dict[str, Any], model: dict[str, Any]) -> dict[str, Any]:
    """Attach model_context to a fault alert when source is FDD."""
    if str(alert.get("source") or "") != "fdd":
        return alert
    analytics = alert.get("analytics") if isinstance(alert.get("analytics"), dict) else {}
    cols = analytics.get("flagged_columns") or analytics.get("value_columns") or []
    site_id = ""
    title = str(alert.get("title") or "")
    if " at " in title:
        site_id = title.rsplit(" at ", 1)[-1].strip()
    if not site_id:
        for pt in model.get("points") or []:
            if isinstance(pt, dict) and pt.get("site_id"):
                site_id = str(pt["site_id"])
                break
        if not site_id and model.get("sites"):
            site_id = str((model["sites"][0] or {}).get("id") or "")

    ctx = resolve_fault_model_context(
        model=model,
        site_id=site_id,
        rule_id=str(alert.get("rule_id") or ""),
        rule_name=str(alert.get("rule_name") or ""),
        fault_code=str(alert.get("code") or ""),
        equipment_id=str(alert.get("equipment_id") or ""),
        equipment_name=str(alert.get("equipment_name") or ""),
        flagged_columns=list(cols) if isinstance(cols, list) else [],
    )
    ctx["severity"] = str(alert.get("severity") or "warning")
    out = dict(alert)
    out["model_context"] = ctx
    if ctx["equipment"]["name"] and not out.get("equipment_name"):
        out["equipment_name"] = ctx["equipment"]["name"]
    if ctx["equipment"]["id"] and not out.get("equipment_id"):
        out["equipment_id"] = ctx["equipment"]["id"]
    return out
