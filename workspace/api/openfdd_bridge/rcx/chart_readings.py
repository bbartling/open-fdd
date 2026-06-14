"""Arrow-native feather reads for RCx trend charts."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from ..feather_store import FeatherStore
from ..model_service import ModelService
from ..plot_readings import CHART_MAX_POINTS, downsample_aligned_plot, evaluate_fault_plots_table
from ..site_defaults import default_site_id, ensure_default_site
from ..timeseries_api import column_kinds_for_site, list_plot_series, resolve_plot_columns
from ..ttl_service import TtlService


def _resolve_site_id(site_id: str) -> str:
    sid = str(site_id or "").strip()
    if sid:
        return sid
    svc = ModelService()
    return ensure_default_site(svc, TtlService()) or default_site_id()


def _filter_table_by_hours(table, *, hours: int):
    import pyarrow as pa
    import pyarrow.compute as pc

    if table.num_rows == 0 or "timestamp" not in table.column_names:
        return table
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max(1, hours))
    ts_col = table.column("timestamp")
    if pa.types.is_string(ts_col.type) or pa.types.is_large_string(ts_col.type):
        parsed = pc.cast(ts_col, pa.timestamp("us", tz="UTC"))
    else:
        parsed = ts_col
    mask = pc.greater_equal(parsed, pa.scalar(cutoff, type=parsed.type))
    filtered = table.filter(mask)
    if filtered.num_rows == 0:
        return table
    return filtered


def _column_to_float_list(table, col: str) -> list[float | None]:
    if col not in table.column_names:
        return []
    import pyarrow as pa

    col_data = table.column(col)
    out: list[float | None] = []
    for val in col_data.to_pylist():
        if val is None:
            out.append(None)
            continue
        try:
            if isinstance(val, float) and val != val:
                out.append(None)
            else:
                out.append(float(val))
        except (TypeError, ValueError):
            out.append(None)
    return out


def read_chart_readings(
    site_id: str,
    columns: list[str],
    *,
    source: str = "bacnet",
    hours: int = 24,
    include_faults: bool = True,
    max_chart_points: int = CHART_MAX_POINTS,
) -> dict[str, Any]:
    """Read historian columns from feather store using PyArrow (no full-site pandas load)."""
    sid = _resolve_site_id(site_id)
    model_svc = ModelService()
    ensure_default_site(model_svc, TtlService())
    model = model_svc.load()
    meta = list_plot_series(sid, source=source)
    kinds = column_kinds_for_site(model, sid)
    columns = resolve_plot_columns(columns, model, sid)

    empty = {
        "site_id": sid,
        "source": source,
        "hours": hours,
        "timestamps": [],
        "series": {},
        "series_kinds": kinds,
        "labels": meta.get("labels") or {},
        "fault_plots": {},
        "fault_panels": [],
        "fault_totals": {},
        "row_count": 0,
    }
    if not columns:
        return empty

    store = FeatherStore()
    read_cols = list(dict.fromkeys(["timestamp", *columns]))
    table = store.read_site_table(sid, source=source, columns=read_cols)
    if table is None or table.num_rows == 0:
        return empty

    table = _filter_table_by_hours(table, hours=hours)
    if table.num_rows == 0:
        return empty

    ts_col = table.column("timestamp").to_pylist()
    timestamps = [str(t) for t in ts_col]
    series = {col: _column_to_float_list(table, col) for col in columns if col in table.column_names}

    fault_plots: dict[str, list[int]] = {}
    fault_panels: list[dict[str, str]] = []
    fault_totals: dict[str, int] = {}
    if include_faults:
        fault_plots, fault_panels, fault_totals = evaluate_fault_plots_table(
            table,
            sid,
            model,
            scope_columns=columns or None,
        )

    n = len(timestamps)
    ts_out, series, fault_plots, _aux, stride, truncated = downsample_aligned_plot(
        n,
        max_chart_points,
        timestamps,
        series,
        fault_plots,
        {},
    )

    return {
        "site_id": sid,
        "source": source,
        "hours": hours,
        "timestamps": ts_out,
        "series": series,
        "series_kinds": kinds,
        "labels": meta.get("labels") or {},
        "fault_plots": fault_plots,
        "fault_panels": fault_panels,
        "fault_totals": fault_totals,
        "chart_stride": stride,
        "chart_truncated": truncated,
        "row_count": n,
    }


def read_chart_readings_with_plot_fallback(
    site_id: str,
    columns: list[str],
    *,
    source: str = "bacnet",
    hours: int = 24,
    include_faults: bool = True,
) -> dict[str, Any]:
    """Prefer Arrow feather reads; fall back to plot_readings when store is empty."""
    data = read_chart_readings(
        site_id,
        columns,
        source=source,
        hours=hours,
        include_faults=include_faults,
    )
    if data.get("row_count"):
        return data
    from ..plot_readings import read_plot_readings

    return read_plot_readings(
        _resolve_site_id(site_id),
        columns,
        source=source,
        hours=hours,
        include_faults=include_faults,
    )
