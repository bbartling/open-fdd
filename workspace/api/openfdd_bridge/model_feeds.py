"""Ensure BRICK feeds relationships exist in model.json before TTL sync."""

from __future__ import annotations

from typing import Any


def _is_vav(eq: dict[str, Any]) -> bool:
    et = str(eq.get("equipment_type") or eq.get("brick_type") or "").upper()
    name = str(eq.get("name") or "").lower()
    return "VAV" in et or "vav" in name


def _is_ahu(eq: dict[str, Any]) -> bool:
    et = str(eq.get("equipment_type") or eq.get("brick_type") or "").upper()
    name = str(eq.get("name") or "").lower()
    if "AHU" in et or "AIR_HANDLER" in et:
        return True
    if "rtu" in name:
        return True
    return "ahu" in name


def _is_hot_water_plant(eq: dict[str, Any]) -> bool:
    et = str(eq.get("equipment_type") or eq.get("brick_type") or "").upper()
    name = str(eq.get("name") or "").lower()
    return "HOT_WATER" in et or "hw-plant" in name or "hw plant" in name


def _append_feeds(parent: dict[str, Any], child_ids: list[str]) -> int:
    feeds = parent.get("feeds")
    if not isinstance(feeds, list):
        feeds = []
    existing = {str(x) for x in feeds if str(x).strip()}
    added = 0
    for cid in child_ids:
        if cid and cid not in existing:
            feeds.append(cid)
            existing.add(cid)
            added += 1
    if feeds:
        parent["feeds"] = sorted(existing | {str(x) for x in feeds if str(x).strip()})
    return added


def ensure_site_feeds(model: dict[str, Any], site_id: str) -> int:
    """Add feeds edges: roof AHU/RTU → VAV terminals on same site. Returns edges added."""
    equipment = [e for e in model.get("equipment") or [] if isinstance(e, dict)]
    site_eq = [e for e in equipment if str(e.get("site_id") or "") == site_id]
    vavs = [e for e in site_eq if _is_vav(e)]
    ahus = [e for e in site_eq if _is_ahu(e)]
    if not ahus or not vavs:
        return 0

    added = 0
    vav_ids = [str(v.get("id") or "") for v in vavs if str(v.get("id") or "").strip()]
    for ahu in ahus:
        added += _append_feeds(ahu, vav_ids)

    plants = [e for e in site_eq if _is_hot_water_plant(e)]
    for plant in plants:
        added += _append_feeds(plant, vav_ids)

    return added


def ensure_model_feeds(model: dict[str, Any]) -> int:
    total = 0
    for site in model.get("sites") or []:
        if isinstance(site, dict) and site.get("id"):
            total += ensure_site_feeds(model, str(site["id"]))
    return total
