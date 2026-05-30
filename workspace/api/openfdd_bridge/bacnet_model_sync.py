"""Merge BACnet discovery rows into the BRICK data model (model.json)."""

from __future__ import annotations

import csv
import re
import uuid
from pathlib import Path
from typing import Any

from .model_service import ModelService
from .paths import workspace_dir

_SAFE = re.compile(r"[^a-zA-Z0-9_-]+")


def _slug(text: str, *, max_len: int = 48) -> str:
    s = _SAFE.sub("_", str(text or "").strip()).strip("_").lower()
    return (s[:max_len] if s else "point")


def _parse_oid(oid: str) -> tuple[str, str]:
    parts = str(oid or "").split(",", 1)
    if len(parts) != 2:
        return "", ""
    return parts[0].strip(), parts[1].strip()


def _point_key(device_instance: int, object_identifier: str) -> str:
    return f"{device_instance}:{object_identifier}"


def _existing_keys(points: list[dict[str, Any]]) -> set[str]:
    keys: set[str] = set()
    for pt in points:
        if not isinstance(pt, dict):
            continue
        dev = pt.get("bacnet_device_id") or pt.get("device_instance")
        oid = pt.get("object_identifier") or pt.get("bacnet_object_id")
        if dev is not None and oid:
            keys.add(_point_key(int(dev), str(oid)))
    return keys


def _row_to_model_point(
    *,
    device_instance: int,
    device_address: str,
    object_identifier: str,
    object_name: str,
    site_id: str,
    equipment_id: str,
    description: str = "",
) -> dict[str, Any]:
    obj_type, obj_inst = _parse_oid(object_identifier)
    external = _slug(object_name or f"{obj_type}_{obj_inst}")
    return {
        "id": str(uuid.uuid4()),
        "site_id": site_id,
        "equipment_id": equipment_id,
        "external_id": external,
        "brick_type": "",
        "fdd_input": external,
        "bacnet_device_id": device_instance,
        "bacnet_device_address": device_address,
        "object_identifier": object_identifier,
        "object_type": obj_type,
        "object_instance": obj_inst,
        "description": description or object_name,
    }


def _load_csv_rows_for_device(device_instance: int) -> list[dict[str, str]]:
    path = workspace_dir() / "bacnet" / "commissioning" / "points_discovered.csv"
    if not path.is_file():
        return []
    rows: list[dict[str, str]] = []
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if str(row.get("device_instance") or "").strip() != str(device_instance):
                continue
            rows.append(row)
    return rows


def merge_device_into_model(
    *,
    device_instance: int,
    device_address: str = "",
    objects: list[dict[str, Any]] | None = None,
    site_id: str | None = None,
    equipment_name: str | None = None,
) -> dict[str, Any]:
    """Append BACnet points for one device; create site/equipment rows when missing."""
    svc = ModelService()
    model = svc.load()
    sites = model.setdefault("sites", [])
    equipment = model.setdefault("equipment", [])
    points = model.setdefault("points", [])

    sid = (site_id or "").strip()
    if not sid:
        sid = str(sites[0].get("id")) if sites and isinstance(sites[0], dict) else "site-default"
    if not any(isinstance(s, dict) and str(s.get("id")) == sid for s in sites):
        sites.append({"id": sid, "name": sid.replace("-", " ").title()})

    eq_id = f"bacnet-{device_instance}"
    eq_row = next((e for e in equipment if isinstance(e, dict) and str(e.get("id")) == eq_id), None)
    if eq_row is None:
        equipment.append(
            {
                "id": eq_id,
                "site_id": sid,
                "name": equipment_name or f"BACnet device {device_instance}",
                "equipment_type": "BACnet_Device",
                "bacnet_device_id": device_instance,
            }
        )

    known = _existing_keys(points)
    added: list[dict[str, Any]] = []

    if objects:
        for obj in objects:
            oid = str(obj.get("object_identifier") or "").strip()
            if not oid:
                continue
            key = _point_key(device_instance, oid)
            if key in known:
                continue
            pt = _row_to_model_point(
                device_instance=device_instance,
                device_address=device_address,
                object_identifier=oid,
                object_name=str(obj.get("name") or oid),
                site_id=sid,
                equipment_id=eq_id,
            )
            points.append(pt)
            known.add(key)
            added.append(pt)
    else:
        for row in _load_csv_rows_for_device(device_instance):
            obj_type = str(row.get("object_type") or "").strip()
            obj_inst = str(row.get("object_instance") or "").strip()
            if not obj_type or not obj_inst:
                continue
            oid = f"{obj_type},{obj_inst}"
            key = _point_key(device_instance, oid)
            if key in known:
                continue
            addr = str(row.get("device_address") or device_address)
            pt = _row_to_model_point(
                device_instance=device_instance,
                device_address=addr,
                object_identifier=oid,
                object_name=str(row.get("object_name") or row.get("description") or oid),
                site_id=sid,
                equipment_id=eq_id,
                description=str(row.get("description") or ""),
            )
            points.append(pt)
            known.add(key)
            added.append(pt)

    svc.store.save(model)
    return {
        "ok": True,
        "device_instance": device_instance,
        "site_id": sid,
        "equipment_id": eq_id,
        "points_added": len(added),
        "total_points": len(points),
    }
