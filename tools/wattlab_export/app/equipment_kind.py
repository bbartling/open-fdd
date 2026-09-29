"""Stamp-only equipment kind helpers that do not import the Pydantic contract."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def infer_parent_ahu_from_path(eq_folder: Path, building_root: Path) -> str | None:
    """Parent AHU comes from a stamped map, not a folder name prefix."""
    _ = (eq_folder, building_root)
    return None


def is_vav_equipment(eq: dict[str, Any]) -> bool:
    from app.site_model import normalize_equipment_type

    raw = eq.get("equipment_type") or eq.get("equipType") or ""
    return normalize_equipment_type(str(raw)) == "VAV"
