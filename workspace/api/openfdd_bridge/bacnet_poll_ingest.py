"""Convert long-format BACnet poll CSV → wide feather timeseries for Plot / FDD."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pandas as pd

from .feather_store import FeatherStore
from .model_service import ModelService
from .paths import bacnet_poll_csv
from .site_defaults import ensure_default_site
from .ttl_service import TtlService

_SAFE = re.compile(r"[^a-zA-Z0-9_-]+")


def _slug(text: str) -> str:
    s = _SAFE.sub("-", str(text or "").strip()).strip("-").lower()
    return s or "point"


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
    # 5007-analog-input-1168 → analog-input-1168
    parts = point_id.split("-", 1)
    return parts[1] if len(parts) == 2 else point_id


def _load_discovered_by_pid() -> dict[str, dict]:
    from .paths import workspace_dir

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


def ingest_poll_samples_to_feather(*, samples_path: Path | None = None) -> dict[str, Any]:
    path = samples_path or bacnet_poll_csv()
    if not path.is_file() or path.stat().st_size == 0:
        return {"ok": False, "reason": "no poll samples CSV", "path": str(path)}

    df = pd.read_csv(path)
    if df.empty or "point_id" not in df.columns:
        return {"ok": False, "reason": "empty or invalid poll CSV", "path": str(path)}

    model_svc = ModelService()
    ensure_default_site(model_svc, TtlService())
    model = model_svc.load()
    discovered = _load_discovered_by_pid()

    ts_col = "timestamp_utc" if "timestamp_utc" in df.columns else "timestamp"
    df[ts_col] = pd.to_datetime(df[ts_col], utc=True, errors="coerce")
    df = df.dropna(subset=[ts_col])

    store = FeatherStore()
    sites_written: dict[str, int] = {}

    for site_id, site_df in (
        df.groupby("site_id") if "site_id" in df.columns else [(ensure_default_site(model_svc, TtlService()), df)]
    ):
        sid = str(site_id).strip() or ensure_default_site(model_svc, TtlService())
        rows: list[dict[str, Any]] = []
        for ts, chunk in site_df.groupby(ts_col):
            row: dict[str, Any] = {"timestamp": ts, "site_id": sid}
            for _, rec in chunk.iterrows():
                pid = str(rec.get("point_id") or "")
                if not pid:
                    continue
                col = _column_for_point(pid, model, discovered)
                raw = rec.get("value")
                try:
                    row[col] = float(raw)
                except (TypeError, ValueError):
                    row[col] = raw
            rows.append(row)
        if not rows:
            continue
        wide = pd.DataFrame(rows).sort_values("timestamp")
        store.write_shard(wide, source="bacnet", site_id=sid)
        compact = store.compact(source="bacnet", site_id=sid)
        sites_written[sid] = int(compact.get("rows") or len(wide))

    return {
        "ok": True,
        "path": str(path),
        "sites": sites_written,
        "rows_long": int(len(df)),
    }
