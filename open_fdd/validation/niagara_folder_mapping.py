"""Niagara station folder → building boundary helpers (issue #315)."""

from __future__ import annotations

from typing import Any


def ord_segments(ord_path: str) -> list[str]:
    text = str(ord_path or "").strip()
    if not text:
        return []
    if text.startswith("slot:"):
        text = text[5:]
    return [p for p in text.split("/") if p]


def infer_building_folders(
    nodes: list[dict[str, Any]],
    *,
    min_children: int = 1,
) -> list[dict[str, Any]]:
    """Group browse tree nodes that look like building folders under Drivers."""
    by_parent: dict[str, list[dict[str, Any]]] = {}
    for node in nodes:
        if not isinstance(node, dict):
            continue
        parent = str(node.get("parent_ord") or node.get("parent") or "")
        by_parent.setdefault(parent, []).append(node)

    buildings: list[dict[str, Any]] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        ord_path = str(node.get("ord") or node.get("path") or "")
        kids = by_parent.get(ord_path, [])
        if len(kids) < min_children:
            continue
        point_like = sum(1 for k in kids if str(k.get("type") or "").lower() in ("point", "controlpoint"))
        buildings.append(
            {
                "folder_ord": ord_path,
                "name": node.get("name") or ord_segments(ord_path)[-1] or ord_path,
                "child_count": len(kids),
                "estimated_points": point_like,
                "segments": ord_segments(ord_path),
            }
        )
    return sorted(buildings, key=lambda b: b["folder_ord"])


def preview_import_stats(
    points: list[dict[str, Any]],
    *,
    root_ord: str,
) -> dict[str, Any]:
    """Dry-run summary for points discovered under a Niagara folder root."""
    root = str(root_ord or "").rstrip("/")
    seen_ords: set[str] = set()
    duplicate_ords: list[str] = []
    skipped: list[dict[str, str]] = []
    equipment_ids: set[str] = set()

    for pt in points:
        if not isinstance(pt, dict):
            skipped.append({"reason": "invalid_record"})
            continue
        ord_path = str(pt.get("point_ord") or pt.get("ord") or "")
        if root and not ord_path.startswith(root):
            skipped.append({"ord": ord_path, "reason": "outside_root"})
            continue
        if ord_path in seen_ords:
            duplicate_ords.append(ord_path)
            continue
        seen_ords.add(ord_path)
        eq = str(pt.get("equipment_id") or pt.get("device_name") or "")
        if eq:
            equipment_ids.add(eq)

    return {
        "root_ord": root,
        "point_count": len(seen_ords),
        "equipment_count": len(equipment_ids),
        "duplicate_ord_count": len(duplicate_ords),
        "duplicate_ords_sample": duplicate_ords[:10],
        "skipped_count": len(skipped),
        "skipped_sample": skipped[:10],
    }


def map_folder_to_site(
    folder_ord: str,
    *,
    station_id: str,
    site_id: str | None = None,
) -> dict[str, str]:
    """Map a Niagara folder ORD to Open-FDD site/building context."""
    segments = ord_segments(folder_ord)
    building = segments[-1] if segments else station_id
    return {
        "station_id": station_id,
        "site_id": site_id or station_id,
        "building_id": building,
        "folder_ord": folder_ord,
        "label": building.replace("_", " ").replace("-", " "),
    }
