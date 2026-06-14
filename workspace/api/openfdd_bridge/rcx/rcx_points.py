"""Historian column catalog for RCx report point picker."""

from __future__ import annotations

from typing import Any

from ..model_service import ModelService
from ..model_sparql import query_model_tree
from ..site_defaults import default_site_id, ensure_default_site
from ..ttl_service import TtlService
from .trend_charts import historian_column_for_point


def _resolve_site_id(site_id: str) -> str:
    sid = str(site_id or "").strip()
    if sid:
        return sid
    svc = ModelService()
    return ensure_default_site(svc, TtlService()) or default_site_id()


def list_report_points(site_id: str, *, limit: int = 200) -> dict[str, Any]:
    """Return pollable columns from local model tree for ad-hoc trend charts."""
    sid = _resolve_site_id(site_id)
    tree = query_model_tree()
    equipment_by_id = {
        str(e.get("id") or e.get("equipment_id") or ""): e
        for e in (tree.get("equipment") or [])
        if isinstance(e, dict)
    }
    rows: list[dict[str, Any]] = []
    for pt in tree.get("points") or []:
        if not isinstance(pt, dict):
            continue
        col = historian_column_for_point(pt)
        if not col:
            continue
        eid = str(pt.get("equipment_id") or "")
        equip = equipment_by_id.get(eid) or {}
        rows.append(
            {
                "column": col,
                "label": str(pt.get("name") or col),
                "brick_type": str(pt.get("brick_type") or ""),
                "equipment_id": eid,
                "equipment_name": str(equip.get("name") or eid),
                "units": str(pt.get("units") or ""),
                "point_id": str(pt.get("id") or ""),
            }
        )
    rows.sort(key=lambda r: (r.get("equipment_name") or "", r.get("label") or ""))
    if limit > 0:
        rows = rows[:limit]
    return {
        "site_id": sid,
        "count": len(rows),
        "points": rows,
    }


def list_report_point_tree(site_id: str, *, limit: int = 500) -> dict[str, Any]:
    """Group historian columns by equipment for tree-style picker."""
    flat = list_report_points(site_id, limit=limit)
    by_equipment: dict[str, list[dict[str, Any]]] = {}
    for pt in flat.get("points") or []:
        eq = str(pt.get("equipment_name") or pt.get("equipment_id") or "Unassigned")
        by_equipment.setdefault(eq, []).append(pt)

    equipment = []
    for name in sorted(by_equipment.keys(), key=lambda s: s.lower()):
        pts = by_equipment[name]
        equipment.append(
            {
                "equipment_name": name,
                "equipment_id": str(pts[0].get("equipment_id") or name),
                "point_count": len(pts),
                "points": pts,
            }
        )
    return {
        "site_id": flat.get("site_id"),
        "equipment_count": len(equipment),
        "point_count": flat.get("count") or 0,
        "equipment": equipment,
    }
