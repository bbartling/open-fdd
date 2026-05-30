"""Fixed fault-code catalog + live equipment fault tree (check-engine light).

Read endpoints are public so the building traffic-light dashboard works without
login on OT LAN wall displays. Writes stay behind integrator/agent auth.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..building_status import faults_by_family
from ..deps import require_user
from ..fault_catalog import catalog_payload, catalog_tree, entry_for_code

router = APIRouter(prefix="/api/faults", tags=["faults"])


@router.get("/catalog")
def get_catalog() -> dict:
    """The full fixed catalog: categories + per-family fault codes."""
    return {"ok": True, **catalog_payload()}


@router.get("/tree")
def get_catalog_tree() -> dict:
    """Reference tree: equipment family -> category -> fault codes (what CAN go wrong)."""
    return {"ok": True, **catalog_tree()}


@router.get("/code/{code}")
def get_code(code: str) -> dict:
    entry = entry_for_code(code)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"unknown fault code: {code}")
    return {"ok": True, "entry": entry}


@router.get("/status")
def get_status() -> dict:
    """Live GREEN/YELLOW/RED traffic + active faults grouped by equipment family."""
    return {"ok": True, **faults_by_family()}
