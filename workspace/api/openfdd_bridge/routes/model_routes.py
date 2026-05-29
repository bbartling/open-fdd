"""BRICK data model import/export and TTL sync."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field

from ..deps import require_roles, require_user
from ..model_health import model_health_summary
from ..model_service import ModelService
from ..ttl_service import TtlService

router = APIRouter(prefix="/api/model", tags=["model"])


class ImportBody(BaseModel):
    payload: dict
    replace: bool = True


def _model() -> ModelService:
    return ModelService()


def _ttl() -> TtlService:
    return TtlService()


@router.get("/export")
def export_model(_user: dict = Depends(require_user)) -> dict:
    return _model().load()


@router.post("/import")
def import_model(body: ImportBody, user: dict = Depends(require_roles("integrator"))) -> dict:
    svc = _model()
    counts = svc.import_json(body.payload, replace=body.replace)
    _ttl().sync()
    return {"ok": True, **counts}


@router.get("/health")
def model_health(_user: dict = Depends(require_user)) -> dict:
    model = _model().load()
    health = model_health_summary(model)
    ttl = _ttl()
    ttl_exists = ttl.ttl_path.is_file()
    return {"ok": True, "ttl_exists": ttl_exists, "ttl_path": str(ttl.ttl_path), **health}


@router.get("/ttl")
def view_ttl(save: bool = False, _user: dict = Depends(require_roles("integrator", "agent"))) -> Response:
    ttl = _ttl()
    if save:
        path = ttl.sync()
        text = path.read_text(encoding="utf-8")
    else:
        text = ttl.build_ttl()
    return Response(content=text, media_type="text/turtle")


@router.post("/sync-ttl")
def sync_ttl(_user: dict = Depends(require_roles("integrator"))) -> dict:
    path = _ttl().sync()
    return {"ok": True, "path": str(path)}
