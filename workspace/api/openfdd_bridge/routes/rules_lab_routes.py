from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..deps import require_roles
from ..model_service import ModelService
from ..rule_store import RuleStore
from ..rules_lab import (
    compare_rule_backends,
    detect_backend_from_payload,
    preview_datafusion_sql,
    validate_datafusion_sql,
)
from ..site_defaults import ensure_default_site
from ..ttl_service import TtlService
from open_fdd.arrow_runtime.datafusion_backend import lint_datafusion_sql_rule

router = APIRouter(
    prefix="/api/rules/lab",
    tags=["rules-lab"],
    dependencies=[Depends(require_roles("integrator", "agent"))],
)


class LabSqlBody(BaseModel):
    backend: str = "datafusion_sql"
    sql: str = ""
    fault_column: str = "fault"
    sample_source: str = "latest"
    site_id: str | None = None
    limit: int = Field(default=500, ge=1, le=10000)
    lookback_hours: float = Field(default=24, ge=0, le=720)


class CompareSide(BaseModel):
    backend: str
    rule_id: str = ""
    code: str = ""
    sql: str = ""
    fault_column: str = "fault"
    config: dict[str, Any] = Field(default_factory=dict)


class LabCompareBody(BaseModel):
    left: CompareSide
    right: CompareSide
    sample_source: str = "latest"
    site_id: str | None = None
    limit: int = Field(default=1000, ge=1, le=10000)
    lookback_hours: float = Field(default=24, ge=0, le=720)


class LabSaveBody(BaseModel):
    id: str | None = None
    name: str = "Untitled rule"
    short_description: str = ""
    description: str = ""
    mode: str = "rule"
    backend: str = "arrow"
    code: str = ""
    sql: str = ""
    fault_column: str = "fault"
    config: dict[str, Any] = Field(default_factory=dict)
    column_map: dict[str, str] = Field(default_factory=dict)
    applies_to: dict[str, Any] = Field(default_factory=dict)
    bindings: dict[str, list[str]] = Field(default_factory=dict)
    severity: str = "warning"
    enabled: bool = True


def _resolve_site_id(site_id: str | None) -> str:
    svc = ModelService()
    return (site_id or "").strip() or ensure_default_site(svc, TtlService())


@router.post("/validate")
def lab_validate(body: LabSqlBody) -> dict:
    backend = str(body.backend or "").strip()
    if backend != "datafusion_sql":
        raise HTTPException(status_code=400, detail=f"validate supports datafusion_sql only, got {backend!r}")
    site_id = _resolve_site_id(body.site_id)
    return validate_datafusion_sql(
        sql=body.sql,
        fault_column=body.fault_column,
        site_id=site_id,
        limit=body.limit,
        lookback_hours=body.lookback_hours,
    )


@router.post("/preview")
def lab_preview(body: LabSqlBody) -> dict:
    backend = str(body.backend or "").strip()
    if backend != "datafusion_sql":
        raise HTTPException(status_code=400, detail=f"preview supports datafusion_sql only, got {backend!r}")
    site_id = _resolve_site_id(body.site_id)
    return preview_datafusion_sql(
        sql=body.sql,
        fault_column=body.fault_column,
        site_id=site_id,
        limit=body.limit,
        lookback_hours=body.lookback_hours,
    )


@router.post("/compare")
def lab_compare(body: LabCompareBody) -> dict:
    site_id = _resolve_site_id(body.site_id)
    return compare_rule_backends(
        left=body.left.model_dump(),
        right=body.right.model_dump(),
        site_id=site_id,
        limit=body.limit,
        lookback_hours=body.lookback_hours,
    )


@router.post("/lint-sql")
def lab_lint_sql(body: LabSqlBody) -> dict:
    """Static SQL lint — no execution."""
    return lint_datafusion_sql_rule(body.sql, fault_column=body.fault_column)


@router.post("/save")
def lab_save(body: LabSaveBody, user: dict = Depends(require_roles("integrator", "agent"))) -> dict:
    saved_by = str(user.get("sub") or user.get("role") or "operator")
    backend = str(body.backend or "").strip() or detect_backend_from_payload(body.model_dump())
    payload = body.model_dump()
    payload["backend"] = backend
    if backend == "datafusion_sql":
        if not str(payload.get("sql") or "").strip():
            raise HTTPException(status_code=400, detail="datafusion_sql rules require sql")
        payload.setdefault("code", "# DataFusion SQL rule — see sql field")
    elif not str(payload.get("code") or "").strip():
        raise HTTPException(status_code=400, detail="arrow rules require code")
    if not str(payload.get("short_description") or "").strip():
        payload["short_description"] = str(body.name or "Fault detected").strip()[:240]
    try:
        entry = RuleStore().upsert(payload, saved_by=saved_by)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "rule": entry}
