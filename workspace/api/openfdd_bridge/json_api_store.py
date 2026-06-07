"""JSON HTTP API endpoint registry + historian ingest (feather source=json_api)."""

from __future__ import annotations

import csv
import re
import threading
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import pandas as pd

from .feather_store import FeatherStore
from .json_api_service import execute_json_api_request
from .paths import json_api_endpoints_path, json_api_poll_csv, workspace_dir
from .site_defaults import ensure_default_site
from .model_service import ModelService
from .ttl_service import TtlService

_LOCK = threading.RLock()
_SAFE = re.compile(r"[^a-zA-Z0-9_-]+")
_ONDEMAND_VALUE: dict[str, str] = {}
_POLL_LAST_RUN: dict[str, float] = {}
_LAST_CYCLE: dict[str, Any] = {"at": "", "samples": 0, "error": ""}
POLL_INTERVALS_S = (60, 300, 600, 900)
POLL_LABELS = {60: "1 min", 300: "5 min", 600: "10 min", 900: "15 min"}
SAMPLES_HEADER = (
    "timestamp_utc,site_id,point_id,host,method,url,json_path,label,value,units\n"
)
REGISTRY_FIELDS = [
    "point_id",
    "url",
    "method",
    "json_path",
    "headers_json",
    "body_json",
    "label",
    "units",
    "enabled",
    "poll_interval_s",
    "last_value",
    "last_read_at",
]


def _slug(text: str) -> str:
    s = _SAFE.sub("-", str(text or "").strip()).strip("-").lower()
    return s or "endpoint"


def _default_site_id() -> str:
    try:
        return ensure_default_site(ModelService(), TtlService())
    except Exception:
        return "site"


def _ensure_dirs() -> None:
    (workspace_dir() / "json_api" / "polls").mkdir(parents=True, exist_ok=True)
    (workspace_dir() / "json_api" / "commissioning").mkdir(parents=True, exist_ok=True)


def _host_from_url(url: str) -> str:
    try:
        return urlparse(url).netloc or "unknown"
    except Exception:
        return "unknown"


def make_point_id(url: str, method: str, label: str) -> str:
    host = _host_from_url(url)
    return f"ja-{_slug(host)}-{_slug(method)}-{_slug(label)}"


def device_key(url: str) -> str:
    return _host_from_url(url)


def _load_endpoints() -> list[dict[str, Any]]:
    path = json_api_endpoints_path()
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        return [dict(row) for row in csv.DictReader(fh)]


def _save_endpoints(rows: list[dict[str, Any]]) -> None:
    _ensure_dirs()
    path = json_api_endpoints_path()
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=REGISTRY_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in REGISTRY_FIELDS})


def list_endpoints() -> dict[str, Any]:
    rows = _load_endpoints()
    enabled = sum(1 for r in rows if str(r.get("enabled", "")).lower() in {"1", "true", "yes"})
    return {"ok": True, "endpoints": rows, "count": len(rows), "enabled_count": enabled}


def record_ondemand_value(*, point_id: str, value: str) -> None:
    text = str(value or "").strip()
    if not text:
        return
    with _LOCK:
        _ONDEMAND_VALUE[point_id] = text


def _latest_poll_values() -> dict[str, str]:
    path = json_api_poll_csv()
    if not path.is_file():
        return {}
    latest: dict[str, tuple[str, str]] = {}
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip() or line.startswith("timestamp_utc"):
                continue
            parts = line.strip().split(",")
            if len(parts) < 10:
                continue
            pid, val, ts = parts[2], parts[9], parts[0]
            prev = latest.get(pid)
            if prev is None or ts >= prev[0]:
                latest[pid] = (ts, val)
    return {pid: val for pid, (_ts, val) in latest.items()}


def _present_value_for_point(*, point_id: str, enabled: bool, latest: dict[str, str], last_value: str) -> str:
    ondemand = _ONDEMAND_VALUE.get(point_id, "")
    polled = latest.get(point_id) or last_value or ""
    if enabled:
        return polled or ondemand
    return ondemand or polled


def upsert_endpoint(row: dict[str, Any]) -> dict[str, Any]:
    url = str(row.get("url") or "").strip()
    if not url:
        raise ValueError("url required")
    method = str(row.get("method") or "GET").strip().upper() or "GET"
    label = str(row.get("label") or "").strip() or str(row.get("json_path") or "value")
    pid = str(row.get("point_id") or "").strip() or make_point_id(url, method, label)
    interval = int(row.get("poll_interval_s") or 0)
    enabled = str(row.get("enabled", "")).lower() in {"1", "true", "yes"} or interval > 0
    entry = {
        "point_id": pid,
        "url": url,
        "method": method,
        "json_path": str(row.get("json_path") or ""),
        "headers_json": str(row.get("headers_json") or ""),
        "body_json": str(row.get("body_json") or ""),
        "label": label,
        "units": str(row.get("units") or ""),
        "enabled": "1" if enabled else "0",
        "poll_interval_s": str(interval if enabled else 0),
        "last_value": str(row.get("last_value") or ""),
        "last_read_at": str(row.get("last_read_at") or ""),
    }
    with _LOCK:
        rows = _load_endpoints()
        out = [r for r in rows if str(r.get("point_id")) != pid]
        out.append(entry)
        _save_endpoints(out)
    return {"ok": True, "endpoint": entry}


def set_endpoint_poll(*, point_id: str, enabled: bool, poll_interval_s: int) -> dict[str, Any]:
    with _LOCK:
        rows = _load_endpoints()
        found = False
        for row in rows:
            if str(row.get("point_id")) != point_id:
                continue
            found = True
            row["enabled"] = "1" if enabled else "0"
            row["poll_interval_s"] = str(poll_interval_s if enabled else 0)
        if not found:
            raise ValueError(f"unknown point_id: {point_id}")
        _save_endpoints(rows)
    return {"ok": True, "point_id": point_id, "enabled": enabled, "poll_interval_s": poll_interval_s}


def delete_endpoint(point_id: str) -> dict[str, Any]:
    with _LOCK:
        rows = _load_endpoints()
        kept = [r for r in rows if str(r.get("point_id")) != point_id]
        if len(kept) == len(rows):
            raise ValueError(f"unknown point_id: {point_id}")
        _save_endpoints(kept)
        _ONDEMAND_VALUE.pop(point_id, None)
    return {"ok": True, "point_id": point_id}


def _row_to_payload(row: dict[str, Any]) -> dict[str, Any]:
    import json as _json

    headers: dict[str, str] = {}
    raw_h = str(row.get("headers_json") or "").strip()
    if raw_h:
        try:
            parsed = _json.loads(raw_h)
            if isinstance(parsed, dict):
                headers = {str(k): str(v) for k, v in parsed.items()}
        except _json.JSONDecodeError:
            pass
    body = str(row.get("body_json") or "").strip() or None
    return {
        "url": str(row.get("url") or ""),
        "method": str(row.get("method") or "GET"),
        "json_path": str(row.get("json_path") or ""),
        "label": str(row.get("label") or ""),
        "headers": headers,
        "body": body,
        "timeout": 5.0,
    }


def driver_tree() -> dict[str, Any]:
    rows = _load_endpoints()
    latest = _latest_poll_values()
    devices: dict[str, dict[str, Any]] = {}
    for row in rows:
        url = str(row.get("url") or "")
        host = _host_from_url(url)
        key = device_key(url)
        method = str(row.get("method") or "GET")
        enabled = str(row.get("enabled", "")).lower() in {"1", "true", "yes"}
        try:
            interval = int(str(row.get("poll_interval_s") or "0"))
        except ValueError:
            interval = 0
        if enabled and interval not in POLL_INTERVALS_S:
            interval = 60
        pid = str(row.get("point_id") or "")
        label = str(row.get("label") or "")
        jpath = str(row.get("json_path") or "")
        dev = devices.setdefault(
            key,
            {"device_key": key, "host": host, "base_url": f"https://{host}" if host else key, "points": []},
        )
        dev["points"].append(
            {
                "point_id": pid,
                "label": label,
                "url": url,
                "method": method,
                "json_path": jpath,
                "object_type": method.lower(),
                "object_identifier": f"{method} {url}",
                "object_name": label,
                "enabled": enabled,
                "poll_interval_s": interval if enabled else 0,
                "poll_label": POLL_LABELS.get(interval, "") if enabled else "",
                "present_value": _present_value_for_point(
                    point_id=pid,
                    enabled=enabled,
                    latest=latest,
                    last_value=str(row.get("last_value") or ""),
                ),
                "units": str(row.get("units") or ""),
                "last_read_at": str(row.get("last_read_at") or ""),
            }
        )
    device_list = sorted(devices.values(), key=lambda d: d["host"])
    for dev in device_list:
        dev["point_count"] = len(dev["points"])
        dev["poll_count"] = sum(1 for p in dev["points"] if p["enabled"])
        dev["device_instance"] = dev["device_key"]
        dev["device_address"] = dev["host"]
    return {
        "ok": True,
        "devices": device_list,
        "poll_intervals": [{"seconds": s, "label": POLL_LABELS[s]} for s in POLL_INTERVALS_S],
        "endpoints_path": str(json_api_endpoints_path()),
    }


def _point_id_for_reading(reading: dict[str, Any]) -> str:
    url = str(reading.get("url") or "")
    method = str(reading.get("method") or "GET")
    label = str(reading.get("label") or "value")
    for row in _load_endpoints():
        if (
            str(row.get("url")) == url
            and str(row.get("method", "GET")).upper() == method.upper()
            and str(row.get("label") or "") == label
        ):
            return str(row.get("point_id") or "")
    return make_point_id(url, method, label)


def append_reading_and_ingest(*, reading: dict[str, Any], site_id: str | None = None) -> dict[str, Any]:
    if not reading.get("success"):
        return {"ok": False, "reason": reading.get("error") or "read_failed"}
    _ensure_dirs()
    sid = (site_id or _default_site_id()).strip() or _default_site_id()
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    path = json_api_poll_csv()
    if not path.is_file() or path.stat().st_size == 0:
        path.write_text(SAMPLES_HEADER, encoding="utf-8")

    url = str(reading.get("url") or "")
    method = str(reading.get("method") or "GET")
    label = str(reading.get("label") or "value")
    host = _host_from_url(url)
    pid = _point_id_for_reading(reading)
    value = reading.get("decoded")
    if value is None:
        value = reading.get("present_value")
    if value is None:
        return {"ok": False, "reason": "no value extracted"}
    col = _slug(label)
    val_text = str(value)

    with path.open("a", encoding="utf-8") as fh:
        fh.write(
            f"{ts},{sid},{pid},{host},{method},\"{url}\",{reading.get('json_path','')},"
            f"\"{label}\",{val_text},{''}\n"
        )

    store = FeatherStore()
    df = pd.DataFrame([{"timestamp": pd.Timestamp(ts), "site_id": sid, col: value}])
    store.write_shard(df, source="json_api", site_id=sid)

    with _LOCK:
        regs = _load_endpoints()
        for row in regs:
            if str(row.get("point_id")) == pid or (
                str(row.get("url")) == url and str(row.get("method")) == method and str(row.get("label")) == label
            ):
                row["last_value"] = val_text
                row["last_read_at"] = ts
        _save_endpoints(regs)

    return {
        "ok": True,
        "site_id": sid,
        "samples_appended": 1,
        "feather_source": "json_api",
        "poll_csv": str(path),
        "point_id": pid,
    }


def refresh_point(point_id: str, *, store: bool = False) -> dict[str, Any]:
    rows = _load_endpoints()
    row = next((r for r in rows if str(r.get("point_id")) == point_id), None)
    if not row:
        raise ValueError(f"unknown point_id: {point_id}")
    reading = execute_json_api_request(_row_to_payload(row))
    if not reading.get("success"):
        raise ValueError(str(reading.get("error") or "read_failed"))
    formatted = str(reading.get("present_value") or "")
    record_ondemand_value(point_id=point_id, value=formatted)
    out: dict[str, Any] = {
        "ok": True,
        "point_id": point_id,
        "value": reading.get("decoded"),
        "present_value": formatted,
        "status_code": reading.get("status_code"),
    }
    if store:
        out["ingest"] = append_reading_and_ingest(reading=reading)
    return out


def run_poll_cycle(*, force: bool = False) -> dict[str, Any]:
    import time as _time

    now = _time.monotonic()
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = _load_endpoints()
    due = []
    for row in rows:
        if str(row.get("enabled", "")).lower() not in {"1", "true", "yes"}:
            continue
        pid = str(row.get("point_id") or "")
        try:
            interval = max(1, int(str(row.get("poll_interval_s") or "60")))
        except ValueError:
            interval = 60
        last = _POLL_LAST_RUN.get(pid, 0.0)
        if force or (now - last) >= interval:
            due.append(row)
    if not due:
        _LAST_CYCLE.update({"at": ts, "samples": 0, "error": ""})
        return {"ok": True, "polled": 0, "samples": 0, "at": ts}

    total = 0
    errors: list[str] = []
    for row in due:
        pid = str(row.get("point_id") or "")
        try:
            reading = execute_json_api_request(_row_to_payload(row))
            if reading.get("success"):
                ingest = append_reading_and_ingest(reading=reading)
                if ingest.get("ok"):
                    total += 1
            else:
                errors.append(str(reading.get("error") or pid))
            _POLL_LAST_RUN[pid] = now
        except Exception as exc:
            errors.append(str(exc))
    err_text = "; ".join(errors[:3])
    _LAST_CYCLE.update({"at": ts, "samples": total, "error": err_text})
    return {"ok": not errors, "polled": len(due), "samples": total, "at": ts, "error": err_text}


def poll_status() -> dict[str, Any]:
    rows = _load_endpoints()
    enabled = [r for r in rows if str(r.get("enabled", "")).lower() in {"1", "true", "yes"}]
    intervals = []
    for r in enabled:
        try:
            intervals.append(int(str(r.get("poll_interval_s") or "60")))
        except ValueError:
            intervals.append(60)
    return {
        "ok": True,
        "enabled_points": len(enabled),
        "interval_s": float(min(intervals) if intervals else 0),
        "samples": int(_LAST_CYCLE.get("samples") or 0),
        "at": str(_LAST_CYCLE.get("at") or ""),
        "error": str(_LAST_CYCLE.get("error") or ""),
    }
