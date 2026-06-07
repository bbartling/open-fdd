"""Modbus register registry + historian ingest (feather source=modbus)."""

from __future__ import annotations

import csv
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .feather_store import FeatherStore
from .paths import modbus_poll_csv, modbus_registers_path, repo_root, workspace_dir
from .site_defaults import ensure_default_site
from .model_service import ModelService
from .ttl_service import TtlService

_LOCK = threading.RLock()
_SAFE = re.compile(r"[^a-zA-Z0-9_-]+")
# On-demand refresh values (shown when polling disabled until next sample).
_ONDEMAND_VALUE: dict[str, str] = {}
_POLL_LAST_RUN: dict[str, float] = {}
_LAST_CYCLE: dict[str, Any] = {"at": "", "samples": 0, "error": ""}
POLL_INTERVALS_S = (60, 300, 600, 900)
POLL_LABELS = {60: "1 min", 300: "5 min", 600: "10 min", 900: "15 min"}
SAMPLES_HEADER = (
    "timestamp_utc,site_id,point_id,host,unit_id,address,function,label,value,units\n"
)


def _slug(text: str) -> str:
    s = _SAFE.sub("-", str(text or "").strip()).strip("-").lower()
    return s or "register"


def _default_site_id() -> str:
    try:
        return ensure_default_site(ModelService(), TtlService())
    except Exception:
        return "site"


def _ensure_dirs() -> None:
    (workspace_dir() / "modbus" / "polls").mkdir(parents=True, exist_ok=True)
    (workspace_dir() / "modbus" / "commissioning").mkdir(parents=True, exist_ok=True)


def _load_registers() -> list[dict[str, Any]]:
    path = modbus_registers_path()
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        return [dict(row) for row in csv.DictReader(fh)]


def _save_registers(rows: list[dict[str, Any]]) -> None:
    _ensure_dirs()
    path = modbus_registers_path()
    fields = [
        "point_id",
        "host",
        "port",
        "unit_id",
        "address",
        "function",
        "count",
        "decode",
        "scale",
        "offset",
        "label",
        "units",
        "enabled",
        "poll_interval_s",
        "last_value",
        "last_read_at",
    ]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fields})


def make_point_id(host: str, unit_id: int, address: int, function: str) -> str:
    return f"mb-{_slug(host)}-u{unit_id}-{function}-{_slug(str(address))}"


def device_key(host: str, port: str | int, unit_id: str | int) -> str:
    return f"{host}:{port}:u{unit_id}"


def record_ondemand_value(*, point_id: str, value: str) -> None:
    text = str(value or "").strip()
    if not text:
        return
    with _LOCK:
        _ONDEMAND_VALUE[point_id] = text


def _latest_poll_values() -> dict[str, str]:
    path = modbus_poll_csv()
    if not path.is_file():
        return {}
    latest: dict[str, tuple[str, str]] = {}
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip() or line.startswith("timestamp_utc"):
                continue
            parts = line.strip().split(",")
            if len(parts) < 9:
                continue
            pid, val, ts = parts[2], parts[8], parts[0]
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


def _row_read_spec(row: dict[str, Any]) -> dict[str, Any]:
    scale = str(row.get("scale") or "").strip()
    offset = str(row.get("offset") or "").strip()
    decode = str(row.get("decode") or "uint16").strip() or "uint16"
    return {
        "host": str(row.get("host") or ""),
        "port": int(row.get("port") or 502),
        "unit_id": int(row.get("unit_id") or 1),
        "timeout": 5.0,
        "registers": [
            {
                "address": int(row.get("address") or 0),
                "count": int(row.get("count") or 1),
                "function": str(row.get("function") or "holding"),
                "decode": None if decode == "raw" else decode,
                "scale": float(scale) if scale else None,
                "offset": float(offset) if offset else None,
                "label": str(row.get("label") or ""),
            }
        ],
    }


def modbus_bench_hint_available() -> bool:
    """True when local dev fake Modbus server script is present (hide on production edge images)."""
    return (repo_root() / "scripts" / "fake_modbus_temp_server.py").is_file()


def driver_tree() -> dict[str, Any]:
    rows = _load_registers()
    latest = _latest_poll_values()
    devices: dict[str, dict[str, Any]] = {}
    for row in rows:
        host = str(row.get("host") or "")
        port = str(row.get("port") or "502")
        unit = str(row.get("unit_id") or "1")
        key = device_key(host, port, unit)
        enabled = str(row.get("enabled", "")).lower() in {"1", "true", "yes"}
        try:
            interval = int(str(row.get("poll_interval_s") or "0"))
        except ValueError:
            interval = 0
        if enabled and interval not in POLL_INTERVALS_S:
            interval = 60
        pid = str(row.get("point_id") or "")
        fn = str(row.get("function") or "holding")
        addr = str(row.get("address") or "0")
        dev = devices.setdefault(
            key,
            {
                "device_key": key,
                "host": host,
                "port": port,
                "unit_id": unit,
                "points": [],
            },
        )
        dev["points"].append(
            {
                "point_id": pid,
                "label": str(row.get("label") or f"reg_{addr}"),
                "register_address": addr,
                "function": fn,
                "object_type": fn,
                "object_identifier": f"{fn}@{addr}",
                "object_name": str(row.get("label") or f"reg_{addr}"),
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
    device_list = sorted(devices.values(), key=lambda d: (d["host"], d["port"], d["unit_id"]))
    for dev in device_list:
        dev["point_count"] = len(dev["points"])
        dev["poll_count"] = sum(1 for p in dev["points"] if p["enabled"])
        dev["device_instance"] = dev["device_key"]
        dev["device_address"] = f"{dev['host']}:{dev['port']} unit {dev['unit_id']}"
    return {
        "ok": True,
        "devices": device_list,
        "poll_intervals": [{"seconds": s, "label": POLL_LABELS[s]} for s in POLL_INTERVALS_S],
        "registers_path": str(modbus_registers_path()),
        "bench_hint_available": modbus_bench_hint_available(),
    }


def delete_register(point_id: str) -> dict[str, Any]:
    with _LOCK:
        rows = _load_registers()
        kept = [r for r in rows if str(r.get("point_id")) != point_id]
        if len(kept) == len(rows):
            raise ValueError(f"unknown point_id: {point_id}")
        _save_registers(kept)
        _ONDEMAND_VALUE.pop(point_id, None)
    return {"ok": True, "point_id": point_id}


def refresh_point(point_id: str, *, store: bool = False) -> dict[str, Any]:
    from .modbus_service import execute_modbus_read_request

    rows = _load_registers()
    row = next((r for r in rows if str(r.get("point_id")) == point_id), None)
    if not row:
        raise ValueError(f"unknown point_id: {point_id}")
    payload = _row_read_spec(row)
    result = execute_modbus_read_request(payload)
    reading = (result.get("readings") or [{}])[0]
    if not reading.get("success"):
        raise ValueError(str(reading.get("error") or "read_failed"))
    decoded = reading.get("decoded")
    if decoded is None and reading.get("words"):
        decoded = (reading.get("words") or [None])[0]
    formatted = "—" if decoded is None else str(decoded)
    record_ondemand_value(point_id=point_id, value=formatted)
    out: dict[str, Any] = {
        "ok": True,
        "point_id": point_id,
        "value": decoded,
        "present_value": formatted,
    }
    if store:
        ingest = append_samples_and_ingest(
            host=payload["host"],
            unit_id=int(payload["unit_id"]),
            readings=result.get("readings") or [],
        )
        out["ingest"] = ingest
    return out


def run_poll_cycle(*, force: bool = False) -> dict[str, Any]:
    """Read all enabled registers whose poll interval has elapsed."""
    from .modbus_service import execute_modbus_read_request

    with _LOCK:
        return _run_poll_cycle_locked(execute_modbus_read_request, force=force)


def _run_poll_cycle_locked(execute_modbus_read_request, *, force: bool = False) -> dict[str, Any]:
    import time as _time

    now = _time.monotonic()
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = _load_registers()
    due: list[dict[str, Any]] = []
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

    groups: dict[str, list[dict[str, Any]]] = {}
    for row in due:
        key = device_key(row.get("host", ""), row.get("port", "502"), row.get("unit_id", "1"))
        groups.setdefault(key, []).append(row)

    total_samples = 0
    errors: list[str] = []
    for _key, group in groups.items():
        sample_row = group[0]
        host = str(sample_row.get("host") or "")
        port = int(sample_row.get("port") or 502)
        unit_id = int(sample_row.get("unit_id") or 1)
        reg_specs = []
        for row in group:
            scale = str(row.get("scale") or "").strip()
            offset = str(row.get("offset") or "").strip()
            decode = str(row.get("decode") or "uint16").strip() or "uint16"
            reg_specs.append(
                {
                    "address": int(row.get("address") or 0),
                    "count": int(row.get("count") or 1),
                    "function": str(row.get("function") or "holding"),
                    "decode": None if decode == "raw" else decode,
                    "scale": float(scale) if scale else None,
                    "offset": float(offset) if offset else None,
                    "label": str(row.get("label") or ""),
                }
            )
        try:
            result = execute_modbus_read_request(
                {
                    "host": host,
                    "port": port,
                    "unit_id": unit_id,
                    "timeout": 5.0,
                    "registers": reg_specs,
                }
            )
            ingest = append_samples_and_ingest(
                host=host,
                unit_id=unit_id,
                readings=result.get("readings") or [],
            )
            if ingest.get("ok"):
                total_samples += int(ingest.get("samples_appended") or 0)
            for row in group:
                _POLL_LAST_RUN[str(row.get("point_id") or "")] = now
        except Exception as exc:
            errors.append(str(exc))

    err_text = "; ".join(errors[:3])
    _LAST_CYCLE.update({"at": ts, "samples": total_samples, "error": err_text})
    return {
        "ok": not errors,
        "polled": len(due),
        "samples": total_samples,
        "at": ts,
        "error": err_text,
    }


def poll_status() -> dict[str, Any]:
    rows = _load_registers()
    enabled = [
        r
        for r in rows
        if str(r.get("enabled", "")).lower() in {"1", "true", "yes"}
    ]
    intervals = []
    for r in enabled:
        try:
            intervals.append(int(str(r.get("poll_interval_s") or "60")))
        except ValueError:
            intervals.append(60)
    interval_s = min(intervals) if intervals else 0.0
    return {
        "ok": True,
        "enabled_points": len(enabled),
        "interval_s": float(interval_s),
        "samples": int(_LAST_CYCLE.get("samples") or 0),
        "at": str(_LAST_CYCLE.get("at") or ""),
        "error": str(_LAST_CYCLE.get("error") or ""),
    }


def list_registers() -> dict[str, Any]:
    rows = _load_registers()
    enabled = sum(1 for r in rows if str(r.get("enabled", "")).lower() in {"1", "true", "yes"})
    return {"ok": True, "registers": rows, "count": len(rows), "enabled_count": enabled}


def upsert_register(row: dict[str, Any]) -> dict[str, Any]:
    host = str(row.get("host") or "").strip()
    if not host:
        raise ValueError("host required")
    unit_id = int(row.get("unit_id") or 1)
    address = int(row.get("address") or 0)
    function = str(row.get("function") or "holding").strip() or "holding"
    pid = str(row.get("point_id") or "").strip() or make_point_id(host, unit_id, address, function)
    interval = int(row.get("poll_interval_s") or 0)
    enabled = str(row.get("enabled", "")).lower() in {"1", "true", "yes"} or interval > 0
    entry = {
        "point_id": pid,
        "host": host,
        "port": str(row.get("port") or "502"),
        "unit_id": str(unit_id),
        "address": str(address),
        "function": function,
        "count": str(row.get("count") or "1"),
        "decode": str(row.get("decode") or "uint16"),
        "scale": str(row.get("scale") or ""),
        "offset": str(row.get("offset") or ""),
        "label": str(row.get("label") or f"reg_{address}"),
        "units": str(row.get("units") or ""),
        "enabled": "1" if enabled else "0",
        "poll_interval_s": str(interval if enabled else 0),
        "last_value": str(row.get("last_value") or ""),
        "last_read_at": str(row.get("last_read_at") or ""),
    }
    with _LOCK:
        rows = _load_registers()
        out = [r for r in rows if str(r.get("point_id")) != pid]
        out.append(entry)
        _save_registers(out)
    return {"ok": True, "register": entry}


def set_register_poll(*, point_id: str, enabled: bool, poll_interval_s: int) -> dict[str, Any]:
    with _LOCK:
        rows = _load_registers()
        found = False
        for row in rows:
            if str(row.get("point_id")) != point_id:
                continue
            found = True
            row["enabled"] = "1" if enabled else "0"
            row["poll_interval_s"] = str(poll_interval_s if enabled else 0)
        if not found:
            raise ValueError(f"unknown point_id: {point_id}")
        _save_registers(rows)
    return {"ok": True, "point_id": point_id, "enabled": enabled, "poll_interval_s": poll_interval_s}


def append_samples_and_ingest(
    *,
    host: str,
    unit_id: int,
    readings: list[dict[str, Any]],
    site_id: str | None = None,
) -> dict[str, Any]:
    """Append long-format Modbus samples and write a feather shard (source=modbus)."""
    _ensure_dirs()
    sid = (site_id or _default_site_id()).strip() or _default_site_id()
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    path = modbus_poll_csv()
    if not path.is_file() or path.stat().st_size == 0:
        path.write_text(SAMPLES_HEADER, encoding="utf-8")

    wide_row: dict[str, Any] = {"timestamp": pd.Timestamp(ts), "site_id": sid}
    long_rows: list[dict[str, Any]] = []
    stored = 0

    for item in readings:
        if not item.get("success"):
            continue
        address = int(item.get("address") or 0)
        function = str(item.get("function") or "holding")
        label = str(item.get("label") or f"reg_{address}")
        pid = make_point_id(host, unit_id, address, function)
        value = item.get("decoded")
        if value is None and item.get("words"):
            words = item.get("words") or []
            value = words[0] if words else None
        if value is None:
            continue
        col = _slug(label)
        wide_row[col] = value
        long_rows.append(
            {
                "timestamp_utc": ts,
                "site_id": sid,
                "point_id": pid,
                "host": host,
                "unit_id": unit_id,
                "address": address,
                "function": function,
                "label": label,
                "value": value,
                "units": str(item.get("units") or ""),
            }
        )
        stored += 1

    if not long_rows:
        return {"ok": False, "reason": "no successful readings"}

    with path.open("a", encoding="utf-8") as fh:
        for row in long_rows:
            fh.write(
                f"{row['timestamp_utc']},{row['site_id']},{row['point_id']},"
                f"{row['host']},{row['unit_id']},{row['address']},{row['function']},"
                f"\"{row['label']}\",{row['value']},{row['units']}\n"
            )

    store = FeatherStore()
    df = pd.DataFrame([wide_row])
    store.write_shard(df, source="modbus", site_id=sid)

    # Update registry last_value
    with _LOCK:
        regs = _load_registers()
        for row in regs:
            for lr in long_rows:
                if str(row.get("point_id")) == lr["point_id"]:
                    row["last_value"] = str(lr["value"])
                    row["last_read_at"] = ts
        _save_registers(regs)

    return {
        "ok": True,
        "site_id": sid,
        "samples_appended": stored,
        "feather_source": "modbus",
        "poll_csv": str(path),
    }
