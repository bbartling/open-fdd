"""Niagara station registry, point cache, and historian ingest."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from .feather_store import FeatherStore
from .paths import data_dir, niagara_points_cache_path, niagara_poll_csv, niagara_stations_path, workspace_dir
from .site_defaults import ensure_default_site
from .model_service import ModelService
from .ttl_service import TtlService

_LOCK = threading.RLock()
_SAFE = re.compile(r"[^a-zA-Z0-9_-]+")
_POLL_STATE: dict[str, dict[str, Any]] = {}
_POLL_ENABLED: dict[str, bool] = {}
_LAST_VALUES: dict[str, dict[str, Any]] = {}
_SAMPLES_HEADER = (
    "timestamp_utc,site_id,point_id,station_id,point_ord,point_name,value,status,source\n"
)

DEFAULT_STATION: dict[str, Any] = {
    "id": "",
    "name": "",
    "station_url": "",
    "username": "",
    "password_env": "OPENFDD_NIAGARA_ADMIN_PASSWORD",
    "verify_tls": False,
    "enabled": False,
    "root_ord": "slot:/Drivers",
    "poll_interval_seconds": 60,
    "read_batch_size": 50,
    "browse_depth": 4,
    "max_nodes": 2000,
    "include_patterns": [],
    "exclude_patterns": [],
    "default_points_root": "",
    "follow_external": False,
    "include_proxy_ext": False,
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _slug(text: str) -> str:
    s = _SAFE.sub("-", str(text or "").strip()).strip("-").lower()
    return s or "station"


def _default_site_id() -> str:
    try:
        return ensure_default_site(ModelService(), TtlService())
    except Exception:
        return "site"


def _ensure_dirs() -> None:
    (data_dir() / "niagara" / "points").mkdir(parents=True, exist_ok=True)
    (workspace_dir() / "niagara" / "polls").mkdir(parents=True, exist_ok=True)


def resolve_password(station: dict[str, Any]) -> str:
    env_name = str(station.get("password_env") or "OPENFDD_NIAGARA_ADMIN_PASSWORD").strip()
    return os.environ.get(env_name, "")


def make_point_id(station_id: str, point_ord: str) -> str:
    digest = hashlib.sha1(point_ord.encode("utf-8"), usedforsecurity=False).hexdigest()[:10]
    return f"niagara-{_slug(station_id)}-{digest}"


def _public_station(row: dict[str, Any]) -> dict[str, Any]:
    out = {**DEFAULT_STATION, **row}
    out.pop("password", None)
    if out.get("password_env"):
        out["password_configured"] = bool(resolve_password(out))
    else:
        out["password_configured"] = False
    return out


def list_stations() -> list[dict[str, Any]]:
    path = niagara_stations_path()
    if not path.is_file():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    rows = raw.get("stations") if isinstance(raw, dict) else raw
    if not isinstance(rows, list):
        return []
    return [_public_station(r) for r in rows if isinstance(r, dict)]


def get_station(station_id: str) -> dict[str, Any] | None:
    for row in list_stations():
        if str(row.get("id")) == station_id:
            return row
    return None


def _load_raw_stations() -> list[dict[str, Any]]:
    path = niagara_stations_path()
    if not path.is_file():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    rows = raw.get("stations") if isinstance(raw, dict) else raw
    return [dict(r) for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def _save_stations(rows: list[dict[str, Any]]) -> None:
    _ensure_dirs()
    path = niagara_stations_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = []
    for row in rows:
        item = {**row}
        item.pop("password", None)
        clean.append(item)
    path.write_text(json.dumps({"stations": clean}, indent=2), encoding="utf-8")


def validate_station_url(station_url: str) -> str:
    """Basic SSRF guard for Niagara station URLs (lab-safe)."""
    from urllib.parse import urlparse

    parsed = urlparse(station_url.strip())
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("station_url must use http or https")
    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError("station_url missing host")
    blocked = {"169.254.169.254", "metadata.google.internal", "localhost", "127.0.0.1", "::1"}
    if host in blocked and os.environ.get("OFDD_NIAGARA_ALLOW_LOCALHOST", "").lower() not in {"1", "true", "yes"}:
        raise ValueError(f"station_url host {host} is blocked (set OFDD_NIAGARA_ALLOW_LOCALHOST=1 for lab loopback)")
    return station_url.rstrip("/")


def upsert_station(payload: dict[str, Any]) -> dict[str, Any]:
    url = str(payload.get("station_url") or "").strip()
    if url:
        payload = {**payload, "station_url": validate_station_url(url)}
    sid = str(payload.get("id") or "").strip() or _slug(str(payload.get("name") or "station"))
    rows = _load_raw_stations()
    merged = {**DEFAULT_STATION, **payload, "id": sid}
    merged.pop("password", None)
    found = False
    for i, row in enumerate(rows):
        if str(row.get("id")) == sid:
            rows[i] = {**row, **merged}
            found = True
            break
    if not found:
        rows.append(merged)
    _save_stations(rows)
    return _public_station(merged)


def delete_station(station_id: str) -> bool:
    rows = _load_raw_stations()
    new_rows = [r for r in rows if str(r.get("id")) != station_id]
    if len(new_rows) == len(rows):
        return False
    _save_stations(new_rows)
    with _LOCK:
        _POLL_STATE.pop(station_id, None)
        _POLL_ENABLED.pop(station_id, None)
    cache = niagara_points_cache_path(station_id)
    if cache.is_file():
        cache.unlink()
    return True


def save_points_cache(station_id: str, points: list[dict[str, Any]]) -> None:
    _ensure_dirs()
    path = niagara_points_cache_path(station_id)
    path.write_text(json.dumps({"station_id": station_id, "points": points, "cached_at": _utc_now()}, indent=2), encoding="utf-8")


def load_points_cache(station_id: str) -> list[dict[str, Any]]:
    path = niagara_points_cache_path(station_id)
    if not path.is_file():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    pts = raw.get("points")
    return pts if isinstance(pts, list) else []


def matches_patterns(point: dict[str, Any], station: dict[str, Any]) -> bool:
    hay = " ".join(
        [
            str(point.get("point_ord") or ""),
            str(point.get("point_name") or ""),
            str(point.get("display_name") or ""),
        ]
    ).lower()
    includes = station.get("include_patterns") or []
    excludes = station.get("exclude_patterns") or []
    if includes:
        if not any(str(p).lower() in hay for p in includes):
            return False
    for pat in excludes:
        if str(pat).lower() in hay:
            return False
    return True


def set_poll_running(station_id: str, running: bool) -> dict[str, Any]:
    with _LOCK:
        _POLL_ENABLED[station_id] = running
        state = _POLL_STATE.setdefault(station_id, {})
        state["running"] = running
        if not running:
            state["connected"] = False
    return poll_status(station_id)


def update_poll_state(station_id: str, **fields: Any) -> None:
    with _LOCK:
        state = _POLL_STATE.setdefault(station_id, {})
        state.update(fields)


def poll_status(station_id: str | None = None) -> dict[str, Any]:
    with _LOCK:
        if station_id:
            st = _POLL_STATE.get(station_id, {})
            return {
                "station_id": station_id,
                "running": bool(_POLL_ENABLED.get(station_id)),
                "connected": bool(st.get("connected")),
                "last_success": st.get("last_success"),
                "last_error": st.get("last_error"),
                "active_points": int(st.get("active_points") or 0),
                "last_poll_duration_ms": int(st.get("last_poll_duration_ms") or 0),
                "batch_count": int(st.get("batch_count") or 0),
            }
        return {
            "stations": {
                sid: {
                    "running": bool(_POLL_ENABLED.get(sid)),
                    **(_POLL_STATE.get(sid) or {}),
                }
                for sid in set(list(_POLL_ENABLED.keys()) + list(_POLL_STATE.keys()))
            }
        }


def health_summary() -> dict[str, Any]:
    deps_ok = True
    deps_error = ""
    try:
        import aiohttp  # noqa: F401
        import msgpack  # noqa: F401
    except ImportError as exc:
        deps_ok = False
        deps_error = str(exc)
    return {
        "ok": True,
        "connector": "niagara_baskstream",
        "read_only": True,
        "dependencies_ok": deps_ok,
        "dependencies_error": deps_error,
        "station_count": len(list_stations()),
    }


def append_samples_and_ingest(
    samples: list[dict[str, Any]],
    *,
    site_id: str | None = None,
) -> dict[str, Any]:
    if not samples:
        return {"samples": 0, "ingested": 0}
    sid = site_id or _default_site_id()
    _ensure_dirs()
    path = niagara_poll_csv()
    new_file = not path.is_file()
    with path.open("a", newline="", encoding="utf-8") as fh:
        if new_file:
            fh.write(_SAMPLES_HEADER)
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "timestamp_utc",
                "site_id",
                "point_id",
                "station_id",
                "point_ord",
                "point_name",
                "value",
                "status",
                "source",
            ],
        )
        for row in samples:
            writer.writerow(row)

    df = pd.DataFrame(samples)
    df["timestamp"] = pd.to_datetime(df["timestamp_utc"], utc=True, errors="coerce")
    df = df.rename(columns={"point_id": "column"})
    df = df[["timestamp", "column", "value"]]
    store = FeatherStore()
    store.write_shard(df, source="niagara_baskstream", site_id=sid)
    return {"samples": len(samples), "ingested": len(samples), "feather_source": "niagara_baskstream", "site_id": sid}


def record_last_values(station_id: str, values: list[dict[str, Any]]) -> None:
    with _LOCK:
        bucket = _LAST_VALUES.setdefault(station_id, {})
        for row in values:
            bucket[str(row.get("point_ord") or "")] = row


def get_last_values(station_id: str) -> dict[str, dict[str, Any]]:
    with _LOCK:
        return dict(_LAST_VALUES.get(station_id) or {})


def driver_tree() -> dict[str, Any]:
    devices: list[dict[str, Any]] = []
    for station in list_stations():
        sid = str(station.get("id"))
        points = load_points_cache(sid)
        last = get_last_values(sid)
        pt_rows = []
        for pt in points:
            ord_value = str(pt.get("point_ord") or "")
            live = last.get(ord_value) or {}
            pt_rows.append(
                {
                    **pt,
                    "point_id": make_point_id(sid, ord_value),
                    "value": live.get("value"),
                    "status": live.get("status"),
                    "timestamp": live.get("timestamp"),
                }
            )
        devices.append(
            {
                "station_id": sid,
                "station_name": station.get("name"),
                "station_url": station.get("station_url"),
                "points": pt_rows,
            }
        )
    return {"devices": devices, "source": "niagara_baskstream"}
