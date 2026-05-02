"""
Structured checks for whether timeseries columns plot cleanly in Plotly line charts
and whether ``clean-metrics`` is recommended before FDD bounds/flatline rules.
"""

from __future__ import annotations

from typing import Literal

import pandas as pd
from pydantic import BaseModel, Field

from open_fdd.desktop.services.time_utils import infer_timestamp_column
from open_fdd.desktop.services.timeseries_numeric_clean import suggest_coercible_columns, _parse_scalar_to_float

# Share of non-null cells that must parse as plain numbers for "plot ready" without clean-metrics.
_PLAIN_NUMERIC_RATIO = 0.90
# Below this, treat as needing unit strip / clean-metrics when lead-float parse works often enough.
_LEAD_NUMERIC_HINT_RATIO = 0.30


class PlotColumnReadiness(BaseModel):
    """Per-column plot / FDD prep hints (stable for API + OpenAPI)."""

    name: str
    role: Literal["timestamp", "metric"]
    plot_line_ready: bool = Field(description="True if Plotly can plot y as numeric lines without flat/empty traces.")
    quality: str = Field(
        description="Coarse dtype bucket: numeric, boolean, string_plain_number, string_with_units, empty, other.",
    )
    non_null_numeric_parse_ratio: float | None = Field(
        default=None,
        description="Share of non-null cells where pd.to_numeric succeeds (0..1).",
    )
    lead_numeric_parse_ratio: float | None = Field(
        default=None,
        description="Share of non-null cells where leading-number parse succeeds (Grafana-style).",
    )
    recommend_clean_metrics: bool = Field(
        default=False,
        description="True when POST /timeseries/clean-metrics is likely to improve this column for plotting/FDD.",
    )
    hint: str = Field(default="", description="Human-readable one-line guidance.")


class TimeseriesPlotReadiness(BaseModel):
    """Aggregate readiness for a frame slice (API contract for UI + agents)."""

    ok: bool = Field(description="True when every metric column is plot_line_ready.")
    row_count: int
    timestamp_column: str | None = None
    metric_columns_total: int = 0
    metric_columns_not_plot_ready: int = 0
    recommend_clean_metrics: bool = Field(
        default=False,
        description="True if any metric suggests running clean-metrics (commit after preview).",
    )
    summary: str
    columns: list[PlotColumnReadiness] = Field(default_factory=list)


def _non_null_ratio_parses_plain_numeric(s: pd.Series) -> float:
    ser = s.dropna()
    if ser.empty:
        return 0.0
    parsed = pd.to_numeric(ser, errors="coerce")
    return float(parsed.notna().mean())


def _non_null_ratio_lead_numeric(s: pd.Series, *, sample_cap: int = 4000) -> float:
    ser = s.dropna()
    if ser.empty:
        return 0.0
    chunk = ser.head(sample_cap)
    ok = sum(1 for v in chunk if _parse_scalar_to_float(v) is not None)
    return ok / max(len(chunk), 1)


def analyze_dataframe_for_plot(frame: pd.DataFrame, *, sample_cap: int = 8000) -> TimeseriesPlotReadiness:
    """
    Inspect dtypes and parseability on a DataFrame slice (tail of merged or single source).

    Call on the same window you would send to Plotly before stringifying timestamps for JSON.
    """
    if frame.empty:
        return TimeseriesPlotReadiness(
            ok=True,
            row_count=0,
            summary="No rows in this site/source window.",
            columns=[],
        )
    work = frame.tail(sample_cap) if len(frame.index) > sample_cap else frame
    ts_col = "timestamp" if "timestamp" in work.columns else infer_timestamp_column(work)
    suggest_clean = set(suggest_coercible_columns(work, min_ratio=_LEAD_NUMERIC_HINT_RATIO, sample=min(800, len(work.index))))
    columns_out: list[PlotColumnReadiness] = []
    metrics_total = 0
    metrics_bad = 0
    any_recommend_clean = False

    for name in work.columns:
        col = str(name)
        if col == ts_col:
            columns_out.append(
                PlotColumnReadiness(
                    name=col,
                    role="timestamp",
                    plot_line_ready=True,
                    quality="timestamp",
                    hint="X-axis for trends.",
                ),
            )
            continue

        metrics_total += 1
        s = work[col]
        if s.dropna().empty:
            metrics_bad += 1
            columns_out.append(
                PlotColumnReadiness(
                    name=col,
                    role="metric",
                    plot_line_ready=False,
                    quality="empty",
                    non_null_numeric_parse_ratio=0.0,
                    lead_numeric_parse_ratio=0.0,
                    recommend_clean_metrics=False,
                    hint="All null in sampled window — nothing to plot.",
                ),
            )
            continue

        if pd.api.types.is_bool_dtype(s):
            columns_out.append(
                PlotColumnReadiness(
                    name=col,
                    role="metric",
                    plot_line_ready=True,
                    quality="boolean",
                    non_null_numeric_parse_ratio=1.0,
                    hint="Boolean/enum; plotted as 0/1.",
                ),
            )
            continue

        if pd.api.types.is_numeric_dtype(s):
            columns_out.append(
                PlotColumnReadiness(
                    name=col,
                    role="metric",
                    plot_line_ready=True,
                    quality="numeric",
                    non_null_numeric_parse_ratio=1.0,
                    hint="Native numeric dtype.",
                ),
            )
            continue

        r_plain = _non_null_ratio_parses_plain_numeric(s)
        r_lead = _non_null_ratio_lead_numeric(s)
        need_clean = col in suggest_clean
        if r_plain >= _PLAIN_NUMERIC_RATIO:
            columns_out.append(
                PlotColumnReadiness(
                    name=col,
                    role="metric",
                    plot_line_ready=True,
                    quality="string_plain_number",
                    non_null_numeric_parse_ratio=r_plain,
                    lead_numeric_parse_ratio=r_lead,
                    recommend_clean_metrics=False,
                    hint="Object/string column but values parse as numbers; Plotly will coerce client-side.",
                ),
            )
            continue

        if need_clean or (r_lead >= _LEAD_NUMERIC_HINT_RATIO and r_plain < _PLAIN_NUMERIC_RATIO):
            any_recommend_clean = True
            metrics_bad += 1
            columns_out.append(
                PlotColumnReadiness(
                    name=col,
                    role="metric",
                    plot_line_ready=False,
                    quality="string_with_units",
                    non_null_numeric_parse_ratio=r_plain,
                    lead_numeric_parse_ratio=r_lead,
                    recommend_clean_metrics=True,
                    hint="Use POST /timeseries/clean-metrics (preview then commit) so lines are numeric in Feather and FDD.",
                ),
            )
            continue

        metrics_bad += 1
        columns_out.append(
            PlotColumnReadiness(
                name=col,
                role="metric",
                plot_line_ready=False,
                quality="other",
                non_null_numeric_parse_ratio=r_plain,
                lead_numeric_parse_ratio=r_lead,
                recommend_clean_metrics=False,
                hint="Low numeric parse rate — check encoding, column type, or map/clean upstream.",
            ),
        )

    ok = metrics_bad == 0 and metrics_total > 0
    if metrics_total == 0:
        summary = "Only a timestamp column — add metrics to plot."
        ok_plot = True
    elif ok:
        summary = "All metric columns look plot-ready for line charts."
        ok_plot = True
    else:
        summary = (
            f"{metrics_bad} of {metrics_total} metric columns are not plot-ready as numeric lines. "
            "See per-column hints; run clean-metrics when recommend_clean_metrics is true."
        )
        ok_plot = False

    return TimeseriesPlotReadiness(
        ok=ok_plot,
        row_count=int(len(frame.index)),
        timestamp_column=str(ts_col) if ts_col else None,
        metric_columns_total=metrics_total,
        metric_columns_not_plot_ready=metrics_bad,
        recommend_clean_metrics=any_recommend_clean,
        summary=summary,
        columns=columns_out,
    )
