"""FastAPI OpenFDD RCx Central — edge registry, analytics preview, RCx reports."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from portfolio.central.fdd_analytics import build_fdd_analytics
from portfolio.central.model_tree import build_model_tree_summary
from portfolio.central.edge_registry import (
    add_or_update_edge,
    delete_edge,
    list_edges_public,
    test_edge_connection,
)
from portfolio.central.overview_cache import cache_ttl_seconds, get_or_set
from portfolio.central.overview_data import build_overview
from portfolio.central.paths import data_dir, reports_dir, sites_path
from portfolio.central.registry import list_edge_sites, site_config_for, touch_site
from portfolio.central.validation import (
    collect_and_validate,
    run_one_off_validation,
    run_validation_plan,
)
from portfolio.central.job_store import list_jobs, load_job

app = FastAPI(title="OpenFDD RCx Central", version="0.2.0")

_DATA = data_dir()
_SITES = sites_path()


class ValidationPlanBody(BaseModel):
    site_id: str = Field(min_length=1)
    interval_hours: float = Field(default=2.0, gt=0, le=24)
    duration_hours: float = Field(default=24.0, gt=0, le=168)
    sleep_seconds: float = Field(default=0.0, ge=0)


class EdgeBody(BaseModel):
    site_id: str = Field(min_length=1)
    name: str = ""
    base_url: str = Field(min_length=8)
    auth_type: str = "password"
    username: str = "agent"
    password: str = ""
    token: str = ""


class EdgeTestBody(BaseModel):
    site_id: str = ""
    base_url: str = ""
    auth_type: str = "password"
    username: str = "agent"
    password: str = ""
    token: str = ""


class RcxPreviewBody(BaseModel):
    site_id: str = Field(min_length=1)
    hours: int = Field(default=24, ge=2, le=168)
    start: str | None = None
    end: str | None = None
    chart_ids: list[str] = Field(default_factory=list)
    custom_columns: list[str] = Field(default_factory=list)
    show_fault_overlays: bool = True
    include_previews: bool = True
    catalog_only: bool = False
    gallery_mode: bool = False
    bundle_ids: list[str] = Field(default_factory=list)


class RcxWorkspaceQuery(BaseModel):
    hours: int = Field(default=24, ge=2, le=168)
    start: str | None = None
    end: str | None = None
    show_fault_overlays: bool = True


class RcxReportBody(RcxPreviewBody):
    sections: list[str] = Field(default_factory=list)
    charts: list[str] = Field(default_factory=list)
    save_to_volume: bool = True


class SparqlBody(BaseModel):
    query: str = Field(min_length=1)
    query_id: str = ""


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "openfdd-rcx-central"}


# --- Edge registry (browser auth) ---

@app.get("/api/central/edges")
def get_edges() -> dict[str, Any]:
    return {"edges": list_edges_public(), "count": len(list_edges_public())}


@app.post("/api/central/edges")
def post_edge(body: EdgeBody) -> dict[str, Any]:
    try:
        edges = add_or_update_edge(
            site_id=body.site_id,
            name=body.name,
            base_url=body.base_url,
            auth_type=body.auth_type,
            username=body.username,
            password=body.password,
            token=body.token,
        )
        return {"ok": True, "edges": edges}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/central/edges/test")
def post_edge_test(body: EdgeTestBody) -> dict[str, Any]:
    try:
        return test_edge_connection(
            site_id=body.site_id or None,
            base_url=body.base_url or None,
            auth_type=body.auth_type,
            username=body.username,
            password=body.password,
            token=body.token,
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.put("/api/central/edges/{site_id}")
def put_edge(site_id: str, body: EdgeBody) -> dict[str, Any]:
    body.site_id = site_id
    return post_edge(body)


@app.delete("/api/central/edges/{site_id}")
def remove_edge(site_id: str) -> dict[str, Any]:
    delete_edge(site_id)
    return {"ok": True, "site_id": site_id}


# --- Sites (legacy + state) ---

@app.get("/api/central/sites")
def get_sites() -> dict[str, Any]:
    sites = [s.to_dict() for s in list_edge_sites(sites_path=_SITES, data_dir=_DATA)]
    return {"sites": sites, "count": len(sites)}


@app.get("/api/central/fdd-analytics/{site_id}")
def get_fdd_analytics(site_id: str, hours: int = 24) -> dict[str, Any]:
    ttl = cache_ttl_seconds()

    def _build() -> dict[str, Any]:
        return build_fdd_analytics(site_id, hours=hours)

    try:
        data, from_cache = get_or_set(f"fdd-analytics:{site_id}:{hours}", ttl, _build)
        return {**data, "_cache": {"hit": from_cache, "ttl_s": ttl}}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/central/fdd-preset/{site_id}/{preset_id}")
def get_fdd_preset(site_id: str, preset_id: str) -> dict[str, Any]:
    try:
        from portfolio.central.edge_registry import resolve_site_config, resolve_token
        from portfolio.collector.edge_client import EdgeClient

        site = resolve_site_config(site_id)
        client = EdgeClient(site.base_url)
        token = resolve_token(site)
        raw = client.get_fdd_query_preset(preset_id, token=token)
        from portfolio.central.fdd_preset_enrich import enrich_fdd_preset

        return enrich_fdd_preset(preset_id, raw, client=client, token=token)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/central/overview/{site_id}")
def get_overview(site_id: str, live: bool = True, fast: bool = True) -> dict[str, Any]:
    ttl = cache_ttl_seconds()

    def _build() -> dict[str, Any]:
        return build_overview(site_id, include_live=live, fast=fast)

    try:
        data, from_cache = get_or_set(f"overview:{site_id}:live={live}:fast={fast}", ttl, _build)
        return {**data, "_cache": {"hit": from_cache, "ttl_s": ttl}}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/central/model-tree/{site_id}")
def get_model_tree(site_id: str, include_tree: bool = False) -> dict[str, Any]:
    """On-demand full BRICK model graph — slow on large remote Edge sites."""
    ttl = max(cache_ttl_seconds(), 300)

    def _build() -> dict[str, Any]:
        return build_model_tree_summary(site_id, include_tree=include_tree)

    try:
        data, from_cache = get_or_set(
            f"model-tree:{site_id}:full={include_tree}",
            ttl,
            _build,
        )
        return {**data, "_cache": {"hit": from_cache, "ttl_s": ttl}}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/central/model/remediate-hvac/{site_id}")
def post_remediate_hvac(site_id: str, dry_run: bool = False) -> dict[str, Any]:
    try:
        from portfolio.central.model_remediate import remediate_hvac_equipment

        return remediate_hvac_equipment(site_id, dry_run=dry_run)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/central/model/remediate/{site_id}")
def post_remediate_model(site_id: str, dry_run: bool = False) -> dict[str, Any]:
    """Full Edge model.json fix: equipment brick types + BACnet device ids on points + TTL sync."""
    try:
        from portfolio.central.model_remediate import remediate_full_model

        return remediate_full_model(site_id, dry_run=dry_run)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/central/model/sync-ttl/{site_id}")
def post_sync_site_ttl(site_id: str, sync_edge: bool = True) -> dict[str, Any]:
    """Mirror Edge data_model.ttl to Central for local SPARQL validation."""
    try:
        from portfolio.central.model_ttl_mirror import mirror_site_ttl

        return mirror_site_ttl(site_id, sync_edge=sync_edge)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/central/model/ttl/{site_id}")
def get_site_ttl_status(site_id: str) -> dict[str, Any]:
    try:
        from portfolio.central.model_ttl_mirror import ttl_mirror_status

        return ttl_mirror_status(site_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/central/model/sparql/predefined/{site_id}")
def get_site_sparql_predefined(site_id: str) -> dict[str, Any]:
    try:
        from portfolio.central.model_sparql_local import predefined_catalog

        return predefined_catalog(site_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/central/model/sparql/{site_id}")
def post_site_sparql(site_id: str, body: SparqlBody) -> dict[str, Any]:
    try:
        from portfolio.central.model_sparql_local import execute_site_sparql, predefined_catalog

        query = body.query.strip()
        if not query and body.query_id:
            catalog = predefined_catalog(site_id)
            match = next(
                (q for q in (catalog.get("queries") or []) if str(q.get("id")) == body.query_id),
                None,
            )
            if match is None:
                raise HTTPException(status_code=404, detail=f"unknown query_id: {body.query_id}")
            query = str(match.get("query") or "")
        if not query:
            raise HTTPException(status_code=400, detail="query or query_id required")
        return execute_site_sparql(site_id, query)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except HTTPException:
        raise
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/central/model/sparql/validate/{site_id}")
def get_site_sparql_validate(site_id: str, sync_if_missing: bool = True) -> dict[str, Any]:
    try:
        from portfolio.central.model_sparql_local import validate_site_model

        return validate_site_model(site_id, sync_if_missing=sync_if_missing)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/central/mechanical-summary/{site_id}")
def get_mechanical_summary(site_id: str, hours: int = 24) -> dict[str, Any]:
    try:
        from portfolio.central.rcx_proxy import rcx_mechanical_narrative, rcx_mechanical_summary

        summary = rcx_mechanical_summary(site_id, hours=hours)
        try:
            narrative = rcx_mechanical_narrative(site_id)
            summary["mechanical_narrative"] = narrative.get("narrative")
            summary["mechanical_counts"] = narrative.get("counts")
            summary["narrative"] = narrative.get("narrative")
            summary["counts"] = narrative.get("counts")
        except RuntimeError as exc:
            summary.setdefault("warnings", []).append(str(exc)[:200])
        return summary
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/central/sites/{site_id}/collect-validate")
def post_collect_validate(site_id: str) -> dict[str, Any]:
    try:
        return collect_and_validate(site_id, sites_path=_SITES, data_dir=_DATA)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/central/validation/run")
def post_validation_run(body: ValidationPlanBody) -> dict[str, Any]:
    try:
        if body.duration_hours <= 0:
            return run_one_off_validation(body.site_id, sites_path=_SITES, data_dir=_DATA)
        return run_validation_plan(
            body.site_id,
            interval_hours=body.interval_hours,
            duration_hours=body.duration_hours,
            sleep_seconds=body.sleep_seconds,
            sites_path=_SITES,
            data_dir=_DATA,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/central/validation/jobs")
def get_validation_jobs() -> dict[str, Any]:
    jobs = list_jobs(data_dir=_DATA)
    return {"jobs": jobs, "count": len(jobs)}


@app.get("/api/central/validation/jobs/{job_id}")
def get_validation_job(job_id: str) -> dict[str, Any]:
    try:
        return load_job(job_id, data_dir=_DATA)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="job not found") from exc


# --- RCx preview + report ---

@app.get("/api/central/rcx/workspace/{site_id}")
def get_rcx_workspace(
    site_id: str,
    hours: int = 24,
    start: str | None = None,
    end: str | None = None,
    show_fault_overlays: bool = True,
) -> dict[str, Any]:
    try:
        from portfolio.central.rcx_proxy import rcx_workspace

        return rcx_workspace(
            site_id,
            hours=hours,
            start=start,
            end=end,
            show_fault_overlays=show_fault_overlays,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/central/rcx/points/{site_id}")
def get_rcx_points(site_id: str, limit: int = 500) -> dict[str, Any]:
    try:
        from portfolio.central.rcx_proxy import rcx_points

        return rcx_points(site_id, limit=limit)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/central/rcx/point-tree/{site_id}")
def get_rcx_point_tree(site_id: str, limit: int = 500) -> dict[str, Any]:
    try:
        from portfolio.central.rcx_proxy import rcx_point_tree

        return rcx_point_tree(site_id, limit=limit)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/central/rcx/preview")
def post_rcx_preview(body: RcxPreviewBody) -> dict[str, Any]:
    try:
        from portfolio.central.rcx_proxy import rcx_preview

        return rcx_preview(
            body.site_id,
            body.model_dump(exclude_none=True),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/central/rcx/charts/preview")
def post_charts_preview(body: RcxPreviewBody) -> dict[str, Any]:
    return post_rcx_preview(body)


@app.post("/api/central/rcx/report")
def post_rcx_report(body: RcxReportBody) -> Response:
    try:
        from portfolio.central.rcx_proxy import rcx_report

        payload = body.model_dump(exclude_none=True)
        if body.charts or body.chart_ids:
            payload["charts"] = body.charts or body.chart_ids
        blob, fname = rcx_report(body.site_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ModuleNotFoundError as exc:
        raise HTTPException(status_code=503, detail="python-docx required") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if body.save_to_volume:
        out = reports_dir() / fname
        out.write_bytes(blob)

    return Response(
        content=blob,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


# Legacy RCx endpoint (backward compatible)
class RcxReportBodyLegacy(BaseModel):
    site_id: str = Field(min_length=1)
    include_validation: bool = True


@app.post("/api/central/rcx/report-legacy")
def post_rcx_report_legacy(body: RcxReportBodyLegacy) -> Response:
    try:
        from open_fdd.reports.rcx_docx import build_rcx_docx
    except ImportError as exc:
        raise HTTPException(status_code=503, detail="python-docx required") from exc

    try:
        cfg = site_config_for(body.site_id, sites_path=_SITES)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    validation = None
    warnings: list[str] = []
    if body.include_validation:
        validation = run_one_off_validation(body.site_id, sites_path=_SITES, data_dir=_DATA)
        if not validation.get("ok"):
            warnings.extend(validation.get("errors") or [])

    latest_path = _DATA / "latest" / f"{body.site_id}.json"
    rollups: list[dict[str, Any]] = []
    if latest_path.is_file():
        import json

        rollups.append(json.loads(latest_path.read_text(encoding="utf-8")))
    else:
        warnings.append("No latest rollup JSON — run collect first.")

    fault_rows: list[dict[str, Any]] = []
    if validation:
        from portfolio.central.fault_hours import fault_summary_from_validation

        fault_rows = fault_summary_from_validation(validation)

    blob = build_rcx_docx(
        site_id=body.site_id,
        site_name=cfg.name,
        window={},
        fault_rows=fault_rows,
        overview={"active_faults": len(fault_rows), "validation": validation, "rollups": rollups},
        sections=["executive_summary", "fault_analytics"],
        warnings=warnings,
    )
    filename = f"openfdd-rcx-{body.site_id}.docx"
    return Response(
        content=blob,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
