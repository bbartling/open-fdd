"""BACnet poll driver CSV store — points_discovered.csv + points.csv."""

from __future__ import annotations

import csv
import os
import threading
from pathlib import Path
from typing import Any

from bacnet_toolshed.config import CSV_FIELDNAMES, normalize_row
from bacnet_toolshed.point_id import make_point_id, make_series_id

from .paths import workspace_dir

_DRIVER_LOCK = threading.RLock()
POLL_INTERVALS_S = (60, 300, 600, 900)
POLL_LABELS = {60: "1 min", 300: "5 min", 600: "10 min", 900: "15 min"}


def _discovered_path() -> Path:
    return workspace_dir() / "bacnet" / "commissioning" / "points_discovered.csv"


def _points_path() -> Path:
    return workspace_dir() / "bacnet" / "commissioning" / "points.csv"


def _commission_defaults() -> dict[str, str]:
    env_path = workspace_dir() / "bacnet" / "commissioning" / "commission.env"
    out: dict[str, str] = {"site_id": "site", "building_id": "building"}
    if env_path.is_file():
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip().lower()
            val = val.strip().strip('"').strip("'")
            if key == "site_id":
                out["site_id"] = val
            elif key == "building_id":
                out["building_id"] = val
    try:
        from .model_service import ModelService
        from .site_defaults import ensure_default_site
        from .ttl_service import TtlService

        sid = ensure_default_site(ModelService(), TtlService())
        if out["site_id"] in {"", "site", "demo"}:
            out["site_id"] = sid
    except Exception:
        pass
    return out


def _load_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        return [dict(row) for row in csv.DictReader(fh)]


def _save_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in CSV_FIELDNAMES})


def _parse_oid(oid: str) -> tuple[str, str]:
    parts = str(oid or "").split(",", 1)
    if len(parts) != 2:
        return "", ""
    return parts[0].strip(), parts[1].strip()


def _object_row(
    *,
    device_instance: int,
    device_address: str,
    object_identifier: str,
    object_name: str,
    defaults: dict[str, str],
) -> dict[str, str]:
    obj_type, obj_inst = _parse_oid(object_identifier)
    raw = {
        "device_instance": str(device_instance),
        "device_address": device_address,
        "object_type": obj_type,
        "object_instance": obj_inst,
        "object_name": object_name or object_identifier,
        "description": object_name or "",
        "present_value": "",
        "units": "",
        "site_id": defaults["site_id"],
        "building_id": defaults["building_id"],
        "system_id": "bacnet",
        "brick_class": "",
        "brick_tag": "",
        "enabled": "0",
        "poll_interval_s": "60",
    }
    row = normalize_row(raw, defaults)
    if not row.get("point_id"):
        row["point_id"] = make_point_id(device_instance, obj_type, obj_inst)
    return row


def _latest_poll_values() -> dict[str, str]:
    """Last present-value per point_id from poll samples CSV."""
    from .paths import bacnet_poll_csv, workspace_dir

    from .bacnet_value_convert import convert_poll_value, load_convert_context, profile_for_sample

    path = bacnet_poll_csv()
    if not path.is_file():
        return {}
    commission_dir = workspace_dir() / "bacnet" / "commissioning"
    device_profiles, point_profiles = load_convert_context(commission_dir)
    discovered = {}
    disc_path = commission_dir / "points_discovered.csv"
    if disc_path.is_file():
        with disc_path.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                pid = str(row.get("point_id") or "").strip()
                if pid:
                    discovered[pid] = dict(row)

    latest: dict[str, tuple[str, str, str]] = {}
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            pid = str(row.get("point_id") or "").strip()
            if not pid:
                continue
            ts = str(row.get("timestamp_utc") or "")
            val = str(row.get("value") if row.get("value") is not None else "")
            units = str(row.get("units") or "")
            prev = latest.get(pid)
            if prev is None or ts >= prev[0]:
                latest[pid] = (ts, val, units)

    out: dict[str, str] = {}
    for pid, (_ts, val, units) in latest.items():
        if val in ("", "nan", "None"):
            continue
        try:
            num = float(val)
            if num <= -400:
                continue
        except ValueError:
            num = None
        disc = discovered.get(pid) or {}
        inst = str(disc.get("device_instance") or "")
        profile = profile_for_sample(
            point_id=pid,
            device_instance=inst,
            device_profiles=device_profiles,
            point_profiles=point_profiles,
        )
        if num is not None:
            num, units = convert_poll_value(num, units=units, profile=profile)
            val = str(num)
        out[pid] = f"{val}{(' ' + units) if units else ''}"
    return out


def device_in_driver(device_instance: int) -> bool:
    inst = str(device_instance)
    return any(str(r.get("device_instance") or "") == inst for r in _load_csv(_discovered_path()))


def sync_discovery(
    *,
    device_instance: int,
    device_address: str = "",
    objects: list[dict[str, Any]],
    replace: bool = False,
    merge_existing: bool = False,
) -> dict[str, Any]:
    """Merge point-discovery objects into points_discovered.csv."""
    if not objects:
        return {"ok": True, "rows_added": 0, "total": 0}
    inst = str(device_instance)
    if not replace and not merge_existing and device_in_driver(device_instance):
        raise ValueError(
            f"device {device_instance} is already in the driver — remove it from the tree or use Refresh points"
        )
    defaults = _commission_defaults()
    with _DRIVER_LOCK:
        rows = _load_csv(_discovered_path())
        if replace:
            rows = [r for r in rows if str(r.get("device_instance") or "") != inst]
        by_pid = {r.get("point_id", ""): r for r in rows if r.get("point_id")}
        added = 0
        for obj in objects:
            oid = str(obj.get("object_identifier") or "").strip()
            if not oid:
                continue
            row = _object_row(
                device_instance=device_instance,
                device_address=device_address,
                object_identifier=oid,
                object_name=str(obj.get("name") or oid),
                defaults=defaults,
            )
            pid = row["point_id"]
            if pid in by_pid:
                existing = by_pid[pid]
                if device_address:
                    existing["device_address"] = device_address
                if row.get("object_name"):
                    existing["object_name"] = row["object_name"]
            else:
                rows.append(row)
                by_pid[pid] = row
                added += 1
        _save_csv(_discovered_path(), rows)
    return {"ok": True, "rows_added": added, "total": len(rows)}


def merge_commission_rows(
    rows: list[dict[str, Any]],
    *,
    enable_poll: bool = True,
) -> dict[str, Any]:
    """Upsert full commission rows into points_discovered.csv and optional points.csv."""
    if not rows:
        return {"ok": True, "discovered_added": 0, "poll_enabled": 0}
    defaults = _commission_defaults()
    discovered_added = 0
    poll_enabled = 0
    with _DRIVER_LOCK:
        discovered = _load_csv(_discovered_path())
        by_pid = {r.get("point_id", ""): r for r in discovered if r.get("point_id")}
        for raw in rows:
            row = normalize_row(dict(raw), defaults)
            pid = str(row.get("point_id") or "").strip()
            if not pid:
                continue
            if pid not in by_pid:
                discovered.append(row)
                by_pid[pid] = row
                discovered_added += 1
            else:
                existing = by_pid[pid]
                for key in (
                    "object_name",
                    "brick_class",
                    "brick_tag",
                    "system_id",
                    "units",
                    "device_address",
                ):
                    if row.get(key):
                        existing[key] = row[key]
        _save_csv(_discovered_path(), discovered)

        if enable_poll:
            points = _load_csv(_points_path())
            poll_by = {r.get("point_id", ""): r for r in points if r.get("point_id")}
            for raw in rows:
                if str(raw.get("enabled") or "0").strip().lower() not in {"1", "true", "yes"}:
                    continue
                row = normalize_row(dict(raw), defaults)
                pid = str(row.get("point_id") or "").strip()
                if not pid:
                    continue
                row["enabled"] = "1"
                try:
                    row["poll_interval_s"] = str(
                        _ensure_poll_interval(int(str(row.get("poll_interval_s") or "60")))
                    )
                except ValueError:
                    row["poll_interval_s"] = "60"
                poll_by[pid] = row
                poll_enabled += 1
            _save_csv(_points_path(), list(poll_by.values()))

    model_sync = _sync_poll_model(poll_enabled > 0)
    poll_trigger: dict[str, Any] | None = None
    if poll_enabled > 0:
        try:
            from .commission_client import commission_poll_once

            code, payload = commission_poll_once()
            poll_trigger = {
                "status_code": code,
                **(payload if isinstance(payload, dict) else {"detail": payload}),
            }
        except Exception as exc:
            poll_trigger = {"ok": False, "error": str(exc)}
    return {
        "ok": True,
        "discovered_added": discovered_added,
        "poll_enabled": poll_enabled,
        "model_sync": model_sync,
        "poll_trigger": poll_trigger,
    }


def driver_tree() -> dict[str, Any]:
    """Device tree from discovered CSV merged with points.csv poll flags."""
    with _DRIVER_LOCK:
        discovered = _load_csv(_discovered_path())
        enabled_rows = {r.get("point_id", ""): r for r in _load_csv(_points_path()) if r.get("point_id")}
    latest_pv = _latest_poll_values()
    devices: dict[str, dict[str, Any]] = {}
    for raw in discovered:
        inst = str(raw.get("device_instance") or "").strip()
        if not inst:
            continue
        obj_type = str(raw.get("object_type") or "")
        obj_inst = str(raw.get("object_instance") or "")
        oid = f"{obj_type},{obj_inst}" if obj_type and obj_inst else ""
        pid = str(raw.get("point_id") or "")
        if not pid and oid:
            pid = make_point_id(inst, obj_type, obj_inst)
        poll_row = enabled_rows.get(pid, {})
        # Poll badge reflects points.csv only (actual RPM list), not discovery CSV enabled flag.
        enabled = bool(poll_row) and str(poll_row.get("enabled") or "0").strip().lower() in {
            "1",
            "true",
            "yes",
        }
        try:
            interval = int(str(poll_row.get("poll_interval_s") or raw.get("poll_interval_s") or "0"))
        except ValueError:
            interval = 0
        if interval not in POLL_LABELS:
            interval = 60 if enabled else 0
        dev = devices.setdefault(
            inst,
            {
                "device_instance": inst,
                "device_address": str(raw.get("device_address") or ""),
                "points": [],
            },
        )
        if raw.get("device_address"):
            dev["device_address"] = str(raw["device_address"])
        dev["points"].append(
            {
                "point_id": pid,
                "object_identifier": oid,
                "object_name": str(raw.get("object_name") or oid),
                "object_type": obj_type,
                "enabled": enabled,
                "poll_interval_s": interval if enabled else 0,
                "poll_label": POLL_LABELS.get(interval, "") if enabled else "",
                "present_value": latest_pv.get(pid, "") if enabled else str(raw.get("present_value") or ""),
                "series_id": str(poll_row.get("series_id") or raw.get("series_id") or ""),
            }
        )
    device_list = sorted(devices.values(), key=lambda d: int(d["device_instance"]))
    for dev in device_list:
        dev["point_count"] = len(dev["points"])
        dev["poll_count"] = sum(1 for p in dev["points"] if p["enabled"])
    return {
        "ok": True,
        "devices": device_list,
        "discovered_path": str(_discovered_path()),
        "points_path": str(_points_path()),
        "poll_intervals": [{"seconds": s, "label": POLL_LABELS[s]} for s in POLL_INTERVALS_S],
    }


def _ensure_poll_interval(interval_s: int) -> int:
    if interval_s not in POLL_LABELS:
        raise ValueError(f"poll_interval_s must be one of {list(POLL_LABELS)}")
    return interval_s


def _apply_point_poll_row(*, point_id: str, enabled: bool, poll_interval_s: int) -> None:
    discovered = _load_csv(_discovered_path())
    src = next((r for r in discovered if r.get("point_id") == point_id), None)
    if src is None:
        raise ValueError(f"unknown point_id: {point_id}")
    points = _load_csv(_points_path())
    by_pid = {r.get("point_id", ""): r for r in points if r.get("point_id")}
    row = dict(src)
    if enabled:
        row["enabled"] = "1"
        row["poll_interval_s"] = str(_ensure_poll_interval(poll_interval_s))
        by_pid[point_id] = normalize_row(row, _commission_defaults())
    elif point_id in by_pid:
        del by_pid[point_id]
    _save_csv(_points_path(), list(by_pid.values()))


def _sync_poll_model(enabled: bool) -> dict[str, Any] | None:
    if not enabled:
        return None
    try:
        from .bacnet_poll_model_sync import sync_enabled_polling_to_model

        return sync_enabled_polling_to_model(sync_ttl=True)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}


def set_point_poll(*, point_id: str, enabled: bool, poll_interval_s: int = 60) -> dict[str, Any]:
    with _DRIVER_LOCK:
        _apply_point_poll_row(point_id=point_id, enabled=enabled, poll_interval_s=poll_interval_s)
    model_sync = _sync_poll_model(enabled)
    poll_trigger: dict[str, Any] | None = None
    if enabled:
        try:
            from .commission_client import commission_poll_once

            code, payload = commission_poll_once()
            poll_trigger = {"status_code": code, **(payload if isinstance(payload, dict) else {"detail": payload})}
        except Exception as exc:
            poll_trigger = {"ok": False, "error": str(exc)}
    return {
        "ok": True,
        "point_id": point_id,
        "enabled": enabled,
        "poll_interval_s": poll_interval_s if enabled else 0,
        "model_sync": model_sync,
        "poll_trigger": poll_trigger,
    }


def set_device_poll(*, device_instance: int, enabled: bool, poll_interval_s: int = 60) -> dict[str, Any]:
    tree = driver_tree()
    dev = next((d for d in tree["devices"] if int(d["device_instance"]) == device_instance), None)
    if dev is None:
        raise ValueError(f"device {device_instance} not in discovered inventory — run point discovery first")
    count = 0
    with _DRIVER_LOCK:
        for pt in dev["points"]:
            _apply_point_poll_row(point_id=pt["point_id"], enabled=enabled, poll_interval_s=poll_interval_s)
            count += 1
    model_sync = _sync_poll_model(enabled)
    poll_trigger: dict[str, Any] | None = None
    if enabled:
        try:
            from .commission_client import commission_poll_once

            code, payload = commission_poll_once()
            poll_trigger = {"status_code": code, **(payload if isinstance(payload, dict) else {"detail": payload})}
        except Exception as exc:
            poll_trigger = {"ok": False, "error": str(exc)}
    return {
        "ok": True,
        "device_instance": device_instance,
        "points_updated": count,
        "enabled": enabled,
        "model_sync": model_sync,
        "poll_trigger": poll_trigger,
    }


def delete_point(*, point_id: str) -> dict[str, Any]:
    with _DRIVER_LOCK:
        for path in (_discovered_path(), _points_path()):
            rows = [r for r in _load_csv(path) if r.get("point_id") != point_id]
            _save_csv(path, rows)
    return {"ok": True, "point_id": point_id}


def delete_device(*, device_instance: int) -> dict[str, Any]:
    inst = str(device_instance)
    with _DRIVER_LOCK:
        for path in (_discovered_path(), _points_path()):
            rows = [r for r in _load_csv(path) if str(r.get("device_instance") or "") != inst]
            _save_csv(path, rows)
    try:
        from .bacnet_poll_model_sync import remove_device_from_model

        model_sync = remove_device_from_model(device_instance=device_instance, sync_ttl=True)
    except Exception as exc:
        model_sync = {"ok": False, "error": str(exc)}
    return {"ok": True, "device_instance": device_instance, "model_sync": model_sync}


def _clear_poll_samples() -> None:
    from .paths import bacnet_poll_csv

    path = bacnet_poll_csv()
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "timestamp_utc",
        "site_id",
        "building_id",
        "system_id",
        "point_id",
        "series_id",
        "device_instance",
        "object_type",
        "object_instance",
        "value",
        "units",
    ]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()


def clear_registry(*, sync_model: bool = True, sync_ttl: bool = True) -> dict[str, Any]:
    """Wipe BACnet driver CSV registries and remove BACnet rows from the data model."""
    with _DRIVER_LOCK:
        _save_csv(_discovered_path(), [])
        _save_csv(_points_path(), [])
        _clear_poll_samples()
    model_result: dict[str, Any] | None = None
    if sync_model:
        from .bacnet_poll_model_sync import clear_bacnet_from_model

        model_result = clear_bacnet_from_model(sync_ttl=sync_ttl)
    return {
        "ok": True,
        "discovered_csv": str(_discovered_path()),
        "points_csv": str(_points_path()),
        "devices_cleared": True,
        "model": model_result,
    }


def remap_device(
    *,
    device_instance: int,
    new_device_instance: int | None = None,
    new_device_address: str | None = None,
) -> dict[str, Any]:
    """Change BACnet instance and/or address for all points on a device."""
    old_inst = str(device_instance)
    new_inst = str(new_device_instance if new_device_instance is not None else device_instance)
    if new_device_instance is not None and not (0 <= new_device_instance <= 4194303):
        raise ValueError("new_device_instance out of range")
    defaults = _commission_defaults()

    def _rewrite_rows(rows: list[dict[str, str]]) -> tuple[list[dict[str, str]], int]:
        out: list[dict[str, str]] = []
        count = 0
        for row in rows:
            if str(row.get("device_instance") or "") != old_inst:
                out.append(row)
                continue
            row = dict(row)
            if new_device_address is not None:
                row["device_address"] = new_device_address.strip()
            if new_inst != old_inst:
                obj_type = str(row.get("object_type") or "")
                obj_inst = str(row.get("object_instance") or "")
                row["device_instance"] = new_inst
                row["point_id"] = make_point_id(new_inst, obj_type, obj_inst)
                row["series_id"] = make_series_id(
                    row.get("site_id", defaults["site_id"]),
                    row.get("building_id", defaults["building_id"]),
                    row.get("system_id", "bacnet"),
                    row["point_id"],
                )
            row = normalize_row(row, defaults)
            out.append(row)
            count += 1
        return out, count

    with _DRIVER_LOCK:
        disc_out, points_updated = _rewrite_rows(_load_csv(_discovered_path()))
        if points_updated == 0:
            raise ValueError(f"device {device_instance} not found — add the device first")
        _save_csv(_discovered_path(), disc_out)
        poll_out, _ = _rewrite_rows(_load_csv(_points_path()))
        _save_csv(_points_path(), poll_out)
    return {
        "ok": True,
        "device_instance": int(new_inst),
        "previous_instance": int(old_inst),
        "device_address": new_device_address,
        "points_updated": points_updated,
    }
