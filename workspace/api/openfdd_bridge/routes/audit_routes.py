"""Audit log read API (integrator only)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ..audit import audit_log_path, error_log_path, tail_jsonl
from ..deps import require_roles

router = APIRouter(
    prefix="/api/audit",
    tags=["audit"],
    dependencies=[Depends(require_roles("integrator"))],
)


@router.get("/events")
def list_audit_events(limit: int = Query(default=100, ge=1, le=500)) -> dict:
    rows = tail_jsonl(audit_log_path(), limit=limit)
    return {"ok": True, "count": len(rows), "path": str(audit_log_path()), "events": rows}


@router.get("/errors")
def list_error_events(limit: int = Query(default=100, ge=1, le=500)) -> dict:
    rows = tail_jsonl(error_log_path(), limit=limit)
    return {"ok": True, "count": len(rows), "path": str(error_log_path()), "events": rows}
