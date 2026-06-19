"""Persist BACnet priority-array override scans (shared workspace volume)."""

from __future__ import annotations

import csv
import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bacnet_toolshed.paths import default_points_discovered, overrides_dir

_LOCK = threading.RLock()
_REGISTRY_VERSION = 1
_EXPORT_FIELDS = [
    "scanned_at_utc",
    "device_instance",
    "device_address",
    "object_identifier",
    "object_name",
    "priority_level",
    "value_type",
    "value",
    "operator_override",
]


def _registry_path() -> Path:
    return overrides_dir() / "registry.json"


def _export_path() -> Path:
    return overrides_dir() / "overrides_export.csv"


def operator_override_priority() -> int:
    raw = os.environ.get("OFDD_OPERATOR_OVERRIDE_PRIORITY", "8").strip()
    try:
        p = int(raw)
        return max(1, min(p, 16))
    except ValueError:
        return 8


def scan_interval_s() -> float:
    raw = os.environ.get("OFDD_OVERRIDE_SCAN_INTERVAL_S", "3600").strip()
    try:
        return max(300.0, float(raw))
    except ValueError:
        return 3600.0


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _empty_registry() -> dict[str, Any]:
    return {
        "version": _REGISTRY_VERSION,
        "scan_interval_s": scan_interval_s(),
        "operator_priority": operator_override_priority(),
        "cursor": 0,
        "last_scan_at": "",
        "last_scan_device": None,
        "last_error": "",
        "devices": {},
    }


def load_registry() -> dict[str, Any]:
    path = _registry_path()
    with _LOCK:
        if not path.is_file():
            return _empty_registry()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return _empty_registry()
    if not isinstance(data, dict):
        return _empty_registry()
    data.setdefault("devices", {})
    data.setdefault("cursor", 0)
    return data


def _save_registry(data: dict[str, Any]) -> None:
    overrides_dir().mkdir(parents=True, exist_ok=True)
    path = _registry_path()
    with _LOCK:
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def list_devices_for_scan() -> list[dict[str, Any]]:
    """Unique BACnet devices from points_discovered.csv (instance + address)."""
    path = default_points_discovered()
    if not path.is_file():
        return []
    seen: dict[str, dict[str, Any]] = {}
    try:
        with path.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                inst = str(row.get("device_instance") or "").strip()
                if not inst:
                    continue
                addr = str(row.get("device_address") or "").strip()
                prev = seen.get(inst)
                if prev is None or (not prev.get("device_address") and addr):
                    seen[inst] = {
                        "device_instance": int(inst),
                        "device_address": addr,
                    }
    except OSError:
        return []
    return sorted(seen.values(), key=lambda d: d["device_instance"])


def save_device_scan(scan: dict[str, Any]) -> None:
    """Merge one supervisory_logic_check result into registry + flat export CSV."""
    inst = scan.get("device_id") or scan.get("device_instance")
    if inst is None:
        return
    key = str(inst)
    entry = {
        "device_instance": int(inst),
        "device_address": str(scan.get("address") or ""),
        "scanned_at": _utc_now(),
        "ok": True,
        "error": "",
        "summary": scan.get("summary") or {},
        "points_with_overrides": scan.get("points_with_overrides") or [],
        "points": scan.get("points") or [],
    }
    with _LOCK:
        data = load_registry()
        data["devices"][key] = entry
        data["last_scan_at"] = entry["scanned_at"]
        data["last_scan_device"] = int(inst)
        data["last_error"] = ""
        data["scan_interval_s"] = scan_interval_s()
        data["operator_priority"] = operator_override_priority()
        _save_registry(data)
        _rewrite_export_csv(data)


def record_scan_error(*, device_instance: int, device_address: str, error: str) -> None:
    key = str(device_instance)
    with _LOCK:
        data = load_registry()
        data["devices"][key] = {
            "device_instance": device_instance,
            "device_address": device_address,
            "scanned_at": _utc_now(),
            "ok": False,
            "error": str(error)[:500],
            "summary": {},
            "points_with_overrides": [],
            "points": [],
        }
        data["last_scan_at"] = _utc_now()
        data["last_scan_device"] = device_instance
        data["last_error"] = str(error)[:500]
        _save_registry(data)


def advance_cursor(device_count: int) -> int:
    with _LOCK:
        data = load_registry()
        cur = int(data.get("cursor") or 0)
        nxt = (cur + 1) % max(device_count, 1)
        data["cursor"] = nxt
        _save_registry(data)
        return nxt


def scan_status() -> dict[str, Any]:
    data = load_registry()
    devices = list_devices_for_scan()
    n = len(devices)
    cursor = int(data.get("cursor") or 0)
    next_inst = None
    next_addr = ""
    if n:
        nxt = devices[cursor % n]
        next_inst = nxt["device_instance"]
        next_addr = nxt.get("device_address") or ""
    total_override_points = 0
    operator_override_points = 0
    op_pri = operator_override_priority()
    for dev in (data.get("devices") or {}).values():
        if not isinstance(dev, dict):
            continue
        for pt in dev.get("points_with_overrides") or []:
            if not isinstance(pt, dict):
                continue
            total_override_points += 1
            levels = pt.get("override_priority_levels") or []
            if op_pri in levels:
                operator_override_points += 1
    return {
        "ok": True,
        "scan_interval_s": scan_interval_s(),
        "operator_priority": op_pri,
        "device_count": n,
        "cursor": cursor,
        "full_rotation_hours": round(n * scan_interval_s() / 3600.0, 1) if n else 0,
        "last_scan_at": data.get("last_scan_at") or "",
        "last_scan_device": data.get("last_scan_device"),
        "last_error": data.get("last_error") or "",
        "next_device_instance": next_inst,
        "next_device_address": next_addr,
        "total_override_points": total_override_points,
        "operator_override_points": operator_override_points,
        "registry_path": str(_registry_path()),
        "export_path": str(_export_path()),
    }


def overrides_for_point(*, device_instance: int, object_identifier: str) -> list[dict[str, Any]]:
    data = load_registry()
    dev = (data.get("devices") or {}).get(str(device_instance))
    if not isinstance(dev, dict):
        return []
    oid = str(object_identifier or "").strip().lower()
    for pt in dev.get("points_with_overrides") or []:
        if not isinstance(pt, dict):
            continue
        if str(pt.get("object_identifier") or "").strip().lower() == oid:
            return list(pt.get("overrides") or [])
    return []


def overrides_by_device() -> dict[str, dict[str, Any]]:
    data = load_registry()
    out: dict[str, dict[str, Any]] = {}
    for key, dev in (data.get("devices") or {}).items():
        if isinstance(dev, dict):
            out[str(key)] = dev
    return out


def _rewrite_export_csv(data: dict[str, Any]) -> None:
    path = _export_path()
    op_pri = operator_override_priority()
    rows: list[dict[str, str]] = []
    for dev in sorted((data.get("devices") or {}).values(), key=lambda d: int(d.get("device_instance") or 0)):
        if not isinstance(dev, dict):
            continue
        scanned = str(dev.get("scanned_at") or "")
        inst = str(dev.get("device_instance") or "")
        addr = str(dev.get("device_address") or "")
        for pt in dev.get("points_with_overrides") or []:
            if not isinstance(pt, dict):
                continue
            oid = str(pt.get("object_identifier") or "")
            name = str(pt.get("object_name") or "")
            for slot in pt.get("overrides") or []:
                if not isinstance(slot, dict):
                    continue
                pl = int(slot.get("priority_level") or 0)
                rows.append(
                    {
                        "scanned_at_utc": scanned,
                        "device_instance": inst,
                        "device_address": addr,
                        "object_identifier": oid,
                        "object_name": name,
                        "priority_level": str(pl),
                        "value_type": str(slot.get("type") or ""),
                        "value": str(slot.get("value") or ""),
                        "operator_override": "1" if pl == op_pri else "0",
                    }
                )
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_EXPORT_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def export_csv_text() -> str:
    path = _export_path()
    if not path.is_file():
        _rewrite_export_csv(load_registry())
    if not path.is_file():
        return ",".join(_EXPORT_FIELDS) + "\n"
    return path.read_text(encoding="utf-8")


def override_alerts(*, operator_only: bool = False) -> list[dict[str, Any]]:
    """Dashboard alerts for BACnet priority-array overrides."""
    data = load_registry()
    op_pri = operator_override_priority()
    alerts: list[dict[str, Any]] = []
    for dev in sorted((data.get("devices") or {}).values(), key=lambda d: int(d.get("device_instance") or 0)):
        if not isinstance(dev, dict) or not dev.get("ok", True):
            continue
        inst = int(dev.get("device_instance") or 0)
        addr = str(dev.get("device_address") or "")
        for pt in dev.get("points_with_overrides") or []:
            if not isinstance(pt, dict):
                continue
            oid = str(pt.get("object_identifier") or "")
            name = str(pt.get("object_name") or oid)
            for slot in pt.get("overrides") or []:
                if not isinstance(slot, dict):
                    continue
                pl = int(slot.get("priority_level") or 0)
                if operator_only and pl != op_pri:
                    continue
                val = slot.get("value")
                val_s = str(val) if val is not None else "—"
                title = f"OVERRIDE device {inst} {name} @ P{pl} = {val_s}"
                alerts.append(
                    {
                        "id": f"bacnet-override-{inst}-{oid.replace(',', '-')}-p{pl}",
                        "severity": "warning" if pl == op_pri else "info",
                        "title": title,
                        "detail": (
                            f"BACnet priority-array slot P{pl} is written on {name} ({oid}) "
                            f"at {addr or 'unknown address'}. "
                            + (
                                "Operator manual level (P8) — verify intentional override."
                                if pl == op_pri
                                else "Supervisory/other priority — may be BAS automation."
                            )
                        ),
                        "source": "bacnet_override",
                        "equipment_family": "OVERRIDE",
                        "equipment_id": str(inst),
                        "equipment_name": f"Device {inst}",
                        "meta": {
                            "device_instance": inst,
                            "device_address": addr,
                            "object_identifier": oid,
                            "object_name": name,
                            "priority_level": pl,
                            "value": val,
                            "operator_override": pl == op_pri,
                        },
                    }
                )
    return alerts


def _parse_iso_utc(value: str) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def assess_override_scan_health(status: dict[str, Any] | None = None) -> dict[str, Any]:
    """Whether the hourly BACnet override rotation is running as expected."""
    status = status if isinstance(status, dict) else scan_status()
    interval = float(status.get("scan_interval_s") or scan_interval_s())
    device_count = int(status.get("device_count") or 0)
    last_error = str(status.get("last_error") or "").strip()
    last_scan_at = str(status.get("last_scan_at") or "").strip()
    stale_threshold_s = max(interval * 2.0, 7200.0)

    age_s: float | None = None
    parsed = _parse_iso_utc(last_scan_at)
    if parsed is not None:
        age_s = max(0.0, (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds())

    base = {
        "scan_interval_s": interval,
        "stale_threshold_s": stale_threshold_s,
        "last_scan_age_s": round(age_s, 1) if age_s is not None else None,
        "device_count": device_count,
        "last_scan_at": last_scan_at,
        "last_scan_device": status.get("last_scan_device"),
        "last_error": last_error,
        "cursor": int(status.get("cursor") or 0),
        "full_rotation_hours": status.get("full_rotation_hours"),
    }

    if device_count < 1:
        return {
            **base,
            "ok": False,
            "status": "no_devices",
            "detail": "No BACnet devices in override scan rotation (points_discovered.csv).",
        }

    if last_error and (age_s is None or age_s > interval):
        return {
            **base,
            "ok": False,
            "status": "error",
            "detail": f"Last supervisory scan failed: {last_error[:160]}",
        }

    if age_s is None:
        return {
            **base,
            "ok": False,
            "status": "stale",
            "detail": "Override scan has not completed yet — waiting for first hourly cycle.",
        }

    if age_s > stale_threshold_s:
        hours = int(age_s // 3600)
        return {
            **base,
            "ok": False,
            "status": "stale",
            "detail": f"Last override scan {hours}h ago (expected within {int(stale_threshold_s // 3600)}h).",
        }

    minutes = max(1, int(age_s // 60))
    last_dev = status.get("last_scan_device")
    dev_note = f" · device {last_dev}" if last_dev is not None else ""
    return {
        **base,
        "ok": True,
        "status": "healthy",
        "detail": f"Hourly override scan active — last run {minutes}m ago{dev_note}.",
    }


def _iter_override_rows(*, operator_only: bool = False) -> list[dict[str, Any]]:
    """Flatten registry overrides with device + scan metadata."""
    data = load_registry()
    op_pri = operator_override_priority()
    rows: list[dict[str, Any]] = []
    for dev in sorted((data.get("devices") or {}).values(), key=lambda d: int(d.get("device_instance") or 0)):
        if not isinstance(dev, dict) or not dev.get("ok", True):
            continue
        inst = int(dev.get("device_instance") or 0)
        addr = str(dev.get("device_address") or "")
        scanned_at = str(dev.get("scanned_at") or "")
        for pt in dev.get("points_with_overrides") or []:
            if not isinstance(pt, dict):
                continue
            oid = str(pt.get("object_identifier") or "")
            name = str(pt.get("object_name") or oid)
            for slot in pt.get("overrides") or []:
                if not isinstance(slot, dict):
                    continue
                pl = int(slot.get("priority_level") or 0)
                if operator_only and pl != op_pri:
                    continue
                val = slot.get("value")
                rows.append(
                    {
                        "device_instance": inst,
                        "device_address": addr,
                        "device_label": f"Device {inst}",
                        "object_identifier": oid,
                        "object_name": name,
                        "priority_level": pl,
                        "value": val,
                        "value_text": str(val) if val is not None else "—",
                        "operator_override": pl == op_pri,
                        "scanned_at": scanned_at,
                    }
                )
    return rows


def override_dashboard_summary(*, preview_limit: int = 8) -> dict[str, Any]:
    """Structured BACnet override payload for building summary + RCx."""
    status = scan_status()
    health = assess_override_scan_health(status)
    operator_rows = _iter_override_rows(operator_only=True)
    all_rows = _iter_override_rows(operator_only=False)

    by_device_map: dict[str, dict[str, Any]] = {}
    for row in all_rows:
        key = str(row["device_instance"])
        bucket = by_device_map.setdefault(
            key,
            {
                "device_instance": row["device_instance"],
                "device_address": row["device_address"],
                "device_label": row["device_label"],
                "operator_override_count": 0,
                "total_override_count": 0,
                "last_scanned_at": row.get("scanned_at") or "",
                "scan_ok": True,
                "points": [],
            },
        )
        bucket["total_override_count"] += 1
        if row.get("operator_override"):
            bucket["operator_override_count"] += 1
        if row.get("scanned_at"):
            bucket["last_scanned_at"] = str(row["scanned_at"])
        bucket["points"].append(row)

    by_device = sorted(by_device_map.values(), key=lambda d: (-int(d["operator_override_count"]), int(d["device_instance"])))

    return {
        "ok": True,
        "scan": status,
        "scan_health": health,
        "operator_priority": status.get("operator_priority") or operator_override_priority(),
        "operator_override_points": len(operator_rows),
        "total_override_points": len(all_rows),
        "preview_limit": preview_limit,
        "preview_total": len(operator_rows),
        "preview": operator_rows[: max(0, preview_limit)],
        "by_device": by_device,
        "overrides": operator_rows,
    }


def slim_overrides_for_llm(*, limit: int = 40) -> dict[str, Any]:
    """Compact override dump for Ollama / agent context."""
    op_pri = operator_override_priority()
    status = scan_status()
    health = assess_override_scan_health(status)
    lines: list[dict[str, Any]] = []
    for row in _iter_override_rows(operator_only=False)[:limit]:
        lines.append(
            {
                "device": row.get("device_instance"),
                "device_instance": row.get("device_instance"),
                "device_address": row.get("device_address"),
                "point": row.get("object_name"),
                "object": row.get("object_name"),
                "oid": row.get("object_identifier"),
                "object_id": row.get("object_identifier"),
                "priority": row.get("priority_level"),
                "value": row.get("value"),
                "operator_p8": bool(row.get("operator_override")),
                "scanned_at": row.get("scanned_at"),
            }
        )
    p8_rows = [r for r in lines if r.get("operator_p8")]
    return {
        "operator_priority": op_pri,
        "override_count": len(p8_rows),
        "operator_override_points": len(p8_rows),
        "total_override_points": len(lines),
        "overrides": lines,
        "p8_overrides": p8_rows[:limit],
        "scan": status,
        "scan_health": health,
    }
