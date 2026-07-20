"""Per-equipment Haystack column-map sidecars next to historian CSVs.

Contract (equipment history only; weather optional):
Each ``history_wide.csv`` (or other equipment history CSV discovered by the loader)
must have a sibling JSON map. Accepted names (first match wins):

1. ``{stem}.json`` — e.g. ``history_wide.json``
2. ``{stem}.column_map.json`` — e.g. ``history_wide.column_map.json``
3. ``column_map.json`` in the same folder

JSON may be a full package map, a single-equip Haystack block, or a flat points dict.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.column_map_json import (
    empty_column_map,
    haystack_equip_type_to_cookbook,
    merge_column_map_into_role_map,
    normalize_column_map,
    normalize_point_roles,
)


class SidecarMapError(ValueError):
    """Missing or invalid per-CSV Haystack map."""


def sidecar_candidates(history_csv: Path) -> list[Path]:
    """Ordered candidate paths for a history CSV's Haystack map."""
    parent = history_csv.parent
    stem = history_csv.stem
    return [
        parent / f"{stem}.json",
        parent / f"{stem}.column_map.json",
        parent / "column_map.json",
    ]


def resolve_sidecar_map_path(history_csv: Path) -> Path | None:
    for path in sidecar_candidates(history_csv):
        if path.is_file():
            return path
    return None


def require_equipment_sidecar_maps(equipment: list[dict[str, Any]]) -> None:
    """Raise SidecarMapError listing every equipment history CSV missing a map."""
    missing: list[str] = []
    for eq in equipment:
        hist = Path(eq["history_path"])
        if resolve_sidecar_map_path(hist) is None:
            rel = f"{eq.get('equipment_id', hist.parent.name)}/{hist.name}"
            missing.append(
                f"{rel} (need one of: {hist.stem}.json | {hist.stem}.column_map.json | column_map.json)"
            )
    if missing:
        preview = "; ".join(missing[:12])
        more = f" … +{len(missing) - 12} more" if len(missing) > 12 else ""
        raise SidecarMapError(
            f"Package rejected: {len(missing)} equipment CSV(s) missing Haystack map JSON. "
            f"{preview}{more}"
        )


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SidecarMapError(f"{path}: invalid JSON ({exc})") from exc


def _points_from_payload(raw: Any, equipment_id: str) -> tuple[dict[str, str], str]:
    """Return (cookbook_role→csv_column, equipment_type) from flexible JSON shapes."""
    if not isinstance(raw, dict):
        raise SidecarMapError(f"map for {equipment_id} must be a JSON object")

    # Full package map
    if any(k in raw for k in ("equip", "equipment", "devices")):
        norm = normalize_column_map(raw)
        block = (norm.get("equipment") or {}).get(equipment_id) or {}
        if not block and len(norm.get("equipment") or {}) == 1:
            # Single-equip file keyed under another id — take the only block
            block = next(iter((norm.get("equipment") or {}).values()))
        roles = dict(block.get("column_roles") or {})
        etype = str(block.get("equipment_type") or "UNKNOWN")
        if not roles:
            raise SidecarMapError(
                f"{equipment_id}: package-style map has no points/column_roles for this equipment"
            )
        return roles, etype

    # Single equip Haystack / legacy block
    if any(k in raw for k in ("points", "column_roles", "roles", "equipType", "equipment_type")):
        points = raw.get("points") or raw.get("column_roles") or raw.get("roles") or {}
        if not isinstance(points, dict):
            raise SidecarMapError(f"{equipment_id}: points must be an object")
        roles = normalize_point_roles(points)
        etype = haystack_equip_type_to_cookbook(
            str(raw.get("equipType") or raw.get("equipment_type") or ""),
            equipment_id,
        )
        if not roles:
            raise SidecarMapError(f"{equipment_id}: sidecar map has empty points")
        return roles, etype

    # Flat points dict (haystack name or cookbook role → csv column)
    if raw and all(isinstance(v, str) for v in raw.values()):
        # Avoid treating metadata-only objects as points
        meta = {"version", "building_id", "building", "siteRef", "site_id", "notes", "generated_by"}
        if set(raw) <= meta:
            raise SidecarMapError(f"{equipment_id}: sidecar map has no point bindings")
        roles = normalize_point_roles({k: v for k, v in raw.items() if k not in meta})
        if not roles:
            raise SidecarMapError(f"{equipment_id}: sidecar map has no point bindings")
        return roles, haystack_equip_type_to_cookbook("", equipment_id)

    raise SidecarMapError(
        f"{equipment_id}: unrecognized map JSON shape "
        "(want points/column_roles, full column_map, or flat role→column object)"
    )


def load_equipment_sidecar_map(
    equipment_id: str,
    history_csv: Path,
    *,
    building_id: str = "",
    site_ref: str = "default_site",
) -> dict[str, Any]:
    """Load one equipment's sidecar into a normalized single-equip column_map."""
    path = resolve_sidecar_map_path(history_csv)
    if path is None:
        raise SidecarMapError(f"{equipment_id}: missing Haystack map next to {history_csv.name}")
    raw = _load_json(path)
    roles, etype = _points_from_payload(raw, equipment_id)
    data = empty_column_map(
        building_id=building_id or "UNNAMED_BUILDING",
        site_ref=site_ref,
        generated_by=f"sidecar:{path.name}",
    )
    data["equipment"][equipment_id] = {
        "equipment_type": etype,
        "device": equipment_id,
        "column_roles": roles,
    }
    return data


def merge_package_column_maps(
    building_root: Path,
    equipment: list[dict[str, Any]],
    *,
    building_id: str = "",
    site_ref: str = "default_site",
    root_column_map: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Require per-equip sidecars; merge them (+ optional root map as supplement)."""
    require_equipment_sidecar_maps(equipment)
    merged = empty_column_map(
        building_id=building_id or building_root.name,
        site_ref=site_ref,
        generated_by="package-sidecars",
    )
    # Root map first (supplement); per-equip sidecars win
    if root_column_map:
        merged = normalize_column_map(root_column_map)
        merged["building_id"] = building_id or merged.get("building_id") or building_root.name
    for eq in equipment:
        eq_id = str(eq["equipment_id"])
        piece = load_equipment_sidecar_map(
            eq_id,
            Path(eq["history_path"]),
            building_id=building_id or building_root.name,
            site_ref=site_ref,
        )
        block = piece["equipment"][eq_id]
        merged["equipment"][eq_id] = block
    return normalize_column_map(merged)


def sidecar_maps_to_role_map(
    column_map: dict[str, Any],
    existing: dict[str, dict[str, str]] | None = None,
) -> dict[str, dict[str, str]]:
    return merge_column_map_into_role_map(existing or {}, column_map, prefer_json=True)
