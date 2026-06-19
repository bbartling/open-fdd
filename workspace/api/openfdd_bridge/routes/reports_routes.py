"""RCx report preview, generation, and persisted report downloads (read-only)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from ..deps import require_roles, require_user
from ..rcx.chart_preview import build_rcx_preview, generate_rcx_docx
from ..rcx.rcx_intent import generate_rcx_report_from_intent, plan_rcx_report_intent
from ..rcx.rcx_points import list_report_point_tree, list_report_points
from ..rcx.report_store import delete_report, list_reports, resolve_report, save_report
from ..rcx.workspace import get_workspace

router = APIRouter(prefix="/api/reports/rcx", tags=["reports"])

_WRITE = Depends(require_roles("integrator", "agent"))


class RcxPreviewRequest(BaseModel):
    site_id: str = ""
    hours: int = Field(default=24, ge=2, le=8760)
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
    include_previews: bool = False


class RcxIntentRequest(BaseModel):
    site_id: str = ""
    hours: int = Field(default=168, ge=2, le=8760)
    start: str | None = None
    end: str | None = None
    sensors: list[str] = Field(default_factory=list, description="Labels, columns, or point ids")
    sensor_columns: list[str] = Field(default_factory=list)
    show_fault_overlays: bool = True
    bundle_ids: list[str] = Field(default_factory=list)
    equipment_ids: list[str] = Field(default_factory=list)
    sections: list[str] = Field(default_factory=list)
    charts: list[str] = Field(default_factory=list)
    include_analytics: bool = True
    include_previews: bool = True
    save_to_volume: bool = True
    return_docx: bool = False


@router.get("/workspace")
def rcx_workspace(
    site_id: str = "",
    hours: int = 24,
    start: str | None = None,
    end: str | None = None,
    show_fault_overlays: bool = True,
    _user: dict = Depends(require_user),
) -> dict[str, Any]:
    return get_workspace(
        site_id=site_id,
        hours=hours,
        start=start,
        end=end,
        show_fault_overlays=show_fault_overlays,
    )


@router.get("/points")
def rcx_points(site_id: str = "", limit: int = 500, _user: dict = Depends(require_user)) -> dict[str, Any]:
    return list_report_points(site_id, limit=limit)


@router.get("/point-tree")
def rcx_point_tree(site_id: str = "", limit: int = 500, _user: dict = Depends(require_user)) -> dict[str, Any]:
    return list_report_point_tree(site_id, limit=limit)


@router.post("/preview")
def rcx_preview(body: RcxPreviewRequest, _user: dict = Depends(require_user)) -> dict[str, Any]:
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
def rcx_charts_preview(body: RcxPreviewRequest, _user: dict = Depends(require_user)) -> dict[str, Any]:
    return rcx_preview(body)


@router.post("/generate")
def rcx_generate(body: RcxGenerateRequest, _user: dict = Depends(require_user)) -> Response:
    """Generate downloadable RCx DOCX from selected sections/charts."""
    charts = [str(c).strip() for c in (body.charts or body.chart_ids or []) if c and str(c).strip()]
    sections = [str(s).strip() for s in (body.sections or []) if s and str(s).strip()]
    bundle_ids = [str(b).strip() for b in (body.bundle_ids or []) if b and str(b).strip()]
    try:
        docx_bytes, fname = generate_rcx_docx(
            site_id=body.site_id,
            hours=body.hours,
            start=body.start,
            end=body.end,
            sections=sections or None,
            charts=charts or None,
            custom_columns=body.custom_columns or None,
            show_fault_overlays=body.show_fault_overlays,
            bundle_ids=bundle_ids or None,
            equipment_ids=body.equipment_ids or None,
            include_previews=body.include_previews,
        )
    except ModuleNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail="Report generation requires python-docx (install bridge requirements).",
        ) from exc

    if body.save_to_volume:
        save_report(fname, docx_bytes)

    headers = {"Content-Disposition": f'attachment; filename="{fname}"'}
    if body.save_to_volume:
        headers["X-OpenFDD-Saved-Filename"] = fname

    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers=headers,
    )


@router.post("/generate-intent")
def rcx_generate_intent(body: RcxIntentRequest, _user: dict = Depends(require_user)):
    """Single-shot RCx report from natural-language sensor list (chat/agent friendly)."""
    try:
        result = generate_rcx_report_from_intent(
            site_id=body.site_id,
            hours=body.hours,
            start=body.start,
            end=body.end,
            sensors=body.sensors or None,
            sensor_columns=body.sensor_columns or None,
            show_fault_overlays=body.show_fault_overlays,
            bundle_ids=body.bundle_ids or None,
            equipment_ids=body.equipment_ids or None,
            sections=body.sections or None,
            charts=body.charts or None,
            include_analytics=body.include_analytics,
            include_previews=body.include_previews,
            save_to_volume=body.save_to_volume,
        )
    except ModuleNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail="Report generation requires python-docx (install bridge requirements).",
        ) from exc

    if body.return_docx:
        from ..rcx.report_store import resolve_report

        path = resolve_report(result["filename"])
        return FileResponse(
            path,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            filename=path.name,
        )
    return result


@router.post("/intent/preview")
def rcx_intent_preview(body: RcxIntentRequest, _user: dict = Depends(require_user)) -> dict[str, Any]:
    """Plan RCx report (sections, charts, sensor resolution) without generating DOCX."""
    return plan_rcx_report_intent(
        site_id=body.site_id,
        hours=body.hours,
        start=body.start,
        end=body.end,
        sensors=body.sensors or None,
        sensor_columns=body.sensor_columns or None,
        show_fault_overlays=body.show_fault_overlays,
        bundle_ids=body.bundle_ids or None,
        equipment_ids=body.equipment_ids or None,
        include_analytics=body.include_analytics,
    )


@router.get("/list")
def rcx_report_list(limit: int = 100, _user: dict = Depends(require_user)) -> dict[str, Any]:
    reports = list_reports(limit=limit)
    return {"reports": reports, "count": len(reports), "reports_dir": "workspace/reports/rcx"}


@router.get("/download/{filename}")
def rcx_report_download(filename: str, _user: dict = Depends(require_user)) -> FileResponse:
    try:
        path = resolve_report(filename)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=path.name,
    )


@router.get("/preview/{filename}")
def rcx_report_preview(filename: str, _user: dict = Depends(require_user)) -> FileResponse:
    """Inline DOCX for browser preview (docx-preview widget)."""
    try:
        path = resolve_report(filename)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=path.name,
        headers={"Content-Disposition": f'inline; filename="{path.name}"'},
    )


@router.delete("/{filename}", dependencies=[_WRITE])
def rcx_report_delete(filename: str) -> dict[str, Any]:
    try:
        delete_report(filename)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True, "deleted": Path(filename).name}
