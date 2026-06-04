"""Convert long-format BACnet poll CSV → wide feather timeseries for Plot / FDD."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

import pandas as pd

from .bacnet_value_convert import convert_poll_value, load_convert_context, profile_for_sample
from .feather_store import FeatherStore, maintain_storage_if_needed
from .model_service import ModelService
from .paths import bacnet_poll_csv, data_dir, workspace_dir
from .site_defaults import ensure_default_site
from .ttl_service import TtlService

_log = logging.getLogger(__name__)
_SAFE = re.compile(r"[^a-zA-Z0-9_-]+")

_INGEST_STATE_NAME = "bacnet_ingest_state.json"
_COLUMN_CACHE: dict[str, Any] = {"model_mtime": 0.0, "map": {}}
_MAINTAIN_COUNTER = 0


def _slug(text: str) -> str:
    s = _SAFE.sub("-", str(text or "").strip()).strip("-").lower()
    return s or "point"


def _ingest_state_path() -> Path:
    return data_dir() / _INGEST_STATE_NAME


def _load_ingest_state() -> dict[str, Any]:
    path = _ingest_state_path()
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _save_ingest_state(state: dict[str, Any]) -> None:
    path = _ingest_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _tail_csv_lines(path: Path, *, max_data_rows: int) -> list[str]:
    """Read header + last N data rows without loading the full poll CSV."""
    if not path.is_file() or path.stat().st_size == 0:
        return []
    need = max(1, max_data_rows) + 1
    block = 256 * 1024
    with path.open("rb") as fh:
        fh.seek(0, os.SEEK_END)
        pos = fh.tell()
        chunks: list[bytes] = []
        while pos > 0 and sum(c.count(b"\n") for c in chunks) < need + 2:
            read_size = min(block, pos)
            pos -= read_size
            fh.seek(pos)
            chunks.insert(0, fh.read(read_size))
    text = b"".join(chunks).decode("utf-8", errors="replace")
    lines = text.splitlines()
    if not lines:
        return []
    header = lines[0]
    data = lines[1:]
    if len(data) <= max_data_rows:
        return [header, *data]
    return [header, *data[-max_data_rows:]]


def _read_poll_csv_incremental(
    path: Path,
    *,
    max_tail_rows: int,
    since_ts: pd.Timestamp | None,
) -> pd.DataFrame:
    """Load recent poll rows only (tail of append-only CSV)."""
    lines = _tail_csv_lines(path, max_data_rows=max_tail_rows)
    if len(lines) < 2:
        return pd.DataFrame()
    from io import StringIO

    df = pd.read_csv(StringIO("\n".join(lines)))
    if df.empty or "point_id" not in df.columns:
        return df
    ts_col = "timestamp_utc" if "timestamp_utc" in df.columns else "timestamp"
    if ts_col not in df.columns:
        return df
    df[ts_col] = pd.to_datetime(df[ts_col], utc=True, errors="coerce")
    df = df.dropna(subset=[ts_col])
    if since_ts is not None and not df.empty:
        df = df[df[ts_col] > since_ts]
    return df


def _max_tail_rows() -> int:
    raw = os.environ.get("OFDD_POLL_INGEST_TAIL_ROWS", "").strip()
    try:
        return max(400, int(raw))
    except ValueError:
        return max(400, _env_enabled_points_hint() * 3)


def _env_enabled_points_hint() -> int:
    raw = os.environ.get("OFDD_POLL_INGEST_ENABLED_HINT", "400").strip()
    try:
        return max(50, int(raw))
    except ValueError:
        return 400


def _column_for_point(point_id: str, model: dict[str, Any], discovered: dict[str, dict]) -> str:
    for pt in model.get("points") or []:
        if not isinstance(pt, dict):
            continue
        if str(pt.get("id") or "") == point_id or str(pt.get("metadata", {}).get("point_id") or "") == point_id:
            ext = str(pt.get("external_id") or "").strip()
            if ext:
                return ext
            fdd = str(pt.get("fdd_input") or "").strip()
            if fdd:
                return fdd
    disc = discovered.get(point_id) or {}
    name = str(disc.get("object_name") or disc.get("description") or "").strip()
    if name:
        return _slug(name)
    parts = point_id.split("-", 1)
    return parts[1] if len(parts) == 2 else point_id


def _build_column_map(model: dict[str, Any], discovered: dict[str, dict]) -> dict[str, str]:
    model_path = data_dir() / "model.json"
    mtime = model_path.stat().st_mtime if model_path.is_file() else 0.0
    if _COLUMN_CACHE.get("model_mtime") == mtime and _COLUMN_CACHE.get("map"):
        return _COLUMN_CACHE["map"]
    out: dict[str, str] = {}
    for pt in model.get("points") or []:
        if not isinstance(pt, dict):
            continue
        pid = str(pt.get("id") or pt.get("metadata", {}).get("point_id") or "").strip()
        if pid:
            out[pid] = _column_for_point(pid, model, discovered)
    for pid in discovered:
        if pid not in out:
            out[pid] = _column_for_point(pid, model, discovered)
    _COLUMN_CACHE["model_mtime"] = mtime
    _COLUMN_CACHE["map"] = out
    return out


def _load_discovered_by_pid() -> dict[str, dict]:
    path = workspace_dir() / "bacnet" / "commissioning" / "points_discovered.csv"
    if not path.is_file():
        return {}
    import csv

    out: dict[str, dict] = {}
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            pid = str(row.get("point_id") or "").strip()
            if pid:
                out[pid] = dict(row)
    return out


def _wide_rows_for_chunk(
    site_df: pd.DataFrame,
    ts_col: str,
    sid: str,
    column_map: dict[str, str],
    discovered: dict[str, dict],
    device_profiles: dict,
    point_profiles: dict,
    device_ranges: dict,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for ts, chunk in site_df.groupby(ts_col):
        row: dict[str, Any] = {"timestamp": ts, "site_id": sid}
        for _, rec in chunk.iterrows():
            pid = str(rec.get("point_id") or "")
            if not pid:
                continue
            col = column_map.get(pid) or _column_for_point(pid, {}, discovered)
            raw = rec.get("value")
            units = str(rec.get("units") or discovered.get(pid, {}).get("units") or "")
            inst = str(rec.get("device_instance") or discovered.get(pid, {}).get("device_instance") or "")
            profile = profile_for_sample(
                point_id=pid,
                device_instance=inst,
                device_profiles=device_profiles,
                point_profiles=point_profiles,
                device_profile_ranges=device_ranges,
            )
            try:
                num = float(raw)
                num, _units_out = convert_poll_value(num, units=units, profile=profile)
                row[col] = num
            except (TypeError, ValueError):
                row[col] = raw
        rows.append(row)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("timestamp")


def _should_run_storage_maintain() -> bool:
    global _MAINTAIN_COUNTER  # noqa: PLW0603
    every = max(1, int(os.environ.get("OFDD_FEATHER_MAINTAIN_EVERY_N", "12") or 12))
    _MAINTAIN_COUNTER += 1
    return _MAINTAIN_COUNTER % every == 0


def ingest_poll_samples_to_feather(*, samples_path: Path | None = None, force_full: bool = False) -> dict[str, Any]:
    path = samples_path or bacnet_poll_csv()
    if not path.is_file() or path.stat().st_size == 0:
        return {"ok": False, "reason": "no poll samples CSV", "path": str(path)}

    state = _load_ingest_state()
    since_raw = str(state.get("last_timestamp_utc") or "").strip()
    since_ts: pd.Timestamp | None = None
    if since_raw and not force_full:
        try:
            since_ts = pd.Timestamp(since_raw)
            if since_ts.tzinfo is None:
                since_ts = since_ts.tz_localize("UTC")
        except (TypeError, ValueError):
            since_ts = None

    tail_rows = _max_tail_rows() if not force_full else 0
    if force_full:
        df = pd.read_csv(path)
    else:
        df = _read_poll_csv_incremental(path, max_tail_rows=tail_rows, since_ts=since_ts)

    if df.empty or "point_id" not in df.columns:
        if since_ts is not None:
            return {"ok": True, "skipped": True, "reason": "no new poll rows", "path": str(path)}
        return {"ok": False, "reason": "empty or invalid poll CSV", "path": str(path)}

    model_svc = ModelService()
    ensure_default_site(model_svc, TtlService())
    model = model_svc.load()
    discovered = _load_discovered_by_pid()
    column_map = _build_column_map(model, discovered)
    commission_dir = workspace_dir() / "bacnet" / "commissioning"
    device_profiles, point_profiles, device_ranges = load_convert_context(commission_dir)

    ts_col = "timestamp_utc" if "timestamp_utc" in df.columns else "timestamp"
    df[ts_col] = pd.to_datetime(df[ts_col], utc=True, errors="coerce")
    df = df.dropna(subset=[ts_col])

    store = FeatherStore()
    sites_written: dict[str, int] = {}
    shards_written = 0
    max_ts: pd.Timestamp | None = None

    for site_id, site_df in (
        df.groupby("site_id") if "site_id" in df.columns else [(ensure_default_site(model_svc, TtlService()), df)]
    ):
        sid = str(site_id).strip() or ensure_default_site(model_svc, TtlService())
        wide = _wide_rows_for_chunk(
            site_df,
            ts_col,
            sid,
            column_map,
            discovered,
            device_profiles,
            point_profiles,
            device_ranges,
        )
        if wide.empty:
            continue
        site_max = wide["timestamp"].max()
        if max_ts is None or site_max > max_ts:
            max_ts = site_max
        store.write_shard(wide, source="bacnet", site_id=sid)
        shards_written += 1
        sites_written[sid] = int(len(wide))
        store.maybe_compact_after_ingest(source="bacnet", site_id=sid)

    if max_ts is not None:
        _save_ingest_state(
            {
                "last_timestamp_utc": max_ts.isoformat(),
                "last_ingest_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "csv_mtime": path.stat().st_mtime,
                "csv_size": path.stat().st_size,
            }
        )

    storage_trim = maintain_storage_if_needed(store) if _should_run_storage_maintain() else None

    return {
        "ok": True,
        "path": str(path),
        "sites": sites_written,
        "rows_long": int(len(df)),
        "shards_written": shards_written,
        "incremental": not force_full,
        "storage_trim": storage_trim,
    }
