"""RCx report preview and DOCX generation (read-only)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..dashboard_analytics import build_rcx_preview

router = APIRouter(prefix="/api/reports/rcx", tags=["reports"])


class RcxPreviewRequest(BaseModel):
    site_id: str = ""
    hours: int = Field(default=24, ge=2, le=168)
    scope: str = "building"
    equipment_ids: list[str] = Field(default_factory=list)


class RcxGenerateRequest(RcxPreviewRequest):
    sections: list[str] = Field(default_factory=list)
    charts: list[str] = Field(default_factory=list)


@router.post("/preview")
def rcx_preview(body: RcxPreviewRequest) -> dict[str, Any]:
    """Data readiness preview for RCx Report Builder."""
    return build_rcx_preview(
        site_id=body.site_id,
        hours=body.hours,
        scope=body.scope,
        equipment_ids=body.equipment_ids,
    )


@router.post("/generate")
def rcx_generate(body: RcxGenerateRequest) -> Response:
    """Generate downloadable RCx DOCX from selected sections/charts."""
    preview = build_rcx_preview(
        site_id=body.site_id,
        hours=body.hours,
        scope=body.scope,
        equipment_ids=body.equipment_ids,
    )
    try:
        from open_fdd.reports.rcx_docx import build_rcx_docx
    except ImportError as exc:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=503,
            detail="Report generation requires python-docx (install bridge requirements).",
        ) from exc

    overview = {
        "active_faults": preview.get("fault_summary", {}).get("active_faults"),
        "total_fault_hours": preview.get("fault_summary", {}).get("total_fault_hours"),
        "model_health": preview.get("fault_summary"),
        "missing_roles": preview.get("missing_roles"),
    }
    try:
        docx_bytes = build_rcx_docx(
            site_id=body.site_id or str(preview.get("site") or ""),
            site_name=str(preview.get("site_name") or preview.get("site") or "Edge"),
            window=preview.get("window") or {},
            fault_rows=preview.get("fault_rows") or [],
            overview=overview,
            sections=body.sections or None,
            charts=body.charts or None,
            warnings=preview.get("warnings") or [],
        )
    except ModuleNotFoundError as exc:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=503,
            detail="Report generation requires python-docx (install bridge requirements).",
        ) from exc
    fname = f"openfdd-rcx-{body.site_id or 'edge'}.docx"
    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )
