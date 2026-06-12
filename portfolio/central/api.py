"""FastAPI OpenFDD RCx Central — edge registry, analytics preview, RCx reports."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from portfolio.central.chart_preview import build_rcx_preview, generate_rcx_docx
from portfolio.central.edge_registry import (
    add_or_update_edge,
    delete_edge,
    list_edges_public,
    test_edge_connection,
)
from portfolio.central.fdd_analytics import build_fdd_analytics
from portfolio.central.mechanical_summary import build_mechanical_summary
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
    chart_ids: list[str] = Field(default_factory=list)
    show_fault_overlays: bool = True


class RcxReportBody(RcxPreviewBody):
    sections: list[str] = Field(default_factory=list)
    charts: list[str] = Field(default_factory=list)
    save_to_volume: bool = True


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
    try:
        return build_fdd_analytics(site_id, hours=hours)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/central/mechanical-summary/{site_id}")
def get_mechanical_summary(site_id: str, hours: int = 24) -> dict[str, Any]:
    try:
        return build_mechanical_summary(site_id, hours=hours)
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

@app.post("/api/central/rcx/preview")
def post_rcx_preview(body: RcxPreviewBody) -> dict[str, Any]:
    try:
        return build_rcx_preview(
            site_id=body.site_id,
            hours=body.hours,
            chart_ids=body.chart_ids or None,
            show_fault_overlays=body.show_fault_overlays,
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
        blob, fname = generate_rcx_docx(
            site_id=body.site_id,
            hours=body.hours,
            sections=body.sections or None,
            charts=body.charts or body.chart_ids or None,
        )
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
    from portfolio.central.rcx_report import build_rcx_docx as legacy_build

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

    blob = legacy_build(
        site_id=body.site_id,
        site_name=cfg.name,
        validation=validation,
        rollups=rollups,
        warnings=warnings,
    )
    filename = f"openfdd-rcx-{body.site_id}.docx"
    return Response(
        content=blob,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
