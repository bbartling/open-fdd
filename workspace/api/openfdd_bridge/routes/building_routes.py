"""Building check-engine status — default home view content."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..building_alerts import load_alerts, merge_auto_issues, replace_alerts
from ..deps import require_roles, require_user
from ..model_health import model_health_summary
from ..model_service import ModelService
from ..stack_health import stack_health

router = APIRouter(prefix="/api/building", tags=["building"])


class AlertItem(BaseModel):
    id: str | None = None
    severity: str = "warning"
    title: str
    detail: str = ""
    source: str = "agent"


class AlertsBody(BaseModel):
    alerts: list[AlertItem] = Field(default_factory=list)
    status: str | None = None


@router.get("/status")
def building_status(_user: dict = Depends(require_user)) -> dict:
    model = ModelService().load()
    health = model_health_summary(model)
    stored = load_alerts()
    merged = merge_auto_issues(model_issues=health.get("issues", []), stored=stored)
    stack = stack_health()
    stack_issues: list[dict[str, str]] = []
    for svc in stack.get("services", []):
        if not isinstance(svc, dict):
            continue
        st = str(svc.get("status") or "")
        if st in {"red", "yellow"}:
            stack_issues.append(
                {
                    "id": f"stack-{svc.get('id')}",
                    "severity": "critical" if st == "red" else "warning",
                    "title": f"{svc.get('label', 'Service')} {st}",
                    "detail": str(svc.get("detail") or ""),
                    "source": "system",
                }
            )
    all_alerts = merged["alerts"] + stack_issues
    status = merged["status"]
    if stack_issues and status == "ok":
        status = "warning"
    if any(a.get("severity") == "critical" for a in stack_issues):
        status = "critical"
    return {
        "ok": True,
        "status": status,
        "model_score": health.get("score"),
        "model_summary": health.get("summary"),
        "alert_count": len(all_alerts),
        "alerts": all_alerts,
        "stack": stack,
        "check_engine": status != "ok",
    }


@router.get("/alerts")
def get_alerts(_user: dict = Depends(require_user)) -> dict:
    return {"ok": True, **load_alerts()}


@router.put("/alerts")
def put_alerts(body: AlertsBody, user: dict = Depends(require_roles("integrator", "agent"))) -> dict:
    username = str(user.get("sub") or "agent")
    doc = replace_alerts(
        [a.model_dump() for a in body.alerts],
        updated_by=username,
        status=body.status,
    )
    return {"ok": True, **doc}
