from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ..deps import require_user
from ..timeseries_api import list_plot_series, list_plot_sites, read_plot_series

router = APIRouter(prefix="/api/timeseries", tags=["timeseries"])


@router.get("/sites")
def timeseries_sites(_user: dict = Depends(require_user)) -> dict:
    return {"ok": True, "sites": list_plot_sites()}


@router.get("/series")
def timeseries_series(
    site_id: str = Query(..., min_length=1),
    source: str = Query(default="bacnet"),
    _user: dict = Depends(require_user),
) -> dict:
    return {"ok": True, **list_plot_series(site_id, source=source)}


@router.get("/plot")
def timeseries_plot(
    site_id: str = Query(..., min_length=1),
    columns: str = Query(default="", description="Comma-separated column names"),
    hours: int = Query(default=24, ge=1, le=168),
    source: str = Query(default="bacnet"),
    limit: int = Query(default=4000, ge=100, le=8000),
    _user: dict = Depends(require_user),
) -> dict:
    cols = [c.strip() for c in columns.split(",") if c.strip()]
    return {
        "ok": True,
        **read_plot_series(site_id, cols, source=source, hours=hours, limit=limit),
    }
