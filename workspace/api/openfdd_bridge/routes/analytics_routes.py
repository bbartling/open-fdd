"""Operational analytics — poll throughput and ingest health."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ..deps import require_roles
from ..poll_throughput import compute_poll_throughput

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

_AGENT = Depends(require_roles("integrator", "agent", "operator"))


@router.get("/poll-throughput")
def poll_throughput(
    window_minutes: int = Query(default=60, ge=5, le=180),
    _user: dict = _AGENT,
) -> dict:
    """Expected vs observed BACnet samples/minute (mixed poll intervals documented)."""
    return compute_poll_throughput(window_minutes=window_minutes)
