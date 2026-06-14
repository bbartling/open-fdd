"""Plot readings with optional FDD fault overlays (web_lambda-style)."""

from __future__ import annotations

import logging
import time
from typing import Any

import pandas as pd

_log = logging.getLogger(__name__)

from . import playground
from .data_loader import load_site_frame
from .fdd_row_prep import (
    DEFAULT_ROLLING_AVG_MINUTES,
    ROLLING_AVG_MINUTES_ALLOWED,
    build_rolling_aux_series,
    normalize_rolling_avg_minutes,
    prepare_fdd_rows,
)
from .feather_store import FeatherStore
from .model_service import ModelService
from .rule_source import read_source
from .rule_store import RuleStore
from .site_defaults import ensure_default_site
from .timeseries_api import (
    _numeric_columns,
    column_kinds_for_site,
    list_plot_series,
    list_plot_sites,
    resolve_plot_columns,
)
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
    aux_series: dict[str, list[float | None]] | None = None,
) -> tuple[
    list[str],
    dict[str, list[float | None]],
    dict[str, list[int]],
    dict[str, list[float | None]],
    int,
    bool,
]:
    aux_series = aux_series or {}
    if n <= max_pts:
        return timestamps, series, fault_plots, aux_series, 1, False
    idx = chart_sample_indices(n, max_pts)
    out_ts = [timestamps[i] for i in idx]
    out_series = {k: [vals[i] for i in idx] for k, vals in series.items()}
    out_faults = {k: [flags[i] for i in idx] for k, flags in fault_plots.items()}
    out_aux = {k: [vals[i] for i in idx] for k, vals in aux_series.items()}
    stride = max(1, n // max(len(idx) - 1, 1))
    return out_ts, out_series, out_faults, out_aux, stride, True


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


def _plot_scope_for_columns(
    model: dict[str, Any], site_id: str, columns: list[str]
) -> tuple[set[str], set[str], set[str]]:
    """Return (brick_types, point_ids, equipment_ids) for plotted telemetry columns."""
    from .timeseries_api import _equipment_for_site, _point_on_site, plot_column_name

    col_set = set(columns)
    bricks: set[str] = set()
    point_ids: set[str] = set()
    equipment_ids: set[str] = set()
    site_eq = _equipment_for_site(model, site_id)
    for pt in model.get("points") or []:
        if not isinstance(pt, dict) or not _point_on_site(pt, site_id, site_eq):
            continue
        if plot_column_name(pt) not in col_set:
            continue
        pid = str(pt.get("id") or pt.get("series_id") or "").strip()
        if pid:
            point_ids.add(pid)
        bt = str(pt.get("brick_type") or "").strip()
        if bt:
            bricks.add(bt)
        eq_id = str(pt.get("equipment_id") or "").strip()
        if eq_id:
            equipment_ids.add(eq_id)
    return bricks, point_ids, equipment_ids


def _rule_matches_plot_scope(
    rule: dict[str, Any],
    *,
    scope_bricks: set[str],
    scope_point_ids: set[str],
    scope_equipment_ids: set[str],
) -> bool:
    bindings = rule.get("bindings") if isinstance(rule.get("bindings"), dict) else {}
    point_ids = {str(x) for x in bindings.get("point_ids") or [] if str(x).strip()}
    equipment_ids = {str(x) for x in bindings.get("equipment_ids") or [] if str(x).strip()}
    rule_bricks = {str(x) for x in bindings.get("brick_types") or [] if str(x).strip()}
    if not point_ids and not equipment_ids and not rule_bricks:
        return True
    if scope_point_ids and point_ids and (point_ids & scope_point_ids):
        return True
    if scope_equipment_ids and equipment_ids and (equipment_ids & scope_equipment_ids):
        return True
    if scope_bricks and rule_bricks and (rule_bricks & scope_bricks):
        return True
    return False


def evaluate_fault_plots_table(
    table: Any,
    site_id: str,
    model: dict[str, Any],
    *,
    rule_ids: set[str] | None = None,
    scope_columns: list[str] | None = None,
    max_rules: int = 12,
) -> tuple[dict[str, list[int]], list[dict[str, str]], dict[str, int]]:
    """Evaluate enabled Arrow rules against a PyArrow table (no pandas)."""
    import pyarrow as pa

    from open_fdd.arrow_runtime.backend import run_arrow_rule
    from open_fdd.arrow_runtime.rules import detect_rule_backend

    if not isinstance(table, pa.Table):
        raise TypeError("evaluate_fault_plots_table requires pyarrow.Table")

    fault_plots: dict[str, list[int]] = {}
    fault_panels: list[dict[str, str]] = []
    fault_totals: dict[str, int] = {}
    rules = [r for r in RuleStore().list_rules() if isinstance(r, dict) and r.get("enabled", True)]
    scope_bricks: set[str] = set()
    scope_point_ids: set[str] = set()
    scope_equipment_ids: set[str] = set()
    if scope_columns:
        scope_bricks, scope_point_ids, scope_equipment_ids = _plot_scope_for_columns(
            model, site_id, scope_columns
        )
    color_i = 0
    evaluated = 0
    n = table.num_rows
    for rule in rules:
        if evaluated >= max_rules:
            break
        rid = str(rule.get("id") or "")
        if rule_ids is not None and rid not in rule_ids:
            continue
        if rule.get("mode") != "rule":
            continue
        if scope_columns and not _rule_matches_plot_scope(
            rule,
            scope_bricks=scope_bricks,
            scope_point_ids=scope_point_ids,
            scope_equipment_ids=scope_equipment_ids,
        ):
            continue
        code = _rule_code(rule)
        if not code.strip():
            continue
        if n == 0 or detect_rule_backend(code, rule) != "arrow":
            continue
        cfg = dict(rule.get("config") or {})
        cfg.setdefault("site_id", site_id)
        try:
            arrow_result = run_arrow_rule(code, table, cfg, rule_id=rid)
        except Exception:
            continue
        if arrow_result.errors:
            continue
        mask = arrow_result.fault_mask.to_pylist()
        flags = [1 if bool(v) else 0 for v in mask[:n]]
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
        evaluated += 1
    return fault_plots, fault_panels, fault_totals


def evaluate_fault_plots(
    df: pd.DataFrame,
    site_id: str,
    model: dict[str, Any],
    *,
    rule_ids: set[str] | None = None,
    scope_columns: list[str] | None = None,
    max_rules: int = 12,
) -> tuple[dict[str, list[int]], list[dict[str, str]], dict[str, int]]:
    import pyarrow as pa

    table = pa.Table.from_pandas(df.reset_index(drop=True), preserve_index=False)
    return evaluate_fault_plots_table(
        table,
        site_id,
        model,
        rule_ids=rule_ids,
        scope_columns=scope_columns,
        max_rules=max_rules,
    )


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


def build_plot_csv_text(data: dict[str, Any]) -> str:
    """Wide time-series CSV for Excel — telemetry columns plus FDD fault flags (0/1)."""
    import csv
    import io

    timestamps = data.get("timestamps") or []
    series = data.get("series") or {}
    fault_plots = data.get("fault_plots") or {}
    fault_panels = data.get("fault_panels") or []
    labels = data.get("labels") or {}
    fault_meta = {str(p.get("key") or ""): p for p in fault_panels if isinstance(p, dict)}

    series_cols = sorted(series.keys())
    fault_cols = sorted(fault_plots.keys())
    headers = ["timestamp_utc"]
    for col in series_cols:
        label = str(labels.get(col) or col).strip()
        headers.append(f"{label} ({col})" if label != col else col)
    for key in fault_cols:
        meta = fault_meta.get(key) or {}
        title = str(meta.get("title") or key).strip()
        code = str(meta.get("fault_code") or "").strip()
        headers.append(f"FDD: {title} [{code}]" if code else f"FDD: {title}")

    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(headers)
    for i, ts in enumerate(timestamps):
        row: list[Any] = [ts]
        for col in series_cols:
            vals = series.get(col) or []
            v = vals[i] if i < len(vals) else None
            row.append("" if v is None else v)
        for key in fault_cols:
            flags = fault_plots.get(key) or []
            row.append(flags[i] if i < len(flags) else "")
        writer.writerow(row)
    return buf.getvalue()


def read_plot_readings(
    site_id: str,
    columns: list[str],
    *,
    source: str = "bacnet",
    hours: int = 24,
    limit: int = CHART_MAX_POINTS,
    max_chart_points: int | None = None,
    include_faults: bool = True,
    rule_ids: list[str] | None = None,
    rolling_avg_minutes: int | None = DEFAULT_ROLLING_AVG_MINUTES,
    show_rolling_avg: bool = True,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    model_svc = ModelService()
    ensure_default_site(model_svc, TtlService())
    model = model_svc.load()
    meta = list_plot_series(site_id, source=source)
    kinds = column_kinds_for_site(model, site_id)
    columns = resolve_plot_columns(columns, model, site_id)
    _log.info(
        "plot readings start site=%s cols=%d hours=%s include_faults=%s",
        site_id,
        len(columns),
        hours,
        include_faults,
    )
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
            "aux_series": {},
            "rolling_avg_minutes": normalize_rolling_avg_minutes(rolling_avg_minutes),
            "rolling_avg_minutes_allowed": list(ROLLING_AVG_MINUTES_ALLOWED),
            "show_rolling_avg": show_rolling_avg,
        }

    roll_min = normalize_rolling_avg_minutes(rolling_avg_minutes)
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

    aux_series: dict[str, list[float | None]] = {}
    if show_rolling_avg and roll_min > 0:
        aux_series = build_rolling_aux_series(df, use_cols, kinds, minutes=roll_min)

    fault_plots: dict[str, list[int]] = {}
    fault_panels: list[dict[str, str]] = []
    fault_totals: dict[str, int] = {}
    chart_guides: dict[str, float | None] = {}
    if include_faults:
        rid_set = {str(x) for x in rule_ids if str(x).strip()} if rule_ids else None
        t_fault = time.perf_counter()
        fault_plots, fault_panels, fault_totals = evaluate_fault_plots(
            df,
            site_id,
            model,
            rule_ids=rid_set,
            scope_columns=columns or None,
        )
        _log.info(
            "plot fault eval site=%s rules=%d ms=%d",
            site_id,
            len(fault_panels),
            int((time.perf_counter() - t_fault) * 1000),
        )
        chart_guides = chart_guides_from_rules(RuleStore().list_rules())

    n = len(ts_col)
    chart_cap = max_chart_points if max_chart_points is not None else CHART_MAX_POINTS
    ts_col, series, fault_plots, aux_series, stride, truncated = downsample_aligned_plot(
        n, chart_cap, ts_col, series, fault_plots, aux_series
    )

    _log.info(
        "plot readings done site=%s series=%d rows=%d ms=%d truncated=%s",
        site_id,
        len(series),
        len(ts_col),
        int((time.perf_counter() - t0) * 1000),
        truncated,
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
        "aux_series": aux_series,
        "rolling_avg_minutes": roll_min,
        "rolling_avg_minutes_allowed": list(ROLLING_AVG_MINUTES_ALLOWED),
        "show_rolling_avg": show_rolling_avg,
    }


__all__ = [
    "list_plot_sites",
    "list_plot_series",
    "read_plot_readings",
    "evaluate_fault_plots",
    "evaluate_fault_plots_table",
    "downsample_aligned_plot",
]
