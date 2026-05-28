from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from .. import playground
from ..data_loader import load_demo_dataframe, records_from_dataframe, rows_for_evaluate
from ..deps import require_user

router = APIRouter(prefix="/api/playground", tags=["playground"], dependencies=[Depends(require_user)])


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
    df = load_demo_dataframe(body.site_id)
    rows = rows_for_evaluate(df, limit=body.limit)
    flags, events = playground.sweep_rule(body.code, body.config, rows)
    return {
        "ok": True,
        "rows": len(rows),
        "flagged": sum(flags),
        "ms": int((time.time() - started) * 1000),
        "events": events,
        "preview_columns": list(df.columns),
    }


@router.post("/run-script")
def run_script(body: ScriptBody) -> dict:
    df = load_demo_dataframe(body.site_id)
    if body.limit and len(df) > body.limit:
        df = df.head(body.limit)
    return playground.run_dataframe_script(body.code, df, cfg=body.config)


@router.get("/sample-frame")
def sample_frame(
    site_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
) -> dict:
    df = load_demo_dataframe(site_id)
    return {"columns": list(df.columns), "records": records_from_dataframe(df, limit=limit)}
