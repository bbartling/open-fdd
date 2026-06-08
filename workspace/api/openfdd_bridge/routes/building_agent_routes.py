"""Building agent check-in — scheduled FDD/poll/memory loop."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from ..building_agent import get_checkin_status, run_checkin
from ..deps import require_roles

router = APIRouter(prefix="/api/building-agent", tags=["building-agent"])

_AGENT = Depends(require_roles("integrator", "agent"))


class CheckinBody(BaseModel):
    site_id: str | None = None
    run_fdd_batch: bool = True
    write_memory: bool = True
    window_minutes: int = Field(default=60, ge=5, le=180)


@router.post("/checkin")
def building_agent_checkin(body: CheckinBody, _user: dict = _AGENT) -> dict:
    """Run one check-in: poll throughput, faults, logs, optional FDD batch, memory append."""
    return run_checkin(
        site_id=body.site_id,
        run_fdd_batch=body.run_fdd_batch,
        write_memory=body.write_memory,
        window_minutes=body.window_minutes,
    )


@router.get("/status")
def building_agent_status(_user: dict = _AGENT) -> dict:
    """Last check-in runs persisted under data/building_agent_checkin.json."""
    return get_checkin_status()


@router.get("/checkin")
def building_agent_checkin_get(
    site_id: str | None = Query(default=None),
    run_fdd_batch: bool = Query(default=False),
    write_memory: bool = Query(default=True),
    window_minutes: int = Query(default=60, ge=5, le=180),
    _user: dict = _AGENT,
) -> dict:
    """Idempotent GET check-in for simple cron wget/curl (batch off by default)."""
    return run_checkin(
        site_id=site_id,
        run_fdd_batch=run_fdd_batch,
        write_memory=write_memory,
        window_minutes=window_minutes,
    )
