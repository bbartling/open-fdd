"""Building check-engine status — default home view content."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..building_alerts import load_alerts, replace_alerts
from ..building_status import collect_status
from ..deps import require_roles, require_user
from ..fault_catalog import is_valid_code

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


@router.get("/status")
def building_status(_user: dict = Depends(require_user)) -> dict:
    status = collect_status()
    health = status["model_health"]
    return {
        "ok": True,
        "status": status["status"],
        "traffic": status["traffic"],
        "model_score": health.get("score"),
        "model_summary": health.get("summary"),
        "alert_count": len(status["alerts"]),
        "alerts": status["alerts"],
        "stack": status["stack"],
        "fdd_alert_count": status["fdd_alert_count"],
        "check_engine": status["status"] != "ok",
    }


@router.get("/alerts")
def get_alerts(_user: dict = Depends(require_user)) -> dict:
    return {"ok": True, **load_alerts()}


@router.put("/alerts")
def put_alerts(body: AlertsBody, user: dict = Depends(require_roles("integrator", "agent"))) -> dict:
    username = str(user.get("sub") or "agent")
    for alert in body.alerts:
        if alert.code and not is_valid_code(alert.code):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"unknown fault code '{alert.code}'. Use a fixed code from "
                    "/api/faults/catalog — codes must not be invented."
                ),
            )
    doc = replace_alerts(
        [a.model_dump() for a in body.alerts],
        updated_by=username,
        status=body.status,
    )
    return {"ok": True, **doc}
