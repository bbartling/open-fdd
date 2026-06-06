"""Build rule column_map from JSON model points (BRICK / FDD keys → historian column names)."""

from __future__ import annotations

from typing import Any


def build_column_map_from_model_points(model: dict[str, Any], site_id: str) -> dict[str, str]:
    """
    Map logical point keys used in Python rules to historian column names (point ``external_id``).

    For each point on ``site_id``, registers:

    - ``brick_type`` → historian column (``external_id`` or ingest/plot fallback)
    - ``fdd_input`` → historian column (when set)

    Later keys overwrite earlier ones (last point wins for duplicate BRICK types on one site).
    """
    try:
        from openfdd_bridge.model_point_utils import point_historian_column, point_site_id
    except ImportError:
        point_historian_column = None  # type: ignore[assignment]
        point_site_id = None  # type: ignore[assignment]

    out: dict[str, str] = {}
    sid = str(site_id or "").strip()
    raw_points = model.get("points") if isinstance(model.get("points"), list) else []
    for p in raw_points:
        if not isinstance(p, dict):
            continue
        pt_sid = point_site_id(p, model) if point_site_id else str(p.get("site_id", "")).strip()
        if sid and pt_sid != sid:
            continue
        ext = str(p.get("external_id") or "").strip()
        if not ext and point_historian_column:
            ext = point_historian_column(p)
        if not ext:
            continue
        for key in (str(p.get("brick_type") or "").strip(), str(p.get("fdd_input") or "").strip()):
            if key:
                out[key] = ext
    return out
