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


def slim_overrides_for_llm(*, limit: int = 40) -> dict[str, Any]:
    """Compact override dump for Ollama / agent context."""
    op_pri = operator_override_priority()
    lines: list[dict[str, Any]] = []
    for alert in override_alerts(operator_only=False)[:limit]:
        meta = alert.get("meta") if isinstance(alert.get("meta"), dict) else {}
        lines.append(
            {
                "device": meta.get("device_instance"),
                "point": meta.get("object_name"),
                "oid": meta.get("object_identifier"),
                "priority": meta.get("priority_level"),
                "value": meta.get("value"),
                "operator_p8": bool(meta.get("operator_override")),
            }
        )
    return {
        "operator_priority": op_pri,
        "override_count": len(lines),
        "overrides": lines,
    }
