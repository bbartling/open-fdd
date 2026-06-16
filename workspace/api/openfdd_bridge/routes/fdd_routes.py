"""FDD batch results API for rule tuning analytics."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ..deps import require_roles
from ..fdd_results import load_results

router = APIRouter(prefix="/api/fdd", tags=["fdd"])

_AGENT = Depends(require_roles("integrator", "agent"))


@router.get("/results")
def fdd_results(
    site_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    _user: dict = _AGENT,
) -> dict:
    """Latest FDD batch runs with per-rule analytics (tuning feedback)."""
    from ..fdd_equipment import enrich_fdd_run_with_equipment
    from ..model_service import ModelService

    doc = load_results()
    model = ModelService().load()
    runs = [r for r in doc.get("runs", []) if isinstance(r, dict)]
    if site_id:
        sid = site_id.strip()
        runs = [r for r in runs if str(r.get("site_id") or "") in {"", sid}]
    runs = [
        enrich_fdd_run_with_equipment(dict(r), model, str(r.get("site_id") or "").strip())
        for r in runs[-limit:]
    ]
    flagged = sum(1 for r in runs if int(r.get("flagged") or 0) > 0)
    errors = sum(1 for r in runs if r.get("status") == "error")
    return {
        "ok": True,
        "generated_at": doc.get("generated_at"),
        "site_id": site_id,
        "runs": runs,
        "summary": {
            "runs": len(runs),
            "flagged": flagged,
            "errors": errors,
        },
    }
