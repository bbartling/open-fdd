"""Resolve runtime site/column fields for GL36-style models missing point site_id."""

from __future__ import annotations

from typing import Any


def equipment_index(model: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for eq in model.get("equipment") or []:
        if isinstance(eq, dict):
            eid = str(eq.get("id") or "").strip()
            if eid:
                out[eid] = eq
    return out


def default_site_id(model: dict[str, Any]) -> str:
    top = str(model.get("site_id") or "").strip()
    if top:
        return top
    sites = model.get("sites") or []
    if len(sites) == 1 and isinstance(sites[0], dict):
        return str(sites[0].get("id") or "").strip()
    return ""


def point_site_id(point: dict[str, Any], model: dict[str, Any]) -> str:
    """Point site_id, else parent equipment site_id, else single-site default."""
    sid = str(point.get("site_id") or "").strip()
    if sid:
        return sid
    eq = equipment_index(model).get(str(point.get("equipment_id") or "").strip())
    if isinstance(eq, dict):
        sid = str(eq.get("site_id") or "").strip()
        if sid:
            return sid
    return default_site_id(model)


def point_historian_column(point: dict[str, Any]) -> str:
    """Feather/CSV column name (matches bacnet ingest + plot tab)."""
    from .timeseries_api import plot_column_name

    return plot_column_name(point)


def enrich_point_runtime_fields(point: dict[str, Any], model: dict[str, Any]) -> dict[str, Any]:
    """Fill site_id / external_id for import and health without changing point ids."""
    pt = dict(point)
    sid = point_site_id(pt, model)
    if sid and not str(pt.get("site_id") or "").strip():
        pt["site_id"] = sid
    col = point_historian_column(pt)
    if col and not str(pt.get("external_id") or "").strip():
        pt["external_id"] = col
    return pt


def enrich_model_runtime_fields(model: dict[str, Any]) -> dict[str, Any]:
    """Return model copy with point site_id/external_id inferred where missing."""
    out = dict(model)
    points = []
    for raw in model.get("points") or []:
        if isinstance(raw, dict):
            points.append(enrich_point_runtime_fields(raw, model))
    out["points"] = points
    return out
