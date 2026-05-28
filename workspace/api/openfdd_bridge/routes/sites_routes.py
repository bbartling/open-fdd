from __future__ import annotations

from fastapi import APIRouter, Depends

from ..data_loader import load_demo_dataframe, records_from_dataframe
from ..deps import require_user

router = APIRouter(prefix="/api/sites", tags=["sites"], dependencies=[Depends(require_user)])

MAX_FRAME_LIMIT = 500
DEFAULT_FRAME_LIMIT = 200


@router.get("")
def list_sites() -> dict:
    df = load_demo_dataframe()
    site_ids = sorted(df["site_id"].unique().tolist()) if "site_id" in df.columns else ["demo"]
    return {
        "sites": [{"site_id": sid, "label": sid} for sid in site_ids],
    }


@router.get("/{site_id}/frame")
def site_frame(site_id: str, limit: int = DEFAULT_FRAME_LIMIT) -> dict:
    safe_limit = max(1, min(int(limit), MAX_FRAME_LIMIT))
    df = load_demo_dataframe(site_id)
    return {"site_id": site_id, "records": records_from_dataframe(df, limit=safe_limit)}
