"""Fixed fault-code catalog + live equipment fault tree (check-engine light).

Catalog read endpoints stay public for analytics pages. Live status requires auth.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..building_status import faults_by_family
from ..deps import require_user
from ..fault_catalog import catalog_graph, catalog_payload, catalog_tree, entry_for_code
from ..fault_catalog_scope import build_applicable_payload, validate_scope_with_ollama

router = APIRouter(prefix="/api/faults", tags=["faults"])


@router.get("/catalog")
def get_catalog() -> dict:
    """The full fixed catalog: categories + per-family fault codes."""
    return {"ok": True, **catalog_payload()}


@router.get("/tree")
def get_catalog_tree() -> dict:
    """Reference tree: equipment family -> category -> fault codes (what CAN go wrong)."""
    return {"ok": True, **catalog_tree()}


@router.get("/applicable")
def get_applicable_catalog(site_id: str | None = None) -> dict:
    """Fault catalog scoped to BRICK equipment on a site (SPARQL + assigned rules)."""
    return build_applicable_payload(site_id)


@router.post("/validate-scope")
def post_validate_scope(body: dict | None = None) -> dict:
    """Ollama sanity-check of applicable fault families for the active site."""
    site_id = None
    if isinstance(body, dict):
        site_id = body.get("site_id")
    return validate_scope_with_ollama(site_id)


@router.get("/graph")
def get_catalog_graph() -> dict:
    """Link graph: fault_code → category → expression-rule cookbook pattern."""
    return {"ok": True, **catalog_graph()}


@router.get("/code/{code}")
def get_code(code: str) -> dict:
    entry = entry_for_code(code)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"unknown fault code: {code}")
    return {"ok": True, "entry": entry}


@router.get("/status")
def get_status(_user: dict = Depends(require_user)) -> dict:
    """Live GREEN/YELLOW/RED traffic + active faults grouped by equipment family."""
    return {"ok": True, **faults_by_family()}
