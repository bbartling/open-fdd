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
    svc = ModelService()
    from .site_defaults import ensure_default_site
    from .ttl_service import TtlService

    ensure_default_site(svc, TtlService())
    enabled = [r for r in _load_csv(_points_csv_path()) if str(r.get("enabled") or "") in {"1", "true", "yes"}]
    discovered = {r.get("point_id", ""): r for r in _load_csv(_discovered_csv_path()) if r.get("point_id")}
    added = 0
    updated = 0
    removed = 0
    sid = ""

    with svc.transaction() as model:
        sid = (site_id or "").strip() or require_model_site(model)
        equipment = model.setdefault("equipment", [])
        points = model.setdefault("points", [])
        by_key = _model_bacnet_keys(points)

        devices_touched: set[str] = set()
        desired_keys: set[str] = set()
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
            desired_keys.add(key)
            default_eq_id = f"bacnet-{inst}"
            devices_touched.add(inst)
            if not any(isinstance(e, dict) and str(e.get("id")) == default_eq_id for e in equipment):
                equipment.append(
                    {
                        "id": default_eq_id,
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
                existing_eq = str(pt.get("equipment_id") or "").strip()
                eq_id = (
                    existing_eq
                    if existing_eq and not existing_eq.startswith("bacnet-")
                    else default_eq_id
                )
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
                eq_id = default_eq_id
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

        bacnet_eq_ids = {
            str(e.get("id"))
            for e in equipment
            if isinstance(e, dict) and _is_bacnet_equipment(e)
        }
        before_pts = len(points)
        model["points"] = [
            p
            for p in points
            if isinstance(p, dict)
            and not (
                _is_bacnet_point(p, bacnet_eq_ids)
                and _point_key(
                    str(p.get("bacnet_device_id") or ""),
                    str(p.get("object_identifier") or ""),
                )
                not in desired_keys
            )
        ]
        removed = before_pts - len(model["points"])
        remaining_eq_ids = {str(p.get("equipment_id") or "") for p in model["points"] if isinstance(p, dict)}
        model["equipment"] = [
            e
            for e in equipment
            if isinstance(e, dict)
            and (not _is_bacnet_equipment(e) or str(e.get("id")) in remaining_eq_ids)
        ]

    ttl_path = None
    if sync_ttl and (added or updated or removed):
        ttl_path = str(TtlService().sync())

    return {
        "ok": True,
        "site_id": sid,
        "points_added": added,
        "points_updated": updated,
        "points_removed": removed,
        "devices": sorted(devices_touched),
        "ttl_path": ttl_path,
    }


def _is_bacnet_equipment(row: dict[str, Any]) -> bool:
    eq_id = str(row.get("id") or "")
    return (
        eq_id.startswith("bacnet-")
        or row.get("bacnet_device_id") is not None
        or str(row.get("equipment_type") or "") == "BACnet_Device"
    )


def _is_bacnet_point(row: dict[str, Any], bacnet_eq_ids: set[str]) -> bool:
    if row.get("bacnet_device_id") is not None:
        return True
    if str(row.get("equipment_id") or "") in bacnet_eq_ids:
        return True
    meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    if meta.get("point_id") and (row.get("object_identifier") or meta.get("series_id")):
        return True
    return False


def remove_device_from_model(*, device_instance: int, sync_ttl: bool = True) -> dict[str, Any]:
    """Drop one BACnet device and its points from model.json."""
    inst = str(device_instance)
    eq_id = f"bacnet-{inst}"
    eq_ids = {eq_id}
    points_removed = 0
    equipment_removed = 0

    with ModelService().transaction() as model:
        equipment = model.get("equipment", [])
        for eq in equipment:
            if isinstance(eq, dict) and str(eq.get("id")) == eq_id:
                equipment_removed = 1
                break
            if isinstance(eq, dict) and str(eq.get("bacnet_device_id") or "") == inst:
                eq_ids.add(str(eq.get("id")))
                equipment_removed += 1

        before_pts = len(model.get("points", []))
        model["points"] = [
            p
            for p in model.get("points", [])
            if isinstance(p, dict)
            and str(p.get("bacnet_device_id") or "") != inst
            and str(p.get("equipment_id") or "") not in eq_ids
        ]
        points_removed = before_pts - len(model["points"])
        model["equipment"] = [
            e
            for e in equipment
            if isinstance(e, dict)
            and str(e.get("id")) not in eq_ids
            and str(e.get("bacnet_device_id") or "") != inst
        ]

    ttl_path = str(TtlService().sync()) if sync_ttl and (points_removed or equipment_removed) else None
    return {
        "ok": True,
        "device_instance": device_instance,
        "points_removed": points_removed,
        "equipment_removed": equipment_removed,
        "ttl_path": ttl_path,
    }


def clear_bacnet_from_model(*, sync_ttl: bool = True) -> dict[str, Any]:
    """Remove all BACnet driver equipment/points from model.json; keep sites and manual rows."""
    points_removed = 0
    equipment_removed = 0

    with ModelService().transaction() as model:
        equipment = model.get("equipment", [])
        bacnet_eq_ids = {
            str(e.get("id"))
            for e in equipment
            if isinstance(e, dict) and _is_bacnet_equipment(e)
        }
        equipment_removed = len(bacnet_eq_ids)
        before_pts = len(model.get("points", []))
        model["points"] = [
            p
            for p in model.get("points", [])
            if isinstance(p, dict) and not _is_bacnet_point(p, bacnet_eq_ids)
        ]
        points_removed = before_pts - len(model["points"])
        model["equipment"] = [
            e for e in equipment if isinstance(e, dict) and str(e.get("id")) not in bacnet_eq_ids
        ]

    ttl_path = str(TtlService().sync()) if sync_ttl else None
    return {
        "ok": True,
        "points_removed": points_removed,
        "equipment_removed": equipment_removed,
        "ttl_path": ttl_path,
    }


def bacnet_sync_status(*, site_id: str | None = None) -> dict[str, Any]:
    """Compare enabled BACnet poll CSV rows with model.json BACnet points."""
    svc = ModelService()
    from .site_defaults import ensure_default_site

    ensure_default_site(svc, TtlService())
    model = svc.load()
    sid = (site_id or "").strip() or require_model_site(model)

    enabled_rows = [
        r for r in _load_csv(_points_csv_path()) if str(r.get("enabled") or "") in {"1", "true", "yes"}
    ]
    discovered = {r.get("point_id", ""): r for r in _load_csv(_discovered_csv_path()) if r.get("point_id")}

    poll_keys: set[str] = set()
    for row in enabled_rows:
        src = discovered.get(str(row.get("point_id") or ""), row)
        inst = str(src.get("device_instance") or row.get("device_instance") or "")
        obj_type = str(src.get("object_type") or row.get("object_type") or "")
        obj_inst = str(src.get("object_instance") or row.get("object_instance") or "")
        if inst and obj_type and obj_inst:
            poll_keys.add(_point_key(inst, f"{obj_type},{obj_inst}"))

    points = [p for p in model.get("points", []) if isinstance(p, dict)]
    bacnet_eq_ids = {
        str(e.get("id"))
        for e in model.get("equipment", [])
        if isinstance(e, dict) and _is_bacnet_equipment(e)
    }
    model_bacnet = [p for p in points if _is_bacnet_point(p, bacnet_eq_ids) and str(p.get("site_id") or "") == sid]
    model_keys = {
        _point_key(str(p.get("bacnet_device_id") or ""), str(p.get("object_identifier") or ""))
        for p in model_bacnet
        if p.get("bacnet_device_id") is not None and p.get("object_identifier")
    }

    missing_in_model = sorted(poll_keys - model_keys)
    extra_in_model = sorted(model_keys - poll_keys)
    ttl = TtlService()
    in_sync = not missing_in_model and not extra_in_model

    return {
        "ok": True,
        "site_id": sid,
        "in_sync": in_sync,
        "poll_enabled_count": len(poll_keys),
        "model_bacnet_count": len(model_keys),
        "missing_in_model": missing_in_model[:40],
        "extra_in_model": extra_in_model[:40],
        "missing_in_model_total": len(missing_in_model),
        "extra_in_model_total": len(extra_in_model),
        "ttl_path": str(ttl.ttl_path),
        "ttl_exists": ttl.ttl_path.is_file(),
        "points_csv": str(_points_csv_path()),
    }
