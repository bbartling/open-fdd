"""Dashboard analytics REST — overview, faults, model health (read-only)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ..dashboard_analytics import build_fault_analytics, build_model_health, build_overview
from ..deps import require_roles

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

_AGENT = Depends(require_roles("integrator", "agent", "operator"))


@router.get("/overview")
def analytics_overview(site_id: str | None = Query(default=None)) -> dict:
    """KPI cards, fault-hour summaries, top faults for dashboard Overview."""
    return build_overview(site_id=site_id)


@router.get("/faults")
def analytics_faults(
    hours: int = Query(default=24, ge=2, le=168),
    severity: str | None = Query(default=None),
    equipment_type: str | None = Query(default=None),
) -> dict:
    """Fault analytics for dedicated Fault Analytics page."""
    return build_fault_analytics(hours=hours, severity=severity, equipment_type=equipment_type)


@router.get("/model-health")
def analytics_model_health() -> dict:
    """BACnet / BRICK model health for engineering review."""
    return build_model_health()


@router.get("/poll-throughput")
def poll_throughput(
    window_minutes: int = Query(default=60, ge=5, le=180),
    _user: dict = _AGENT,
) -> dict:
    """Expected vs observed BACnet samples/minute."""
    from ..poll_throughput import compute_poll_throughput

    return compute_poll_throughput(window_minutes=window_minutes)
