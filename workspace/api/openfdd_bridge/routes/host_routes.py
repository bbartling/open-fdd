from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..deps import require_roles, require_user
from ..host_stats import collect_host_stats
from ..pooge_service import PoogeRequest, preview_pooge, run_pooge

router = APIRouter(prefix="/api/host", tags=["host"])

_INTEGRATOR = Depends(require_roles("integrator"))


class PoogeBody(BaseModel):
    dry_run: bool = True
    confirmation: str = ""
    clear_historian: bool = True
    clear_bacnet: bool = True
    clear_model: bool = False
    clear_rules: bool = False
    clear_exports: bool = True
    preserve_auth: bool = True
    preserve_network: bool = True
    preserve_site_identity: bool = True
    linux_update: bool = False
    docker_update: bool = False


def _to_req(body: PoogeBody) -> PoogeRequest:
    return PoogeRequest(**body.model_dump())


@router.get("/stats")
def host_stats(_user: dict = Depends(require_user)) -> dict:
    return collect_host_stats()


@router.get("/maintenance/status")
def maintenance_status(_user: dict = _INTEGRATOR) -> dict:
    return {"ok": True, "pooge_available": True}


@router.post("/pooge/preview")
def pooge_preview(body: PoogeBody, _user: dict = _INTEGRATOR) -> dict:
    return preview_pooge(_to_req(body))


@router.post("/pooge/run")
def pooge_run(body: PoogeBody, user: dict = _INTEGRATOR) -> dict:
    return run_pooge(_to_req(body), user=user)
