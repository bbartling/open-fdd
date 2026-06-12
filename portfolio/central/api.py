"""FastAPI Central desk — edge registry, validation jobs, RCx reports."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from portfolio.central.registry import list_edge_sites
from portfolio.central.validation import (
    collect_and_validate,
    run_one_off_validation,
    run_validation_plan,
)
from portfolio.central.job_store import list_jobs, load_job
from portfolio.central.rcx_report import build_rcx_docx
from portfolio.central.registry import site_config_for

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SITES = ROOT / "sites.json"
DEFAULT_DATA = ROOT / "data"

app = FastAPI(title="Open-FDD Central", version="0.1.0")


class ValidationPlanBody(BaseModel):
    site_id: str = Field(min_length=1)
    interval_hours: float = Field(default=2.0, gt=0, le=24)
    duration_hours: float = Field(default=24.0, gt=0, le=168)
    sleep_seconds: float = Field(
        default=0.0,
        ge=0,
        description="Wall-clock sleep between cycles (0=try-out)",
    )


class RcxReportBody(BaseModel):
    site_id: str = Field(min_length=1)
    include_validation: bool = True


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "openfdd-central"}


@app.get("/api/central/sites")
def get_sites() -> dict[str, Any]:
    sites = [s.to_dict() for s in list_edge_sites(sites_path=DEFAULT_SITES, data_dir=DEFAULT_DATA)]
    return {"sites": sites, "count": len(sites)}


@app.post("/api/central/sites/{site_id}/collect-validate")
def post_collect_validate(site_id: str) -> dict[str, Any]:
    try:
        return collect_and_validate(
            site_id, sites_path=DEFAULT_SITES, data_dir=DEFAULT_DATA
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/central/validation/run")
def post_validation_run(body: ValidationPlanBody) -> dict[str, Any]:
    try:
        if body.duration_hours <= 0:
            return run_one_off_validation(
                body.site_id, sites_path=DEFAULT_SITES, data_dir=DEFAULT_DATA
            )
        return run_validation_plan(
            body.site_id,
            interval_hours=body.interval_hours,
            duration_hours=body.duration_hours,
            sleep_seconds=body.sleep_seconds,
            sites_path=DEFAULT_SITES,
            data_dir=DEFAULT_DATA,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/central/validation/jobs")
def get_validation_jobs() -> dict[str, Any]:
    jobs = list_jobs(data_dir=DEFAULT_DATA)
    return {"jobs": jobs, "count": len(jobs)}


@app.get("/api/central/validation/jobs/{job_id}")
def get_validation_job(job_id: str) -> dict[str, Any]:
    try:
        return load_job(job_id, data_dir=DEFAULT_DATA)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="job not found") from exc


@app.post("/api/central/rcx/report")
def post_rcx_report(body: RcxReportBody) -> Response:
    try:
        cfg = site_config_for(body.site_id, sites_path=DEFAULT_SITES)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    validation = None
    warnings: list[str] = []
    if body.include_validation:
        validation = run_one_off_validation(
            body.site_id, sites_path=DEFAULT_SITES, data_dir=DEFAULT_DATA
        )
        if not validation.get("ok"):
            warnings.extend(validation.get("errors") or [])

    latest_path = DEFAULT_DATA / "latest" / f"{body.site_id}.json"
    rollups: list[dict[str, Any]] = []
    if latest_path.is_file():
        import json

        rollups.append(json.loads(latest_path.read_text(encoding="utf-8")))
    else:
        warnings.append("No latest rollup JSON — run portfolio collect first.")

    blob = build_rcx_docx(
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
