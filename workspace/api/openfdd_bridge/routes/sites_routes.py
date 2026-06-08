from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..data_loader import load_demo_dataframe, records_from_dataframe
from ..deps import require_roles, require_user
from ..model_sparql import list_model_sites
from ..model_service import ModelService
from ..site_defaults import ensure_default_site
from ..site_memory import get_site_memory, put_site_memory
from ..ttl_service import TtlService

router = APIRouter(prefix="/api/sites", tags=["sites"], dependencies=[Depends(require_user)])

_AGENT_WRITE = Depends(require_roles("integrator", "agent"))


class SiteMemoryBody(BaseModel):
    content: str = ""
    mode: str = Field(default="replace", pattern="^(replace|append)$")

MAX_FRAME_LIMIT = 500
DEFAULT_FRAME_LIMIT = 200


@router.get("")
def list_sites() -> dict:
    model_svc = ModelService()
    ensure_default_site(model_svc, TtlService())
    sites = list_model_sites(model_svc.load())
    if sites:
        return {"sites": [{"site_id": s["site_id"], "label": s["name"]} for s in sites]}
    df = load_demo_dataframe()
    site_ids = sorted(df["site_id"].unique().tolist()) if "site_id" in df.columns else []
    return {
        "sites": [{"site_id": sid, "label": sid} for sid in site_ids if sid.lower() != "demo"],
    }


@router.get("/{site_id}/frame")
def site_frame(site_id: str, limit: int = DEFAULT_FRAME_LIMIT) -> dict:
    safe_limit = max(1, min(int(limit), MAX_FRAME_LIMIT))
    df = load_demo_dataframe(site_id)
    return {"site_id": site_id, "records": records_from_dataframe(df, limit=safe_limit)}


@router.get("/{site_id}/memory")
def site_memory_get(site_id: str, kind: str = "memory") -> dict:
    """Per-building MEMORY.md (kind=memory) or SKILLS.md (kind=skills)."""
    if kind not in {"memory", "skills"}:
        raise HTTPException(status_code=400, detail="kind must be memory or skills")
    try:
        return get_site_memory(site_id=site_id, kind=kind)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/{site_id}/memory")
def site_memory_put(
    site_id: str,
    body: SiteMemoryBody,
    kind: str = "memory",
    _user: dict = _AGENT_WRITE,
) -> dict:
    if kind not in {"memory", "skills"}:
        raise HTTPException(status_code=400, detail="kind must be memory or skills")
    try:
        return put_site_memory(
            site_id=site_id,
            content=body.content,
            kind=kind,
            mode=body.mode,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
