"""BRICK data model import/export and TTL sync."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from ..deps import require_roles, require_user
from ..model_health import model_health_summary
from ..model_service import ModelService
from ..site_defaults import ensure_default_site
from ..ttl_service import TtlService

router = APIRouter(prefix="/api/model", tags=["model"])


class ImportBody(BaseModel):
    payload: dict
    replace: bool = True


class SiteBody(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)


def _model() -> ModelService:
    return ModelService()


def _ttl() -> TtlService:
    return TtlService()


def _require_site(model: dict) -> str:
    sites = model.get("sites") or []
    if not sites or not isinstance(sites[0], dict):
        raise HTTPException(
            status_code=400,
            detail="Configure a BRICK site first (Data Model tab → Site setup).",
        )
    sid = str(sites[0].get("id") or "").strip()
    if not sid:
        raise HTTPException(status_code=400, detail="Site id is missing — save a site on the Data Model tab.")
    return sid


@router.get("/export")
def export_model(_user: dict = Depends(require_user)) -> dict:
    svc = _model()
    ensure_default_site(svc, _ttl())
    return svc.load()


@router.get("/sites")
def list_sites(_user: dict = Depends(require_user)) -> dict:
    svc = _model()
    ttl = _ttl()
    sid = ensure_default_site(svc, ttl)
    model = svc.load()
    sites = [s for s in model.get("sites", []) if isinstance(s, dict)]
    return {"ok": True, "sites": sites, "configured": len(sites) > 0, "active_site_id": sid}


@router.get("/tree")
def model_tree(_user: dict = Depends(require_user)) -> dict:
    svc = _model()
    ensure_default_site(svc, _ttl())
    model = svc.load()
    equipment = [e for e in model.get("equipment", []) if isinstance(e, dict)]
    points = [p for p in model.get("points", []) if isinstance(p, dict)]
    brick_types = sorted(
        {str(p.get("brick_type") or "").strip() for p in points if str(p.get("brick_type") or "").strip()}
    )
    eq_types = sorted(
        {str(e.get("equipment_type") or "").strip() for e in equipment if str(e.get("equipment_type") or "").strip()}
    )
    return {
        "ok": True,
        "sites": model.get("sites") or [],
        "equipment": equipment,
        "points": points,
        "brick_types": brick_types,
        "equipment_types": eq_types,
    }


@router.post("/sites")
def upsert_site(body: SiteBody, _user: dict = Depends(require_roles("operator", "integrator", "agent"))) -> dict:
    sid = body.id.strip()
    with _model().transaction() as model:
        sites = model.setdefault("sites", [])
        for site in sites:
            if isinstance(site, dict) and str(site.get("id")) == sid:
                site["name"] = body.name.strip()
                break
        else:
            sites.insert(0, {"id": sid, "name": body.name.strip()})
    path = _ttl().sync()
    return {"ok": True, "site_id": sid, "ttl_path": str(path)}


@router.post("/import")
def import_model(body: ImportBody, user: dict = Depends(require_roles("integrator"))) -> dict:
    svc = _model()
    normalized = svc.normalize_import_payload(body.payload)
    _require_site(normalized)
    counts = svc.import_json(body.payload, replace=body.replace)
    _ttl().sync()
    return {"ok": True, **counts}


@router.get("/health")
def model_health(_user: dict = Depends(require_user)) -> dict:
    svc = _model()
    ensure_default_site(svc, _ttl())
    model = svc.load()
    health = model_health_summary(model)
    ttl = _ttl()
    ttl_exists = ttl.ttl_path.is_file()
    return {"ok": True, "ttl_exists": ttl_exists, "ttl_path": str(ttl.ttl_path), **health}


@router.get("/ttl")
def view_ttl(save: bool = False, _user: dict = Depends(require_user)) -> Response:
    ttl = _ttl()
    if save:
        path = ttl.sync()
        text = path.read_text(encoding="utf-8")
    else:
        text = ttl.build_ttl()
    return Response(content=text, media_type="text/turtle")


@router.post("/sync-ttl")
def sync_ttl(_user: dict = Depends(require_roles("integrator", "operator", "agent"))) -> dict:
    path = _ttl().sync()
    return {"ok": True, "path": str(path)}


@router.get("/bacnet-sync")
def bacnet_sync_status(_user: dict = Depends(require_user)) -> dict:
    from ..bacnet_poll_model_sync import bacnet_sync_status as _status

    svc = _model()
    ensure_default_site(svc, _ttl())
    return _status()


@router.post("/bacnet-sync")
def bacnet_sync_run(_user: dict = Depends(require_roles("integrator", "operator", "agent"))) -> dict:
    from ..bacnet_poll_model_sync import sync_enabled_polling_to_model

    ensure_default_site(_model(), _ttl())
    return sync_enabled_polling_to_model(sync_ttl=True)


@router.delete("/points/{point_id}")
def delete_point(
    point_id: str,
    disable_poll: bool = True,
    user: dict = Depends(require_roles("integrator", "operator", "agent")),
) -> dict:
    removed = _model().delete_point(point_id)
    if not removed:
        raise HTTPException(status_code=404, detail=f"point not found: {point_id}")
    poll_disabled = False
    if disable_poll:
        meta = removed.get("metadata") if isinstance(removed.get("metadata"), dict) else {}
        poll_pid = str(meta.get("point_id") or "").strip()
        if poll_pid:
            from ..bacnet_driver_store import set_point_poll

            set_point_poll(point_id=poll_pid, enabled=False)
            poll_disabled = True
    path = _ttl().sync()
    return {"ok": True, "deleted": point_id, "poll_disabled": poll_disabled, "ttl_path": str(path)}


@router.delete("/equipment/{equipment_id}")
def delete_equipment(
    equipment_id: str,
    user: dict = Depends(require_roles("integrator", "operator", "agent")),
) -> dict:
    counts = _model().delete_equipment(equipment_id, cascade_points=True)
    if counts["equipment_removed"] == 0:
        raise HTTPException(status_code=404, detail=f"equipment not found: {equipment_id}")
    path = _ttl().sync()
    return {"ok": True, "equipment_id": equipment_id, **counts, "ttl_path": str(path)}
