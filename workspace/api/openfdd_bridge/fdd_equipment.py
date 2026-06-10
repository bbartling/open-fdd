"""Map historian columns and FDD runs to BRICK equipment labels for operator alerts."""

from __future__ import annotations

from typing import Any

from .timeseries_api import historian_column_candidates, plot_column_name


def _equipment_index(model: dict[str, Any], site_id: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for eq in model.get("equipment") or []:
        if not isinstance(eq, dict):
            continue
        if str(eq.get("site_id") or "") not in {"", site_id}:
            continue
        eid = str(eq.get("id") or "").strip()
        if eid:
            out[eid] = eq
    return out


def column_to_equipment_map(model: dict[str, Any], site_id: str) -> dict[str, dict[str, str]]:
    """Historian column -> {equipment_id, equipment_name}."""
    eq_index = _equipment_index(model, site_id)
    mapping: dict[str, dict[str, str]] = {}
    for pt in model.get("points") or []:
        if not isinstance(pt, dict) or str(pt.get("site_id") or "") not in {"", site_id}:
            continue
        eid = str(pt.get("equipment_id") or "").strip()
        eq = eq_index.get(eid) or {}
        name = str(eq.get("name") or eid or "").strip()
        for col in historian_column_candidates(pt):
            if col and col not in mapping:
                mapping[col] = {"equipment_id": eid, "equipment_name": name}
        col = plot_column_name(pt)
        if col and col not in mapping:
            mapping[col] = {"equipment_id": eid, "equipment_name": name}
    return mapping


def equipment_labels_for_columns(
    model: dict[str, Any],
    site_id: str,
    columns: list[str] | None,
) -> list[str]:
    """Unique BAS equipment names for historian columns (preserves order)."""
    if not columns:
        return []
    col_map = column_to_equipment_map(model, site_id)
    seen: set[str] = set()
    out: list[str] = []
    for col in columns:
        key = str(col or "").strip()
        if not key:
            continue
        name = str((col_map.get(key) or {}).get("equipment_name") or "").strip()
        if name and name not in seen:
            seen.add(name)
            out.append(name)
    return out


def enrich_fdd_run_with_equipment(
    run: dict[str, Any],
    model: dict[str, Any],
    site_id: str,
) -> dict[str, Any]:
    """Attach equipment_names / equipment_id from flagged historian columns."""
    analytics = run.get("analytics") if isinstance(run.get("analytics"), dict) else {}
    cols = analytics.get("flagged_columns") or analytics.get("value_columns") or []
    if not cols and run.get("bound_columns"):
        cols = run.get("flagged_columns") or []
    if isinstance(cols, int):
        cols = []
    col_map = column_to_equipment_map(model, site_id)
    names = equipment_labels_for_columns(model, site_id, list(cols))
    ids: list[str] = []
    for col in cols:
        eid = str((col_map.get(str(col)) or {}).get("equipment_id") or "").strip()
        if eid and eid not in ids:
            ids.append(eid)
    if names:
        run = {**run, "equipment_names": names}
    if ids:
        run = {**run, "equipment_id": ids[0], "equipment_ids": ids}
        if len(ids) == 1:
            run.setdefault("equipment_name", names[0] if names else None)
    return run
