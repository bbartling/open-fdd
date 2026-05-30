from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from .. import playground
from ..data_loader import load_frame_for_run, records_from_dataframe, rows_for_evaluate, enrich_rows_with_column_map
from ..deps import require_roles
from ..model_service import ModelService
from ..site_defaults import ensure_default_site
from ..ttl_service import TtlService
from open_fdd.engine.column_map_from_model import build_column_map_from_model_points

router = APIRouter(
    prefix="/api/playground",
    tags=["playground"],
    dependencies=[Depends(require_roles("integrator", "agent"))],
)


class LintBody(BaseModel):
    code: str


class RuleBody(BaseModel):
    code: str
    config: dict[str, Any] = Field(default_factory=dict)
    site_id: str | None = None
    limit: int = Field(default=200, ge=1, le=1000)


class ScriptBody(BaseModel):
    code: str
    site_id: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    limit: int = Field(default=500, ge=1, le=1000)


@router.post("/lint")
def lint_code(body: LintBody) -> dict:
    return playground.lint_python(body.code)


@router.post("/test-rule")
def test_rule(body: RuleBody) -> dict:
    started = time.time()
    model_svc = ModelService()
    site_id = (body.site_id or "").strip() or ensure_default_site(model_svc, TtlService())
    df, origin = load_frame_for_run(site_id)
    column_map = build_column_map_from_model_points(model_svc.load(), site_id)
    rows = enrich_rows_with_column_map(rows_for_evaluate(df, limit=body.limit), column_map)
    flags, events = playground.sweep_rule(body.code, body.config, rows)
    return {
        "ok": True,
        "site_id": site_id,
        "data_source": origin,
        "rows": len(rows),
        "flagged": sum(flags),
        "ms": int((time.time() - started) * 1000),
        "events": events,
        "preview_columns": list(df.columns),
        "column_map": column_map,
    }


@router.post("/run-script")
def run_script(body: ScriptBody) -> dict:
    model_svc = ModelService()
    site_id = (body.site_id or "").strip() or ensure_default_site(model_svc, TtlService())
    df, origin = load_frame_for_run(site_id)
    if body.limit and len(df) > body.limit:
        df = df.head(body.limit)
    result = playground.run_dataframe_script(body.code, df, cfg=body.config)
    result["site_id"] = site_id
    result["data_source"] = origin
    return result


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
