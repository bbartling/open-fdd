"""Plot readings with optional FDD fault overlays (web_lambda-style)."""

from __future__ import annotations

from typing import Any

import pandas as pd

from . import playground
from .data_loader import load_site_frame
from .fdd_row_prep import prepare_fdd_rows
from .feather_store import FeatherStore
from .model_service import ModelService
from .rule_source import read_source
from .rule_store import RuleStore
from .site_defaults import ensure_default_site
from .timeseries_api import _numeric_columns, column_kinds_for_site, list_plot_sites, list_plot_series
from .ttl_service import TtlService

CHART_MAX_POINTS = 4000
FAULT_COLORS = ("#f85149", "#d29922", "#58a6ff", "#3fb950", "#a371f7", "#ffa657", "#ff7b72", "#79c0ff")


def chart_sample_indices(n: int, max_pts: int) -> list[int]:
    if n <= 0:
        return []
    if n <= max_pts:
        return list(range(n))
    stride = max(1, (n + max_pts - 2) // (max_pts - 1))
    idx = list(range(0, n, stride))
    if idx[-1] != n - 1:
        idx.append(n - 1)
    return idx[:max_pts]


def downsample_aligned_plot(
    n: int,
    max_pts: int,
    timestamps: list[str],
    series: dict[str, list[float | None]],
    fault_plots: dict[str, list[int]],
) -> tuple[list[str], dict[str, list[float | None]], dict[str, list[int]], int, bool]:
    if n <= max_pts:
        return timestamps, series, fault_plots, 1, False
    idx = chart_sample_indices(n, max_pts)
    out_ts = [timestamps[i] for i in idx]
    out_series = {k: [vals[i] for i in idx] for k, vals in series.items()}
    out_faults = {k: [flags[i] for i in idx] for k, flags in fault_plots.items()}
    stride = max(1, n // max(len(idx) - 1, 1))
    return out_ts, out_series, out_faults, stride, True


def chart_guides_from_rules(rules: list[dict[str, Any]]) -> dict[str, float | None]:
    low: float | None = None
    high: float | None = None
    low_rh: float | None = None
    high_rh: float | None = None
    for rule in rules:
        cfg = rule.get("config") if isinstance(rule.get("config"), dict) else {}
        if cfg.get("bounds_low") is not None:
            low = float(cfg["bounds_low"])
        if cfg.get("bounds_high") is not None:
            high = float(cfg["bounds_high"])
        if cfg.get("bounds_low_rh") is not None:
            low_rh = float(cfg["bounds_low_rh"])
        if cfg.get("bounds_high_rh") is not None:
            high_rh = float(cfg["bounds_high_rh"])
    out: dict[str, float | None] = {}
    if low is not None:
        out["bounds_low"] = low
    if high is not None:
        out["bounds_high"] = high
    if low_rh is not None:
        out["bounds_low_rh"] = low_rh
    if high_rh is not None:
        out["bounds_high_rh"] = high_rh
    return out


def _rule_code(rule: dict[str, Any]) -> str:
    path = str(rule.get("source_path") or "")
    if path:
        disk = read_source(path)
        if disk.strip():
            return disk
    return str(rule.get("code") or "")


def evaluate_fault_plots(
    df: pd.DataFrame,
    site_id: str,
    model: dict[str, Any],
    *,
    rule_ids: set[str] | None = None,
) -> tuple[dict[str, list[int]], list[dict[str, str]], dict[str, int]]:
    fault_plots: dict[str, list[int]] = {}
    fault_panels: list[dict[str, str]] = []
    fault_totals: dict[str, int] = {}
    rules = [r for r in RuleStore().list_rules() if isinstance(r, dict) and r.get("enabled", True)]
    color_i = 0
    for rule in rules:
        rid = str(rule.get("id") or "")
        if rule_ids is not None and rid not in rule_ids:
            continue
        if rule.get("mode") != "rule":
            continue
        code = _rule_code(rule)
        if not code.strip():
            continue
        rows = prepare_fdd_rows(df, rule, model, site_id, limit=len(df))
        n = len(rows)
        if n == 0:
            continue
        flags, events = playground.sweep_rule(code, rule.get("config") or {}, rows, capture_print=False)
        if any(e.get("type") == "error" for e in events):
            continue
        if len(flags) < n:
            flags = flags + [False] * (n - len(flags))
        flags = [1 if f else 0 for f in flags[:n]]
        fault_plots[rid] = flags
        fault_totals[rid] = sum(flags)
        color = FAULT_COLORS[color_i % len(FAULT_COLORS)]
        color_i += 1
        fault_panels.append(
            {
                "key": rid,
                "title": str(rule.get("name") or rid),
                "color": color,
                "fault_code": str(rule.get("fault_code") or ""),
            }
        )
    return fault_plots, fault_panels, fault_totals


def _prepare_frame(site_id: str, *, source: str, hours: int, limit: int) -> pd.DataFrame | None:
    df = load_site_frame(site_id, source=source)
    if df is None or df.empty:
        return None
    if "timestamp" in df.columns:
        df = df.copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
        cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=max(1, hours))
        df = df[df["timestamp"] >= cutoff]
    df = df.sort_values("timestamp") if "timestamp" in df.columns else df
    if limit and len(df) > limit:
        df = df.tail(limit)
    return df


def read_plot_readings(
    site_id: str,
    columns: list[str],
    *,
    source: str = "bacnet",
    hours: int = 24,
    limit: int = CHART_MAX_POINTS,
    include_faults: bool = True,
    rule_ids: list[str] | None = None,
) -> dict[str, Any]:
    model_svc = ModelService()
    ensure_default_site(model_svc, TtlService())
    model = model_svc.load()
    meta = list_plot_series(site_id, source=source)
    kinds = column_kinds_for_site(model, site_id)
    df = _prepare_frame(site_id, source=source, hours=hours, limit=limit)
    if df is None or df.empty:
        return {
            "site_id": site_id,
            "source": source,
            "hours": hours,
            "timestamps": [],
            "series": {},
            "series_kinds": kinds,
            "labels": meta.get("labels") or {},
            "fault_plots": {},
            "fault_panels": [],
            "fault_totals": {},
            "chart_guides": {},
            "chart_stride": 1,
            "chart_truncated": False,
        }

    ts_col = df["timestamp"].astype(str).tolist() if "timestamp" in df.columns else [str(i) for i in range(len(df))]
    series: dict[str, list[float | None]] = {}
    use_cols = columns or _numeric_columns(df)
    for col in use_cols:
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

    fault_plots: dict[str, list[int]] = {}
    fault_panels: list[dict[str, str]] = []
    fault_totals: dict[str, int] = {}
    chart_guides: dict[str, float | None] = {}
    if include_faults:
        rid_set = {str(x) for x in rule_ids if str(x).strip()} if rule_ids else None
        fault_plots, fault_panels, fault_totals = evaluate_fault_plots(df, site_id, model, rule_ids=rid_set)
        chart_guides = chart_guides_from_rules(RuleStore().list_rules())

    n = len(ts_col)
    ts_col, series, fault_plots, stride, truncated = downsample_aligned_plot(
        n, CHART_MAX_POINTS, ts_col, series, fault_plots
    )

    return {
        "site_id": site_id,
        "source": source,
        "hours": hours,
        "timestamps": ts_col,
        "series": series,
        "series_kinds": kinds,
        "labels": meta.get("labels") or {},
        "fault_plots": fault_plots,
        "fault_panels": fault_panels,
        "fault_totals": fault_totals,
        "chart_guides": chart_guides,
        "chart_stride": stride,
        "chart_truncated": truncated,
        "row_count": n,
    }


__all__ = [
    "list_plot_sites",
    "list_plot_series",
    "read_plot_readings",
    "evaluate_fault_plots",
    "downsample_aligned_plot",
]
