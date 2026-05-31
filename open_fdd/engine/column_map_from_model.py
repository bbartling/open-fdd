"""Build rule ``column_map`` from JSON model points (BRICK / FDD keys → CSV column names)."""

from __future__ import annotations

from typing import Any


def build_column_map_from_model_points(model: dict[str, Any], site_id: str) -> dict[str, str]:
    """
    Map logical point keys used in Python rules to DataFrame column names (point ``external_id``).

    For each point on ``site_id``, registers:

    - ``brick_type`` → ``external_id`` (when both non-empty)
    - ``fdd_input`` → ``external_id`` (when both non-empty; often equals BRICK class)

    Later keys overwrite earlier ones (last point wins for duplicate BRICK types on one site).
    """
    out: dict[str, str] = {}
    sid = str(site_id or "").strip()
    raw_points = model.get("points") if isinstance(model.get("points"), list) else []
    for p in raw_points:
        if not isinstance(p, dict):
            continue
        if sid and str(p.get("site_id", "")).strip() != sid:
            continue
        ext = str(p.get("external_id") or "").strip()
        if not ext:
            continue
        for key in (str(p.get("brick_type") or "").strip(), str(p.get("fdd_input") or "").strip()):
            if key:
                out[key] = ext
    return out
