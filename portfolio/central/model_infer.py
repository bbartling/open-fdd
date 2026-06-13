"""Infer BACnet + equipment fields missing from GL36 BACnet-sync model rows."""

from __future__ import annotations

import re
from typing import Any

from portfolio.central.equipment_classify import effective_equipment_type, hvac_bucket, report_family

_POINT_ID_DEVICE = re.compile(r"^(\d+)-", re.I)
_OBJECT_ID = re.compile(r"^(\d+)-((?:analog|binary|multi-state|character-string|integer)[^-]+(?:-\d+)?)$", re.I)


def infer_bacnet_device_id(
    point: dict[str, Any],
    *,
    equipment: dict[str, Any] | None = None,
) -> str:
    """Device instance from metadata, equipment row, or point id prefix (e.g. 12035-analog-input-1)."""
    meta = point.get("metadata") if isinstance(point.get("metadata"), dict) else {}
    for src in (
        point.get("bacnet_device_id"),
        meta.get("bacnet_device_id"),
        meta.get("device_instance"),
        (equipment or {}).get("bacnet_device_instance"),
        (equipment or {}).get("bacnet_device_id"),
    ):
        if src is not None and str(src).strip():
            return str(src).strip()
    pid = str(point.get("id") or point.get("point_id") or "")
    m = _POINT_ID_DEVICE.match(pid)
    if m:
        return m.group(1)
    return ""


def infer_object_identifier(point: dict[str, Any]) -> str:
    meta = point.get("metadata") if isinstance(point.get("metadata"), dict) else {}
    for src in (
        point.get("object_identifier"),
        meta.get("object_identifier"),
        meta.get("object_id"),
        point.get("bacnet_object"),
    ):
        if src is not None and str(src).strip():
            return str(src).strip()
    pid = str(point.get("id") or point.get("point_id") or "")
    m = _OBJECT_ID.match(pid)
    if m:
        return m.group(2).replace("-", ",")
    parts = pid.split("-", 1)
    if len(parts) == 2 and parts[0].isdigit():
        return parts[1].replace("-", ",", 1) if parts[1].count("-") else parts[1]
    return ""


def infer_equipment_type(eq: dict[str, Any]) -> str:
    et = effective_equipment_type(eq)
    if et and et != "Equipment":
        return et
    fam = report_family(eq)
    return {"ahu": "AHU", "vav": "VAV", "hws": "Hot_Water_Plant"}.get(fam, et or "Equipment")


def enrich_point_row(
    point: dict[str, Any],
    *,
    equipment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    pt = dict(point)
    dev = infer_bacnet_device_id(pt, equipment=equipment)
    obj = infer_object_identifier(pt)
    if dev:
        pt["bacnet_device_id"] = dev
        meta = dict(pt.get("metadata") or {})
        if not meta.get("bacnet_device_id"):
            meta["bacnet_device_id"] = dev
        pt["metadata"] = meta
    if obj:
        pt["object_identifier"] = obj
        meta = dict(pt.get("metadata") or {})
        if not meta.get("object_identifier"):
            meta["object_identifier"] = obj
        pt["metadata"] = meta
    return pt


def enrich_equipment_row(eq: dict[str, Any]) -> dict[str, Any]:
    row = dict(eq)
    bucket = hvac_bucket(row)
    if bucket and not str(row.get("brick_type") or "").strip():
        row["brick_type"] = bucket
    if bucket and not str(row.get("equipment_type") or "").strip():
        row["equipment_type"] = bucket
    et = infer_equipment_type(row)
    if et:
        row["equipment_type"] = et
    return row
