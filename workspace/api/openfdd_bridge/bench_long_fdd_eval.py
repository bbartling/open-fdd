"""Bench long FDD evaluate API — read-only historian + Arrow/DataFusion execution."""

from __future__ import annotations

from typing import Any

import pyarrow as pa
from pydantic import BaseModel, Field

from open_fdd.validation.bench_5007_long_fdd import (
    SmokeConfig,
    align_semantic_points,
    evaluate_backend_on_table,
    historian_source,
    _parse_ts,
)


class BenchLongFddEvaluateBody(BaseModel):
    """Read-only bench validation payload — smoke/long-FDD use; not a general SQL API."""

    site_id: str = Field(default="demo", max_length=64)
    source: str = Field(default="bacnet_direct", pattern="^(bacnet_direct|niagara_baskstream)$")
    semantic_key: str = Field(default="duct-t", max_length=128)
    backend: str = Field(default="pyarrow", pattern="^(pyarrow|datafusion_sql)$")
    threshold: float = 80.0
    phase: str = "fault"
    lookback_hours: float = Field(default=2.0, ge=0.1, le=168.0)
    poll_interval_s: int = Field(default=60, ge=15, le=3600)
    confirmation_rows: int = Field(default=10, ge=1, le=1000)
    confirmation_minutes: float = Field(default=10.0, ge=0.0, le=1440.0)
    fault_direction: str = Field(default="below", pattern="^(below|above)$")
    run_started_at: str | None = None
    threshold_change_at: str | None = None
    threshold_change_row_index: int | None = Field(default=None, ge=0, le=100000)
    freshness_window_minutes: float | None = Field(default=None, ge=0.1, le=1440.0)


def evaluate_long_fdd(body: BenchLongFddEvaluateBody, model: dict[str, Any]) -> dict[str, Any]:
    from datetime import datetime, timedelta, timezone

    from open_fdd.arrow_runtime.column_map_from_model import build_column_map_from_model_points
    from open_fdd.arrow_runtime.features import arrow_time_filter
    from openfdd_bridge.data_loader import load_arrow_table_for_run

    aligned = align_semantic_points(model, body.site_id)
    by_source = aligned.get(body.semantic_key) or {}
    pt = by_source.get(body.source)
    if pt is None:
        return {"ok": False, "error": f"no model alignment for {body.semantic_key!r} source {body.source!r}"}

    col_map = build_column_map_from_model_points(model, body.site_id)
    value_col = col_map.get(pt.fdd_input) or pt.historian_column or pt.fdd_input
    hist_src = historian_source(body.source)
    columns = sorted({value_col, "timestamp", "site_id", "equipment_id"})
    table, origin = load_arrow_table_for_run(body.site_id, source=hist_src, columns=columns)
    if not isinstance(table, pa.Table) or table.num_rows == 0:
        return {"ok": False, "error": f"no historian data for source={hist_src}", "origin": origin}

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=body.lookback_hours)
    if body.run_started_at:
        run_start = _parse_ts(body.run_started_at)
        if run_start:
            cutoff = max(cutoff, run_start - timedelta(minutes=5))
    table = arrow_time_filter(table, "timestamp", cutoff, None)
    if table.num_rows == 0:
        return {"ok": False, "error": f"no historian rows within lookback/window", "origin": origin}

    cfg = SmokeConfig(
        site_id=body.site_id,
        poll_seconds=body.poll_interval_s,
        confirmation_rows=body.confirmation_rows,
        confirmation_minutes=body.confirmation_minutes,
        fault_direction=body.fault_direction,
        forced_threshold_f=body.threshold,
        freshness_window_minutes=body.freshness_window_minutes or 5.0,
    )
    threshold_change_wall = _parse_ts(body.threshold_change_at) if body.threshold_change_at else None
    metrics = evaluate_backend_on_table(
        table,
        alignment=pt,
        backend=body.backend,
        cfg=cfg,
        threshold=body.threshold,
        phase=body.phase,
        threshold_change_wall=threshold_change_wall,
        threshold_change_row_index=body.threshold_change_row_index,
    )
    return {
        "ok": not metrics.errors,
        "origin": origin,
        "metrics": {
            "source": metrics.source,
            "point_id": metrics.point_id,
            "equipment_id": metrics.equipment_id,
            "semantic_key": metrics.semantic_key,
            "backend": metrics.backend,
            "row_count": metrics.row_count,
            "raw_true_count": metrics.raw_true_count,
            "confirmed_true_count": metrics.confirmed_true_count,
            "first_raw_fault_time": metrics.first_raw_fault_time,
            "first_confirmed_fault_time": metrics.first_confirmed_fault_time,
            "first_raw_fault_after_change": metrics.first_raw_fault_after_change,
            "first_confirmed_fault_after_change": metrics.first_confirmed_fault_after_change,
            "first_sample_time": metrics.first_sample_time,
            "last_sample_time": metrics.last_sample_time,
            "confirmation_delay_seconds": metrics.confirmation_delay_seconds,
            "observed_confirmation_delay_seconds": metrics.observed_confirmation_delay_seconds,
            "expected_confirmation_delay_seconds": metrics.expected_confirmation_delay_seconds,
            "average_sample_interval_s": metrics.average_sample_interval_s,
            "max_sample_gap_s": metrics.max_sample_gap_s,
            "threshold_change_wall_time": metrics.threshold_change_wall_time,
            "threshold_change_sample_time": metrics.threshold_change_sample_time,
            "threshold_change_row_index": metrics.threshold_change_row_index,
            "preexisting_raw_fault": metrics.preexisting_raw_fault,
            "early_confirmed_fault": metrics.early_confirmed_fault,
            "value_avg": metrics.value_avg,
            "value_min": metrics.value_min,
            "value_max": metrics.value_max,
            "raw_mask_fingerprint": metrics.raw_mask_fingerprint,
            "confirmed_mask_fingerprint": metrics.confirmed_mask_fingerprint,
            "execution_evidence": metrics.execution_evidence,
            "errors": metrics.errors,
        },
    }
