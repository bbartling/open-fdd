"""Sync BACnet poll-driver CSV rows into model.json + BRICK TTL (Feather series refs)."""

from __future__ import annotations

import csv
import re
from typing import Any

from .model_service import ModelService
from .paths import workspace_dir
from .ttl_service import TtlService

_SAFE = re.compile(r"[^a-zA-Z0-9_-]+")


def _slug(text: str, *, max_len: int = 48) -> str:
    s = _SAFE.sub("_", str(text or "").strip()).strip("_").lower()
    return (s[:max_len] if s else "point")


def _points_csv_path():
    return workspace_dir() / "bacnet" / "commissioning" / "points.csv"


def _discovered_csv_path():
    return workspace_dir() / "bacnet" / "commissioning" / "points_discovered.csv"


def _load_csv(path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        return [dict(row) for row in csv.DictReader(fh)]


def feather_external_ref(*, site_id: str, series_id: str) -> str:
    sid = _slug(site_id, max_len=64)
    series = str(series_id or "").strip()
    return f"feather://bacnet/{sid}/{series}"


def require_model_site(model: dict[str, Any]) -> str:
    sites = model.get("sites") or []
    if not sites or not isinstance(sites[0], dict):
        raise ValueError("Configure a BRICK site on the Data Model tab before BACnet polling sync.")
    sid = str(sites[0].get("id") or "").strip()
    if not sid:
        raise ValueError("Configure a BRICK site on the Data Model tab before BACnet polling sync.")
    return sid


def _point_key(device_instance: str, object_identifier: str) -> str:
    return f"{device_instance}:{object_identifier}"


def _model_bacnet_keys(points: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for pt in points:
        if not isinstance(pt, dict):
            continue
        dev = pt.get("bacnet_device_id") or pt.get("device_instance")
        oid = pt.get("object_identifier") or pt.get("bacnet_object_id")
        if dev is not None and oid:
            out[_point_key(str(dev), str(oid))] = pt
    return out


def sync_enabled_polling_to_model(*, site_id: str | None = None, sync_ttl: bool = True) -> dict[str, Any]:
    """Upsert model.json points for every enabled row in points.csv."""
    enabled = [r for r in _load_csv(_points_csv_path()) if str(r.get("enabled") or "") in {"1", "true", "yes"}]
    discovered = {r.get("point_id", ""): r for r in _load_csv(_discovered_csv_path()) if r.get("point_id")}
    svc = ModelService()
    added = 0
    updated = 0
    sid = ""

    with svc.transaction() as model:
        sid = (site_id or "").strip() or require_model_site(model)
        equipment = model.setdefault("equipment", [])
        points = model.setdefault("points", [])
        by_key = _model_bacnet_keys(points)

        devices_touched: set[str] = set()
        for row in enabled:
            pid = str(row.get("point_id") or "")
            src = discovered.get(pid, row)
            inst = str(src.get("device_instance") or row.get("device_instance") or "")
            obj_type = str(src.get("object_type") or row.get("object_type") or "")
            obj_inst = str(src.get("object_instance") or row.get("object_instance") or "")
            if not inst or not obj_type or not obj_inst:
                continue
            oid = f"{obj_type},{obj_inst}"
            key = _point_key(inst, oid)
            eq_id = f"bacnet-{inst}"
            devices_touched.add(inst)
            if not any(isinstance(e, dict) and str(e.get("id")) == eq_id for e in equipment):
                equipment.append(
                    {
                        "id": eq_id,
                        "site_id": sid,
                        "name": f"BACnet device {inst}",
                        "equipment_type": "BACnet_Device",
                        "bacnet_device_id": int(inst) if inst.isdigit() else inst,
                    }
                )
            series_id = str(row.get("series_id") or src.get("series_id") or "")
            external_ref = feather_external_ref(site_id=sid, series_id=series_id) if series_id else ""
            name = str(src.get("object_name") or row.get("object_name") or oid)
            poll_s = str(row.get("poll_interval_s") or "60")
            metadata = {
                "external_ref": external_ref,
                "series_id": series_id,
                "poll_interval_s": poll_s,
                "point_id": pid,
            }
            if key in by_key:
                pt = by_key[key]
                pt["site_id"] = sid
                pt["equipment_id"] = eq_id
                pt["bacnet_device_id"] = int(inst) if inst.isdigit() else inst
                pt["bacnet_device_address"] = str(src.get("device_address") or "")
                pt["object_identifier"] = oid
                pt["object_type"] = obj_type
                pt["object_instance"] = obj_inst
                pt["description"] = name
                pt["metadata"] = {**(pt.get("metadata") if isinstance(pt.get("metadata"), dict) else {}), **metadata}
                updated += 1
            else:
                pt = {
                    "id": pid or f"{eq_id}-{obj_type}-{obj_inst}",
                    "site_id": sid,
                    "equipment_id": eq_id,
                    "external_id": _slug(name),
                    "brick_type": str(src.get("brick_class") or row.get("brick_class") or ""),
                    "fdd_input": _slug(name),
                    "bacnet_device_id": int(inst) if inst.isdigit() else inst,
                    "bacnet_device_address": str(src.get("device_address") or ""),
                    "object_identifier": oid,
                    "object_type": obj_type,
                    "object_instance": obj_inst,
                    "description": name,
                    "metadata": metadata,
                }
                points.append(pt)
                by_key[key] = pt
                added += 1

    ttl_path = None
    if sync_ttl and (added or updated):
        ttl_path = str(TtlService().sync())

    return {
        "ok": True,
        "site_id": sid,
        "points_added": added,
        "points_updated": updated,
        "devices": sorted(devices_touched),
        "ttl_path": ttl_path,
    }
