from __future__ import annotations

from fastapi import APIRouter, Depends

from ..deps import require_user
from ..host_stats import collect_host_stats

router = APIRouter(prefix="/api/host", tags=["host"])


@router.get("/stats")
def host_stats(_user: dict = Depends(require_user)) -> dict:
    return collect_host_stats()
