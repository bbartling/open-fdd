"""BRICK data model import/export and TTL sync."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from ..audit import write_audit
from ..deps import require_roles, require_user
from ..model_access import require_model_mutation
from ..security import debug_diagnostics_enabled, operator_can_edit_model
from ..model_health import model_health_summary
from ..model_service import ModelService
from ..model_sparql import list_model_sites, query_model_graph, query_model_tree, scope_bundle
from ..sparql_queries import execute_model_sparql, predefined_catalog
from ..ttl_graph import TtlGraphError
from ..site_defaults import ensure_default_site
from ..ttl_service import TtlService

router = APIRouter(prefix="/api/model", tags=["model"])

_MODEL_MUTATION = Depends(require_model_mutation)


class ImportBody(BaseModel):
    payload: dict
    replace: bool = True


class SiteBody(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)


class SparqlBody(BaseModel):
    query: str = Field(min_length=1, max_length=200_000)


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
    sites = list_model_sites(model)
    return {"ok": True, "sites": sites, "configured": len(sites) > 0, "active_site_id": sid}


@router.get("/graph")
def model_graph(
    site_id: str | None = None,
    _user: dict = Depends(require_user),
) -> dict:
    """Site equipment, points, and brick:feeds edges — SPARQL over synced TTL."""
    svc = _model()
    ttl = _ttl()
    sid = (site_id or "").strip() or ensure_default_site(svc, ttl)
    try:
        return {"ok": True, **query_model_graph(sid)}
    except TtlGraphError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/scope")
def model_scope(
    site_id: str | None = None,
    equipment_id: str | None = None,
    brick_type: str | None = None,
    _user: dict = Depends(require_user),
) -> dict:
    """BRICK SPARQL scope for Rule Lab / plots — sites, equipment, sensors with timeseries columns."""
    svc = _model()
    ttl = _ttl()
    sid = (site_id or "").strip() or ensure_default_site(svc, ttl)
    try:
        return {"ok": True, **scope_bundle(sid, equipment_id=equipment_id, brick_type=brick_type)}
    except TtlGraphError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/tree")
def model_tree(_user: dict = Depends(require_user)) -> dict:
    """Full BRICK catalog — SPARQL SELECT over synced data_model.ttl."""
    svc = _model()
    ensure_default_site(svc, _ttl())
    try:
        return {"ok": True, **query_model_tree()}
    except TtlGraphError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/sites")
def upsert_site(body: SiteBody, user: dict = _MODEL_MUTATION) -> dict:
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
    write_audit(
        event_type="model.write",
        action="upsert_site",
        outcome="success",
        user=user,
        resource_type="site",
        resource_id=sid,
    )
    payload = {"ok": True, "site_id": sid, "ttl_synced": True}
    if debug_diagnostics_enabled():
        payload["ttl_path"] = str(path)
    return payload


@router.post("/import")
def import_model(body: ImportBody, user: dict = Depends(require_roles("integrator"))) -> dict:
    svc = _model()
    normalized = svc.normalize_import_payload(body.payload)
    _require_site(normalized)
    counts = svc.import_json(body.payload, replace=body.replace)
    _ttl().sync()
    return {"ok": True, **counts}


@router.get("/sparql/predefined")
def sparql_predefined(_user: dict = Depends(require_user)) -> dict:
    ensure_default_site(_model(), _ttl())
    return predefined_catalog()


@router.post("/sparql")
def run_model_sparql(body: SparqlBody, _user: dict = Depends(require_user)) -> dict:
    ensure_default_site(_model(), _ttl())
    return execute_model_sparql(body.query, _ttl())


@router.get("/health")
def model_health(_user: dict = Depends(require_user)) -> dict:
    svc = _model()
    ensure_default_site(svc, _ttl())
    model = svc.load()
    health = model_health_summary(model)
    ttl = _ttl()
    ttl_exists = ttl.ttl_path.is_file()
    payload: dict = {"ok": True, "ttl_exists": ttl_exists, "ttl_configured": ttl_exists, **health}
    if debug_diagnostics_enabled():
        payload["ttl_path"] = str(ttl.ttl_path)
    return payload


@router.get("/ttl")
def view_ttl(
    save: bool = False,
    user: dict = Depends(require_user),
) -> Response:
    ttl = _ttl()
    if save:
        if user.get("role") != "integrator" and not operator_can_edit_model():
            raise HTTPException(status_code=403, detail="saving TTL requires integrator role")
        path = ttl.sync()
        write_audit(
            event_type="model.write",
            action="save_ttl",
            outcome="success",
            user=user,
            resource_type="ttl",
        )
        text = path.read_text(encoding="utf-8")
    else:
        text = ttl.build_ttl()
    return Response(content=text, media_type="text/turtle")


@router.post("/sync-ttl")
def sync_ttl(user: dict = _MODEL_MUTATION) -> dict:
    path = _ttl().sync()
    write_audit(
        event_type="model.write",
        action="sync_ttl",
        outcome="success",
        user=user,
        resource_type="ttl",
    )
    payload = {"ok": True, "ttl_synced": True}
    if debug_diagnostics_enabled():
        payload["path"] = str(path)
    return payload


@router.get("/bacnet-sync")
def bacnet_sync_status(_user: dict = Depends(require_user)) -> dict:
    from ..bacnet_poll_model_sync import bacnet_sync_status as _status

    svc = _model()
    ensure_default_site(svc, _ttl())
    return _status()


@router.post("/bacnet-sync")
def bacnet_sync_run(user: dict = _MODEL_MUTATION) -> dict:
    from ..bacnet_poll_model_sync import sync_enabled_polling_to_model

    ensure_default_site(_model(), _ttl())
    result = sync_enabled_polling_to_model(sync_ttl=True)
    write_audit(
        event_type="model.write",
        action="bacnet_sync",
        outcome="success",
        user=user,
        resource_type="model",
    )
    return result


@router.delete("/points/{point_id}")
def delete_point(
    point_id: str,
    disable_poll: bool = True,
    user: dict = _MODEL_MUTATION,
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
    from ..rule_store import RuleStore

    bindings_pruned = RuleStore().prune_bindings(point_ids=[point_id])
    path = _ttl().sync()
    write_audit(
        event_type="model.write",
        action="delete_point",
        outcome="success",
        user=user,
        resource_type="point",
        resource_id=point_id,
    )
    payload = {
        "ok": True,
        "deleted": point_id,
        "poll_disabled": poll_disabled,
        "bindings_pruned": bindings_pruned,
        "ttl_synced": True,
    }
    if debug_diagnostics_enabled():
        payload["ttl_path"] = str(path)
    return payload


@router.delete("/equipment/{equipment_id}")
def delete_equipment(
    equipment_id: str,
    user: dict = _MODEL_MUTATION,
) -> dict:
    svc = _model()
    model = svc.load()
    removed_point_ids = [
        str(p.get("id") or "")
        for p in (model.get("points") or [])
        if isinstance(p, dict) and str(p.get("equipment_id") or "") == equipment_id
    ]
    counts = svc.delete_equipment(equipment_id, cascade_points=True)
    if counts["equipment_removed"] == 0:
        raise HTTPException(status_code=404, detail=f"equipment not found: {equipment_id}")
    from ..rule_store import RuleStore

    bindings_pruned = RuleStore().prune_bindings(
        point_ids=removed_point_ids,
        equipment_ids=[equipment_id],
    )
    path = _ttl().sync()
    write_audit(
        event_type="model.write",
        action="delete_equipment",
        outcome="success",
        user=user,
        resource_type="equipment",
        resource_id=equipment_id,
    )
    payload = {
        "ok": True,
        "equipment_id": equipment_id,
        **counts,
        "bindings_pruned": bindings_pruned,
        "ttl_synced": True,
    }
    if debug_diagnostics_enabled():
        payload["ttl_path"] = str(path)
    return payload
