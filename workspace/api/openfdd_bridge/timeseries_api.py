"""Feather-store timeseries reads for the Plot tab (web_lambda-style multi-series)."""

from __future__ import annotations

from typing import Any

import pandas as pd

from .data_loader import load_site_frame
from .feather_store import FeatherStore
from .model_service import ModelService
from .site_defaults import ensure_default_site
from .ttl_service import TtlService


def list_plot_sites() -> list[dict[str, str]]:
    model = ModelService()
    ensure_default_site(model, TtlService())
    sites: dict[str, str] = {}
    for row in model.load().get("sites") or []:
        if isinstance(row, dict) and row.get("id"):
            sites[str(row["id"])] = str(row.get("name") or row["id"])
    for entry in FeatherStore().list_sites():
        sid = entry.get("site_id") or ""
        if sid and sid not in sites:
            sites[sid] = sid
    return [{"site_id": sid, "name": name} for sid, name in sorted(sites.items())]


def _numeric_columns(df: pd.DataFrame) -> list[str]:
    skip = {"timestamp", "site_id", "building_id", "system_id"}
    cols: list[str] = []
    for col in df.columns:
        if col in skip:
            continue
        if pd.api.types.is_numeric_dtype(df[col]):
            cols.append(str(col))
    return cols


def list_plot_series(site_id: str, *, source: str = "bacnet") -> dict[str, Any]:
    df = load_site_frame(site_id, source=source)
    model = ModelService().load()
    labels: dict[str, str] = {}
    for pt in model.get("points") or []:
        if not isinstance(pt, dict) or str(pt.get("site_id") or "") != site_id:
            continue
        ext = str(pt.get("external_id") or "").strip()
        if ext:
            labels[ext] = str(pt.get("description") or pt.get("brick_type") or ext)
    columns = _numeric_columns(df) if df is not None and not df.empty else []
    return {
        "site_id": site_id,
        "source": source,
        "columns": columns,
        "labels": labels,
        "row_count": int(len(df)) if df is not None else 0,
    }


def read_plot_series(
    site_id: str,
    columns: list[str],
    *,
    source: str = "bacnet",
    hours: int = 24,
    limit: int = 4000,
) -> dict[str, Any]:
    df = load_site_frame(site_id, source=source)
    if df is None or df.empty:
        return {"site_id": site_id, "series": {}, "hours": hours}
    if "timestamp" in df.columns:
        df = df.copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
        cutoff = pd.Timestamp.utcnow() - pd.Timedelta(hours=max(1, hours))
        df = df[df["timestamp"] >= cutoff]
    df = df.sort_values("timestamp") if "timestamp" in df.columns else df
    if limit and len(df) > limit:
        df = df.tail(limit)
    ts_col = df["timestamp"].astype(str).tolist() if "timestamp" in df.columns else list(range(len(df)))
    series: dict[str, list[float | None]] = {}
    for col in columns:
        if col not in df.columns:
            continue
        vals: list[float | None] = []
        for v in df[col].tolist():
            if v is None or (isinstance(v, float) and pd.isna(v)):
                vals.append(None)
            else:
                try:
                    vals.append(float(v))
                except (TypeError, ValueError):
                    vals.append(None)
        series[col] = vals
    return {"site_id": site_id, "timestamps": ts_col, "series": series, "hours": hours}
