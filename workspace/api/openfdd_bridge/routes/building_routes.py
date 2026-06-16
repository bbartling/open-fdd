"""Building check-engine status — default home view content."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..building_alerts import load_alerts, replace_alerts
from ..building_status import collect_status, public_dashboard_snapshot
from ..deps import require_roles, require_user
from ..portfolio_rollup import build_portfolio_rollup
from ..security import clients_must_authenticate, public_dashboard_ws_allowed

router = APIRouter(prefix="/api/building", tags=["building"])


class AlertItem(BaseModel):
    id: str | None = None
    severity: str = "warning"
    title: str
    detail: str = ""
    source: str = "agent"
    code: str = ""
    equipment_family: str = ""


class AlertsBody(BaseModel):
    alerts: list[AlertItem] = Field(default_factory=list)
    status: str | None = None


@router.get("/snapshot")
def building_snapshot(_user: dict = Depends(require_user)) -> dict:
    """Dashboard payload: stack status strip + live fault tree (authenticated)."""
    snap = public_dashboard_snapshot()
    return {"ok": True, **snap}


@router.get("/public-snapshot")
def building_public_snapshot() -> dict:
    """Read-only dashboard faults for wall displays / anonymous viewers."""
    if clients_must_authenticate() and not public_dashboard_ws_allowed():
        raise HTTPException(status_code=401, detail="unauthorized")
    snap = public_dashboard_snapshot()
    return {"ok": True, **snap}


@router.get("/status")
def building_status(_user: dict = Depends(require_user)) -> dict:
    status = collect_status()
    health = status["model_health"]
    configured = bool(status.get("model_configured"))
    counts = health.get("counts") if isinstance(health.get("counts"), dict) else {}
    return {
        "ok": True,
        "status": status["status"],
        "traffic": status["traffic"],
        "model_configured": configured,
        "model_score": health.get("score") if configured else None,
        "model_summary": health.get("summary") if configured else None,
        "model_counts": {
            "equipment": counts.get("equipment"),
            "points": counts.get("points"),
        }
        if configured
        else None,
        "alert_count": len(status["alerts"]),
        "alerts": status["alerts"],
        "fdd_alert_count": status["fdd_alert_count"],
        "check_engine": status["status"] != "ok",
    }


@router.get("/portfolio-rollup")
def portfolio_rollup(
    site_id: str | None = Query(default=None),
    _user: dict = Depends(require_roles("integrator", "agent")),
) -> dict:
    """Central collector snapshot: run hours, faults, P8 overrides, poll health."""
    return build_portfolio_rollup(site_id=site_id)


@router.get("/alerts")
def get_alerts(_user: dict = Depends(require_user)) -> dict:
    return {"ok": True, **load_alerts()}


@router.put("/alerts")
def put_alerts(body: AlertsBody, user: dict = Depends(require_roles("integrator", "agent"))) -> dict:
    username = str(user.get("sub") or "agent")
    for alert in body.alerts:
        _ = alert
    doc = replace_alerts(
        [a.model_dump() for a in body.alerts],
        updated_by=username,
        status=body.status,
    )
    return {"ok": True, **doc}
