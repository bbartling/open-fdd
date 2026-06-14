"""RCx report preview, generation, and persisted report downloads (read-only)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from ..rcx.chart_preview import build_rcx_preview, generate_rcx_docx
from ..rcx.rcx_points import list_report_point_tree, list_report_points
from ..rcx.report_store import list_reports, resolve_report, save_report
from ..rcx.workspace import get_workspace

router = APIRouter(prefix="/api/reports/rcx", tags=["reports"])


class RcxPreviewRequest(BaseModel):
    site_id: str = ""
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
    scope: str = "building"
    equipment_ids: list[str] = Field(default_factory=list)


class RcxGenerateRequest(RcxPreviewRequest):
    sections: list[str] = Field(default_factory=list)
    charts: list[str] = Field(default_factory=list)
    save_to_volume: bool = True


@router.get("/workspace")
def rcx_workspace(
    site_id: str = "",
    hours: int = 24,
    start: str | None = None,
    end: str | None = None,
    show_fault_overlays: bool = True,
) -> dict[str, Any]:
    return get_workspace(
        site_id=site_id,
        hours=hours,
        start=start,
        end=end,
        show_fault_overlays=show_fault_overlays,
    )


@router.get("/points")
def rcx_points(site_id: str = "", limit: int = 500) -> dict[str, Any]:
    return list_report_points(site_id, limit=limit)


@router.get("/point-tree")
def rcx_point_tree(site_id: str = "", limit: int = 500) -> dict[str, Any]:
    return list_report_point_tree(site_id, limit=limit)


@router.post("/preview")
def rcx_preview(body: RcxPreviewRequest) -> dict[str, Any]:
    """Data readiness preview and optional chart gallery for RCx Report Builder."""
    return build_rcx_preview(
        site_id=body.site_id,
        hours=body.hours,
        start=body.start,
        end=body.end,
        chart_ids=body.chart_ids or None,
        custom_columns=body.custom_columns or None,
        show_fault_overlays=body.show_fault_overlays,
        include_previews=body.include_previews,
        catalog_only=body.catalog_only,
        gallery_mode=body.gallery_mode,
        bundle_ids=body.bundle_ids or None,
        scope=body.scope,
        equipment_ids=body.equipment_ids or None,
    )


@router.post("/charts/preview")
def rcx_charts_preview(body: RcxPreviewRequest) -> dict[str, Any]:
    return rcx_preview(body)


@router.post("/generate")
def rcx_generate(body: RcxGenerateRequest) -> Response:
    """Generate downloadable RCx DOCX from selected sections/charts."""
    charts = body.charts or body.chart_ids or None
    try:
        docx_bytes, fname = generate_rcx_docx(
            site_id=body.site_id,
            hours=body.hours,
            start=body.start,
            end=body.end,
            sections=body.sections or None,
            charts=charts,
            custom_columns=body.custom_columns or None,
            show_fault_overlays=body.show_fault_overlays,
        )
    except ModuleNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail="Report generation requires python-docx (install bridge requirements).",
        ) from exc

    if body.save_to_volume:
        save_report(fname, docx_bytes)

    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/list")
def rcx_report_list(limit: int = 100) -> dict[str, Any]:
    reports = list_reports(limit=limit)
    return {"reports": reports, "count": len(reports)}


@router.get("/download/{filename}")
def rcx_report_download(filename: str) -> FileResponse:
    try:
        path = resolve_report(filename)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=path.name,
    )
