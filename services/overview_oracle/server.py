#!/usr/bin/env python3
"""Vibe 19 Overview analytics oracle for React parity.

Serves the same pandas + Plotly figures Streamlit Overview uses
(``open_fdd.analytics`` / ``agent_api.run_analytics``), keyed by building_id.

  PYTHONPATH=services/ui:. .venv/bin/uvicorn services.overview_oracle.server:app --host 0.0.0.0 --port 8099
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Resolve repo roots whether launched as module or script.
_REPO = Path(__file__).resolve().parents[2]
_UI = _REPO / "services" / "ui"
import sys

for p in (str(_UI), str(_REPO)):
    if p not in sys.path:
        sys.path.insert(0, p)

from app.agent_api import load_package_path, run_analytics  # noqa: E402
from open_fdd.analytics.charts import (  # noqa: E402
    bas_vs_web_oat_histogram,
    bas_vs_web_oat_overlay,
    economizer_delta_scatter,
    economizer_mat_residual_chart,
    economizer_temps_overlay,
    equipment_inspection_chart,
    format_mech_cooling_coverage_display,
    mech_cooling_oat_histogram,
    motor_weekly_runtime_chart,
)
from open_fdd.analytics.core import (  # noqa: E402
    dataset_time_span,
    economizer_free_cooling_diagnostics,
)

app = FastAPI(title="Open-FDD Overview Oracle (Vibe 19)", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_LOCK = threading.Lock()
_CACHE: dict[str, dict[str, Any]] = {}

PLANT_CHART_META: tuple[tuple[str, str, str], ...] = (
    ("air", "Air side — supply fans", "AHU supply fan status preferred over command."),
    (
        "boiler",
        "Boiler plant — HW pumps",
        "One series per HW pump (status preferred over command).",
    ),
    (
        "chiller",
        "Chiller plant — chillers, CHW/CW pumps, towers",
        "Chiller plant prefers mapped pump status; if no pump, falls back to "
        "chiller_status / compressor_status / equipment_enable — never leave-temp fake runtime.",
    ),
)

DEFAULT_PACKAGES = {
    "BUILDING_100": Path(
        os.environ.get(
            "OPENFDD_BUILDING_100_ZIP",
            "/home/ben/raw_BUILDING_100_openfdd.zip",
        )
    ),
    "BUILDING_50": Path(
        os.environ.get(
            "OPENFDD_BUILDING_50_ZIP",
            "/home/ben/raw_BUILDING_50_openfdd.zip",
        )
    ),
}


def _fig_json(fig: Any) -> dict[str, Any] | None:
    if fig is None:
        return None
    try:
        payload = json.loads(fig.to_json())
    except Exception:
        payload = fig.to_plotly_json()  # type: ignore[assignment]
    if isinstance(payload, dict):
        layout = payload.get("layout")
        if isinstance(layout, dict):
            layout.pop("template", None)
    return payload  # type: ignore[return-value]


def _df_records(df: pd.DataFrame | None, limit: int | None = None) -> list[dict[str, Any]]:
    if df is None or getattr(df, "empty", True):
        return []
    out = df.copy()
    for col in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[col]):
            out[col] = out[col].astype(str)
    if isinstance(out.index, pd.DatetimeIndex):
        out = out.reset_index()
        if "index" in out.columns:
            out = out.rename(columns={"index": "timestamp"})
    if limit is not None:
        out = out.head(limit)
    # NaN → null
    return json.loads(out.to_json(orient="records", date_format="iso"))


def _resolve_package(building_id: str) -> Path:
    bid = (building_id or "").strip()
    if not bid:
        raise HTTPException(400, "building_id required")
    env_map = os.environ.get("OPENFDD_OVERVIEW_PACKAGE_MAP")
    if env_map:
        try:
            mapped = json.loads(env_map)
            if bid in mapped:
                p = Path(mapped[bid]).expanduser()
                if p.exists():
                    return p
        except json.JSONDecodeError:
            pass
    if bid in DEFAULT_PACKAGES and DEFAULT_PACKAGES[bid].exists():
        return DEFAULT_PACKAGES[bid]
    # workspace csv_buildings (may lack valid package manifest — prefer zip)
    folder = _REPO / "workspace" / "data" / "csv_buildings" / bid
    if folder.is_dir() and (folder / "manifest.json").is_file():
        # Only use if zip missing; loader may reject non-v1 manifests
        return folder
    # raw zip next to home
    cand = Path(f"/home/ben/raw_{bid}_openfdd.zip")
    if cand.exists():
        return cand
    raise HTTPException(
        404,
        f"No package path for building_id={bid!r}. "
        "Set OPENFDD_BUILDING_100_ZIP or OPENFDD_OVERVIEW_PACKAGE_MAP.",
    )


def _get_dataset(building_id: str) -> Any:
    path = _resolve_package(building_id)
    key = f"{building_id}::{path}::{path.stat().st_mtime_ns if path.exists() else 0}"
    with _LOCK:
        hit = _CACHE.get(key)
        if hit and hit.get("dataset") is not None:
            return hit["dataset"]
    t0 = time.time()
    ds = load_package_path(path)
    with _LOCK:
        _CACHE[key] = {"dataset": ds, "loaded_at": time.time(), "load_s": time.time() - t0, "path": str(path)}
        # drop other keys for same building
        for k in list(_CACHE):
            if k.startswith(f"{building_id}::") and k != key:
                _CACHE.pop(k, None)
    return ds


class OverviewRequest(BaseModel):
    building_id: str
    bare_min_occ_hours_week: float | None = Field(default=None)
    prefer_web_oat: bool = True
    chw_leave_max_f: float = 48.0
    use_mech_cooling_status_proof: bool = True
    oat_err: float = 5.0
    econ_overlay_equipment_id: str | None = None


@app.get("/api/overview-oracle/health")
def health() -> dict[str, Any]:
    return {"ok": True, "service": "overview-oracle", "repo": str(_REPO)}


@app.post("/api/overview-oracle/vibe19")
def overview_vibe19(body: OverviewRequest) -> dict[str, Any]:
    """Full Vibe 19 Overview analytics + Plotly figures for one building."""
    t0 = time.time()
    ds = _get_dataset(body.building_id)
    span = dataset_time_span(ds.frames)
    analytics = run_analytics(
        ds,
        params={
            "prefer_web_oat": body.prefer_web_oat,
            "chw_leave_max_f": body.chw_leave_max_f,
            "use_mech_cooling_status_proof": body.use_mech_cooling_status_proof,
        },
    )
    weekly: pd.DataFrame = analytics["motor_weekly"]
    bare = body.bare_min_occ_hours_week
    plant_figs: list[dict[str, Any]] = []
    for plant, title, caption in PLANT_CHART_META:
        sub = (
            weekly.loc[weekly["plant_group"] == plant]
            if weekly is not None and not weekly.empty and "plant_group" in weekly.columns
            else weekly.iloc[0:0]
        )
        fig = motor_weekly_runtime_chart(
            sub,
            title=title,
            min_hours_line=bare if plant == "air" else None,
            show_avg_oat=True,
        )
        plant_figs.append(
            {
                "plant_group": plant,
                "title": title,
                "caption": caption,
                "figure": _fig_json(fig),
                "empty": fig is None,
            }
        )

    cool_bins = analytics["mech_cooling_oat_bins"]
    cool_cov = analytics["mech_cooling_coverage"]
    cool_fig = mech_cooling_oat_histogram(cool_bins)
    try:
        cov_display = format_mech_cooling_coverage_display(cool_cov)
    except Exception:
        cov_display = cool_cov

    econ_tbl = analytics["economizer_weather"]
    fc = economizer_free_cooling_diagnostics(
        ds.frames,
        ds.role_map,
        weather=ds.weather,
        prefer_web_oat=body.prefer_web_oat,
    )
    econ_pts = fc.get("points")
    econ_metrics = fc.get("metrics")
    delta_fig = economizer_delta_scatter(
        econ_pts, dt_min_f=float(fc.get("dt_min_f") or 10.0)
    )
    resid_fig = economizer_mat_residual_chart(econ_pts)
    overlay_eq = body.econ_overlay_equipment_id
    if not overlay_eq and econ_metrics is not None and not getattr(econ_metrics, "empty", True):
        overlay_eq = str(econ_metrics["equipment_id"].iloc[0])
    temps_fig = economizer_temps_overlay(econ_pts, equipment_id=overlay_eq)

    bas_overlay = bas_vs_web_oat_overlay(
        ds.frames, ds.role_map, weather=ds.weather, oat_err=body.oat_err
    )
    bas_hist = bas_vs_web_oat_histogram(
        ds.frames, ds.role_map, weather=ds.weather
    )

    # devices by type
    type_counts: dict[str, int] = {}
    for eq_id, frame in ds.frames.items():
        et = str(getattr(frame, "attrs", {}).get("equipment_type") or "unknown")
        type_counts[et] = type_counts.get(et, 0) + 1
    devices = [
        {"type": k, "count": v}
        for k, v in sorted(type_counts.items(), key=lambda kv: kv[0])
    ]

    start = span.get("start")
    end = span.get("end")
    return {
        "ok": True,
        "building_id": body.building_id,
        "source": "vibe19-pandas-oracle",
        "elapsed_s": round(time.time() - t0, 2),
        "equipment_count": len(ds.frames),
        "equipment_ids": sorted(ds.frames.keys()),
        "has_weather": ds.weather is not None and not getattr(ds.weather, "empty", True),
        "span": {
            "start": None if start is None else str(start),
            "end": None if end is None else str(end),
            "span_hours": span.get("span_hours"),
        },
        "motor_weekly": {
            "caption": (
                "Bars = run hours by week (Mon start). Dotted line = avg OAT °F while "
                "that motor was on. Chiller plant prefers pump status, then "
                "chiller/compressor enable (no leave-temp fake hours). Air side: "
                "dashed orange = bare-min occupied hours/week from the building schedule."
            ),
            "plants": plant_figs,
            "table": _df_records(weekly, limit=5000),
        },
        "mech_cooling": {
            "caption": (
                "Chillers / DX / VRF use compressor-proof mode. Never CHW cooling valves. "
                "Bins sorted cold→hot; OAT from web weather by default. Stacked bars are "
                "per-device runtime; line traces are total compressor device-hours and any "
                "compressor active."
            ),
            "figure": _fig_json(cool_fig),
            "bins": _df_records(cool_bins, limit=5000),
            "coverage": _df_records(cov_display, limit=5000),
            "n_included": int(
                cool_cov["included"].fillna(False).astype(bool).sum()
            )
            if cool_cov is not None
            and not cool_cov.empty
            and "included" in cool_cov.columns
            else None,
            "n_excluded": int(
                (~cool_cov["included"].fillna(False).astype(bool)).sum()
            )
            if cool_cov is not None
            and not cool_cov.empty
            and "included" in cool_cov.columns
            else None,
        },
        "economizer_weather": {
            "caption": (
                "Strict web dry-bulb + dewpoint. Opportunity = 60≤DB<72°F and DP<60°F. "
                "Integrated hours = cooling-valve + OA damper ≥90%. Prohibited cooling = "
                "compressor proof below 60°F."
            ),
            "table": _df_records(econ_tbl, limit=500),
        },
        "economizer_free_cooling": {
            "caption": (
                "Guideline 36–aligned mixing plots for AHU/RTU while the supply fan is "
                "running. Delta scatter uses (x = OAT−RAT, y = MAT−RAT); |OAT−RAT|<10°F "
                "suppressed. MAT residual vs damper mixing model."
            ),
            "metrics": _df_records(econ_metrics, limit=200),
            "delta_scatter": _fig_json(delta_fig),
            "mat_residual": _fig_json(resid_fig),
            "temps_overlay": _fig_json(temps_fig),
            "overlay_equipment_id": overlay_eq,
            "skipped": fc.get("skipped") or [],
            "dt_min_f": fc.get("dt_min_f"),
        },
        "bas_vs_web_oat": {
            "caption": (
                f"Overlay of BAS OAT and web dry-bulb with ±{body.oat_err}°F tolerance "
                "band (OAT-METEO). Histogram of BAS − web deviation in the expander."
            ),
            "overlay": _fig_json(bas_overlay),
            "histogram": _fig_json(bas_hist),
            "oat_err": body.oat_err,
        },
        "devices_by_type": devices,
    }


class InspectRequest(BaseModel):
    building_id: str
    equipment_id: str
    columns: list[str] | None = None


@app.post("/api/overview-oracle/inspect")
def overview_inspect(body: InspectRequest) -> dict[str, Any]:
    ds = _get_dataset(body.building_id)
    eq = body.equipment_id
    if eq == "(weather)":
        df = ds.weather
        label = "weather"
        if df is None or getattr(df, "empty", True):
            raise HTTPException(404, "No weather frame for this building")
    else:
        if eq not in ds.frames:
            raise HTTPException(404, f"Unknown equipment_id={eq!r}")
        df = ds.frames[eq]
        label = eq

    numeric_cols: list[str] = []
    for c in df.columns:
        s = df[c]
        if pd.api.types.is_bool_dtype(s) or pd.api.types.is_numeric_dtype(s):
            numeric_cols.append(str(c))
        else:
            coerced = pd.to_numeric(s, errors="coerce")
            if coerced.notna().sum() >= max(1, int(0.5 * len(s))):
                numeric_cols.append(str(c))
    show = body.columns if body.columns else numeric_cols
    show = [c for c in show if c in numeric_cols]
    fig = equipment_inspection_chart(df, equipment_id=label, columns=show) if show else None
    span = ""
    first = last = None
    if isinstance(df.index, pd.DatetimeIndex) and len(df.index):
        first, last = str(df.index.min()), str(df.index.max())
        span = f"{first} → {last}"
    return {
        "ok": True,
        "equipment_id": label,
        "row_count": int(len(df)),
        "plottable_columns": numeric_cols,
        "columns_plotted": show,
        "first_timestamp": first,
        "last_timestamp": last,
        "span": span,
        "figure": _fig_json(fig),
        "csv_preview": _df_records(df.reset_index().head(50)),
    }


@app.get("/api/overview-oracle/inspect/meta")
def inspect_meta(
    building_id: str = Query(...),
    equipment_id: str = Query(...),
) -> dict[str, Any]:
    ds = _get_dataset(building_id)
    options = sorted(ds.frames.keys())
    if ds.weather is not None and not getattr(ds.weather, "empty", True):
        options = options + ["(weather)"]
    eq = equipment_id if equipment_id in options else (options[0] if options else "")
    if eq == "(weather)":
        df = ds.weather
    else:
        df = ds.frames.get(eq)
    cols: list[str] = []
    if df is not None:
        for c in df.columns:
            s = df[c]
            if pd.api.types.is_bool_dtype(s) or pd.api.types.is_numeric_dtype(s):
                cols.append(str(c))
            else:
                coerced = pd.to_numeric(s, errors="coerce")
                if coerced.notna().sum() >= max(1, int(0.5 * len(s))):
                    cols.append(str(c))
    return {
        "ok": True,
        "options": options,
        "equipment_id": eq,
        "plottable_columns": cols,
        "row_count": 0 if df is None else int(len(df)),
    }
