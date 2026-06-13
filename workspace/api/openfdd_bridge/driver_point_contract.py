"""Unified driver point/value contract for BACnet, Niagara, Modbus, and JSON API."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

SOURCE_ALIASES = {
    "bacnet": "bacnet_direct",
    "bacnet_direct": "bacnet_direct",
    "niagara_baskstream": "niagara_baskstream",
    "modbus": "modbus",
    "json_api": "json_api",
}


def canonical_source(source: str) -> str:
    return SOURCE_ALIASES.get(str(source or "").strip(), str(source or ""))


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _coerce_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"true", "1", "active", "on"}:
        return True
    if text in {"false", "0", "inactive", "off"}:
        return False
    return None


def _coerce_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    m = re.match(r"^(-?\d+(?:\.\d+)?)", text)
    if m:
        return float(m.group(1))
    return None


def normalize_bacnet_point(row: dict[str, Any], *, source: str = "bacnet_direct") -> dict[str, Any]:
    point_id = str(row.get("point_id") or "")
    return {
        "source": canonical_source(source),
        "driver_id": str(row.get("device_instance") or ""),
        "equipment_id": str(row.get("equipment_id") or ""),
        "semantic_point_id": str(row.get("fdd_input") or row.get("external_id") or ""),
        "raw_point_id": point_id,
        "display_name": str(row.get("object_name") or point_id),
        "point_name": str(row.get("object_name") or ""),
        "point_path": str(row.get("object_identifier") or ""),
        "type": str(row.get("object_type") or ""),
        "units": str(row.get("units") or ""),
        "writable": bool(row.get("commandable")),
        "status": str(row.get("status") or "ok"),
        "ok": True,
        "last_seen": str(row.get("last_read_at") or row.get("timestamp") or ""),
        "tags": {"brick_type": row.get("brick_class") or row.get("brick_type")},
    }


def normalize_bacnet_value(
    *,
    point_id: str,
    value: Any,
    timestamp: str = "",
    status: str = "ok",
    units: str = "",
    semantic_point_id: str = "",
    source: str = "bacnet_direct",
) -> dict[str, Any]:
    return {
        "source": canonical_source(source),
        "point_id": point_id,
        "semantic_point_id": semantic_point_id,
        "timestamp": timestamp or _utc_now(),
        "value": value,
        "display_value": value,
        "quality": status,
        "status": status,
        "ok": status.lower() in {"", "ok", "{ok}"},
        "units": units,
        "poll_cycle_id": "",
        "ingested_at": _utc_now(),
    }


def normalize_niagara_point(row: dict[str, Any], *, source: str = "niagara_baskstream") -> dict[str, Any]:
    point_ord = str(row.get("point_ord") or "")
    return {
        "source": canonical_source(source),
        "driver_id": str(row.get("station_id") or ""),
        "equipment_id": str(row.get("device_ord") or ""),
        "semantic_point_id": str(row.get("semantic_point_id") or ""),
        "raw_point_id": str(row.get("point_id") or point_ord),
        "display_name": str(row.get("display_name") or row.get("point_name") or ""),
        "point_name": str(row.get("point_name") or ""),
        "point_path": point_ord,
        "type": str(row.get("type_spec") or row.get("value_type") or ""),
        "units": str(row.get("units") or ""),
        "writable": bool(row.get("writable")),
        "status": str(row.get("status") or ""),
        "ok": row.get("ok") if row.get("ok") is not None else True,
        "last_seen": str(row.get("timestamp") or row.get("discovered_at") or ""),
        "tags": {"kind": row.get("kind")},
    }


def normalize_niagara_value(
    row: dict[str, Any],
    *,
    semantic_point_id: str = "",
    source: str = "niagara_baskstream",
) -> dict[str, Any]:
    value = row.get("display_value")
    if value in (None, ""):
        value = row.get("value")
    status = str(row.get("status") or "")
    return {
        "source": canonical_source(source),
        "point_id": str(row.get("point_id") or row.get("point_ord") or ""),
        "semantic_point_id": semantic_point_id,
        "timestamp": str(row.get("timestamp") or _utc_now()),
        "value": value,
        "display_value": row.get("display_value") if row.get("display_value") not in (None, "") else value,
        "quality": status,
        "status": status,
        "ok": row.get("ok") if row.get("ok") is not None else ("ok" in status.lower()),
        "units": str(row.get("units") or ""),
        "poll_cycle_id": "",
        "ingested_at": _utc_now(),
    }


def normalize_modbus_point(row: dict[str, Any], *, source: str = "modbus") -> dict[str, Any]:
    point_id = str(row.get("point_id") or "")
    return {
        "source": canonical_source(source),
        "driver_id": f"{row.get('host')}:{row.get('port')}",
        "equipment_id": "",
        "semantic_point_id": str(row.get("label") or ""),
        "raw_point_id": point_id,
        "display_name": str(row.get("label") or point_id),
        "point_name": str(row.get("label") or ""),
        "point_path": f"{row.get('function')}@{row.get('address')}",
        "type": str(row.get("decode") or "register"),
        "units": str(row.get("units") or ""),
        "writable": False,
        "status": "ok",
        "ok": True,
        "last_seen": str(row.get("last_read_at") or ""),
        "tags": {},
    }


def normalize_json_api_point(row: dict[str, Any], *, source: str = "json_api") -> dict[str, Any]:
    point_id = str(row.get("point_id") or "")
    return {
        "source": canonical_source(source),
        "driver_id": str(row.get("host") or ""),
        "equipment_id": "",
        "semantic_point_id": str(row.get("label") or ""),
        "raw_point_id": point_id,
        "display_name": str(row.get("label") or point_id),
        "point_name": str(row.get("label") or ""),
        "point_path": str(row.get("url") or row.get("resource") or ""),
        "type": "rest_sensor",
        "units": str(row.get("units") or ""),
        "writable": False,
        "status": "ok",
        "ok": True,
        "last_seen": str(row.get("last_read_at") or ""),
        "tags": {"json_path": row.get("json_path")},
    }


def values_compatible(
    bacnet_value: dict[str, Any],
    niagara_value: dict[str, Any],
    *,
    kind: str = "numeric",
    tolerance: float = 1.0,
    timestamp_skew_s: float = 180.0,
) -> dict[str, Any]:
    """Compare normalized values; return per-point validation result."""
    result: dict[str, Any] = {
        "pass": False,
        "kind": kind,
        "bacnet": bacnet_value,
        "niagara": niagara_value,
        "abs_diff": None,
        "timestamp_skew_s": None,
        "stale_bacnet": False,
        "stale_niagara": False,
        "missing_bacnet": bacnet_value.get("value") in (None, ""),
        "missing_niagara": niagara_value.get("value") in (None, ""),
    }
    if result["missing_bacnet"] or result["missing_niagara"]:
        result["reason"] = "missing sample"
        return result

    if kind == "boolean":
        b = _coerce_bool(bacnet_value.get("value"))
        n = _coerce_bool(niagara_value.get("value"))
        result["pass"] = b is not None and n is not None and b == n
        result["reason"] = "boolean match" if result["pass"] else f"boolean mismatch {b} vs {n}"
        return result

    b_num = _coerce_float(bacnet_value.get("value"))
    n_num = _coerce_float(niagara_value.get("value"))
    if b_num is None or n_num is None:
        result["reason"] = "non-numeric value"
        return result
    diff = abs(b_num - n_num)
    result["abs_diff"] = diff
    result["pass"] = diff <= tolerance
    result["reason"] = "within tolerance" if result["pass"] else f"diff {diff:.3f} > {tolerance}"

    try:
        b_ts = datetime.fromisoformat(str(bacnet_value.get("timestamp", "")).replace("Z", "+00:00"))
        n_ts = datetime.fromisoformat(str(niagara_value.get("timestamp", "")).replace("Z", "+00:00"))
        skew = abs((b_ts - n_ts).total_seconds())
        result["timestamp_skew_s"] = skew
        if skew > timestamp_skew_s:
            result["stale_bacnet"] = b_ts < n_ts
            result["stale_niagara"] = n_ts < b_ts
    except (TypeError, ValueError):
        pass

    return result
