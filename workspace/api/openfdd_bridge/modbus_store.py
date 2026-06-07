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
from .paths import modbus_poll_csv, modbus_registers_path, workspace_dir
from .site_defaults import ensure_default_site
from .model_service import ModelService
from .ttl_service import TtlService

_LOCK = threading.RLock()
_SAFE = re.compile(r"[^a-zA-Z0-9_-]+")
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
