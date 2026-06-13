"""Historian column catalog for RCx report point picker."""

from __future__ import annotations

from typing import Any

from portfolio.central.edge_registry import resolve_site_config, resolve_token
from portfolio.collector.edge_client import EdgeClient


from portfolio.central.trend_charts import historian_column_for_point


def _plot_column(pt: dict[str, Any]) -> str:
    return historian_column_for_point(pt)


def list_report_points(site_id: str, *, limit: int = 200) -> dict[str, Any]:
    """Return pollable columns from Edge model tree for ad-hoc trend charts."""
    site = resolve_site_config(site_id)
    client = EdgeClient(site.base_url)
    token = resolve_token(site)
    tree = client.get_model_tree(token=token)
    equipment_by_id = {
        str(e.get("id") or e.get("equipment_id") or ""): e
        for e in (tree.get("equipment") or [])
        if isinstance(e, dict)
    }
    rows: list[dict[str, Any]] = []
    for pt in tree.get("points") or []:
        if not isinstance(pt, dict):
            continue
        col = _plot_column(pt)
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
        "site_id": site_id,
        "count": len(rows),
        "points": rows,
    }


def list_report_point_tree(site_id: str, *, limit: int = 500) -> dict[str, Any]:
    """Group historian columns by equipment for tree-style Dash picker."""
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
        "site_id": site_id,
        "equipment_count": len(equipment),
        "point_count": flat.get("count") or 0,
        "equipment": equipment,
    }
