"""Historian column catalog for RCx report point picker."""

from __future__ import annotations

from typing import Any

from portfolio.central.edge_registry import resolve_site_config, resolve_token
from portfolio.collector.edge_client import EdgeClient


def _plot_column(pt: dict[str, Any]) -> str:
    for key in ("timeseries_column", "historian_column", "fdd_input", "column", "brick_tag", "id"):
        val = str(pt.get(key) or "").strip()
        if val:
            return val
    return str(pt.get("name") or "").strip()


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
