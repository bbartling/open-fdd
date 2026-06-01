from __future__ import annotations

import logging
import time
import traceback
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from .. import playground
from ..data_loader import load_frame_for_run, records_from_dataframe
from ..fdd_row_prep import prepare_fdd_rows
from ..deps import require_roles
from ..model_service import ModelService
from ..site_defaults import ensure_default_site
from ..timeseries_api import resolve_plot_columns
from ..ttl_service import TtlService
from open_fdd.engine.column_map_from_model import build_column_map_from_model_points

_log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/playground",
    tags=["playground"],
    dependencies=[Depends(require_roles("integrator", "agent"))],
)


class LintBody(BaseModel):
    code: str
    mode: str = "rule"


class RuleBody(BaseModel):
    code: str
    config: dict[str, Any] = Field(default_factory=dict)
    site_id: str | None = None
    limit: int = Field(default=200, ge=1, le=10000)
    chunk_hours: float = Field(default=0, ge=0, le=168)
    lookback_hours: float = Field(default=24, ge=0, le=168)
    point_id: str | None = None
    point_keys: list[str] = Field(default_factory=list)
    equipment_id: str | None = None
    value_kind: str | None = None


class ScriptBody(BaseModel):
    code: str
    site_id: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    limit: int = Field(default=500, ge=1, le=10000)
    lookback_hours: float = Field(default=24, ge=0, le=168)
    equipment_id: str | None = None
    point_keys: list[str] = Field(default_factory=list)


def _filter_frame_to_scope(
    df,
    model: dict[str, Any],
    site_id: str,
    *,
    equipment_id: str | None,
    point_keys: list[str],
) -> tuple[Any, list[str], str | None]:
    """Return (scoped_df, data_columns_kept, warning_if_scope_missed)."""
    import pandas as pd

    meta = {"timestamp", "site_id", "building_id", "system_id"}
    scoped = bool((point_keys and any(str(x).strip() for x in point_keys)) or (equipment_id and str(equipment_id).strip()))
    if not scoped:
        data_cols = [c for c in df.columns if c not in meta]
        return df, data_cols, None

    cols: list[str] = []
    if point_keys:
        cols = resolve_plot_columns(point_keys, model, site_id)
    elif equipment_id:
        # Device-only scope is intentionally not supported for rule test (too wide / column collisions).
        warning = "pick at least one sensor (point) — device-wide scope is disabled for rule test"
        empty = df.iloc[0:0].copy()
        return empty, [], warning

    if not cols:
        warning = "scope requested but no model columns resolved — empty data frame"
        empty = df.iloc[0:0].copy() if isinstance(df, pd.DataFrame) else df
        return empty, [], warning

    keep = [c for c in df.columns if c in meta or c in cols]
    data_kept = [c for c in keep if c not in meta]
    if not data_kept:
        warning = f"scope columns {cols!r} not in feather store — re-poll or check external_id"
        empty = df.iloc[0:0].copy()
        return empty, [], warning

    return df[keep], data_kept, None


def _apply_lookback(df, lookback_hours: float):
    if lookback_hours <= 0 or df.empty or "timestamp" not in df.columns:
        return df
    import pandas as pd

    cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=lookback_hours)
    ts = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    trimmed = df.loc[ts >= cutoff].copy()
    return trimmed if not trimmed.empty else df


@router.post("/lint")
def lint_code(body: LintBody) -> dict:
    return playground.lint_python(body.code, require_evaluate=body.mode != "script")


@router.post("/test-rule")
def test_rule(body: RuleBody) -> dict:
    started = time.time()
    lint = playground.lint_python(body.code)
    if not lint["ok"]:
        return {
            "ok": False,
            "issues": lint["issues"],
            "events": playground._lint_error_events(lint),  # noqa: SLF001
            "rows": 0,
            "flagged": 0,
            "ms": int((time.time() - started) * 1000),
        }
    try:
        model_svc = ModelService()
        site_id = (body.site_id or "").strip() or ensure_default_site(model_svc, TtlService())
        df, origin = load_frame_for_run(site_id)
        df = _apply_lookback(df, body.lookback_hours or 24)
        model = model_svc.load()
        point_keys = [x for x in (body.point_keys or ([body.point_id] if body.point_id else [])) if str(x).strip()]
        df, scope_cols, scope_warning = _filter_frame_to_scope(
            df,
            model,
            site_id,
            equipment_id=body.equipment_id,
            point_keys=point_keys,
        )
        if body.limit and len(df) > body.limit:
            df = df.tail(body.limit)
        rule_stub: dict[str, Any] = {
            "config": dict(body.config),
            "bindings": {
                "point_ids": point_keys,
                "equipment_ids": [body.equipment_id] if body.equipment_id else [],
            },
        }
        if body.value_kind:
            rule_stub["config"]["value_kind"] = body.value_kind
        rows = prepare_fdd_rows(df, rule_stub, model, site_id, limit=len(df))
        value_column = rows[0].get("value_column") if rows else ""
        column_map = build_column_map_from_model_points(model, site_id)
        chunk_hours = body.chunk_hours or 0
        use_chunked = chunk_hours > 0 and len(df) > 500
        if use_chunked:
            row_count, flagged, events = playground.sweep_dataframe_chunked(
                body.code,
                body.config,
                df,
                chunk_hours=chunk_hours,
                enrich_rows=lambda _rows: rows,
            )
        else:
            flags, events = playground.sweep_rule(body.code, body.config, rows)
            row_count = len(rows)
            flagged = sum(flags)
        ok = not any(ev.get("type") == "error" for ev in events)
        scope_label = ""
        if body.equipment_id:
            scope_label = f"equipment={body.equipment_id}"
        elif body.point_keys:
            scope_label = f"points={len(body.point_keys)}"
        _log.info(
            "test-rule site=%s scope=%s rows=%d flagged=%d ms=%d",
            site_id,
            scope_label or "full-site",
            row_count,
            flagged,
            int((time.time() - started) * 1000),
        )
        max_events = 80
        trimmed_events = events[:max_events]
        if len(events) > max_events:
            trimmed_events = [
                *trimmed_events,
                {"type": "stdout", "text": f"… {len(events) - max_events} more events omitted"},
            ]
        return {
            "ok": ok,
            "site_id": site_id,
            "data_source": origin,
            "equipment_id": body.equipment_id or "",
            "point_keys": point_keys,
            "value_column": value_column,
            "scope_columns": scope_cols,
            "scope_warning": scope_warning,
            "rows": row_count,
            "flagged": flagged,
            "ms": int((time.time() - started) * 1000),
            "events": trimmed_events,
            "column_map": column_map,
            "chunked": use_chunked,
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "trace": traceback.format_exc(limit=12),
            "rows": 0,
            "flagged": 0,
            "ms": int((time.time() - started) * 1000),
            "events": [{"type": "error", "text": str(exc), "trace": traceback.format_exc(limit=12)}],
        }


@router.post("/run-script")
def run_script(body: ScriptBody) -> dict:
    lint = playground.lint_python(body.code, require_evaluate=False)
    if not lint["ok"]:
        return {
            "ok": False,
            "issues": lint["issues"],
            "error": "syntax error — fix before run",
            "events": playground._lint_error_events(lint),  # noqa: SLF001
        }
    try:
        model_svc = ModelService()
        site_id = (body.site_id or "").strip() or ensure_default_site(model_svc, TtlService())
        df, origin = load_frame_for_run(site_id)
        model = model_svc.load()
        df = _apply_lookback(df, body.lookback_hours or 24)
        df, _, _scope_warn = _filter_frame_to_scope(
            df,
            model,
            site_id,
            equipment_id=body.equipment_id,
            point_keys=body.point_keys,
        )
        if body.limit and len(df) > body.limit:
            df = df.head(body.limit)
        result = playground.run_dataframe_script(body.code, df, cfg=body.config)
        result["site_id"] = site_id
        result["data_source"] = origin
        return result
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "trace": traceback.format_exc(limit=12),
        }


@router.get("/sample-frame")
def sample_frame(
    site_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
) -> dict:
    model_svc = ModelService()
    sid = (site_id or "").strip() or ensure_default_site(model_svc, TtlService())
    df, origin = load_frame_for_run(sid)
    return {
        "site_id": sid,
        "data_source": origin,
        "columns": list(df.columns),
        "records": records_from_dataframe(df, limit=limit),
    }
