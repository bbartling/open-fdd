"""Operational logs for remote agent triage (no SSH)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ..deps import require_roles
from ..ops_logs import collect_ops_logs

router = APIRouter(prefix="/api/ops", tags=["ops"])

_AGENT = Depends(require_roles("integrator", "agent"))


@router.get("/logs")
def ops_logs(
    tail: int = Query(default=80, ge=10, le=500),
    service: str = Query(default="bridge"),
    include_audit: bool = Query(default=True),
    include_errors: bool = Query(default=True),
    include_docker: bool = Query(default=True),
    _user: dict = _AGENT,
) -> dict:
    """Tail bridge error/audit JSONL and optional docker compose service logs."""
    return collect_ops_logs(
        tail=tail,
        service=service,
        include_audit=include_audit,
        include_errors=include_errors,
        include_docker=include_docker,
    )
