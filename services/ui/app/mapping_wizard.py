"""Site/building/equipment mapping wizard — nested YAML with flat backward compatibility."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from app.site_model import Building, Equipment, Site, equipment_type_from_id, sites_to_yaml_dict

DEFAULT_SITE_ID = "default_site"
DEFAULT_BUILDING_ID = "HVAC_BUILDING"


def is_nested_role_map(data: dict[str, Any]) -> bool:
    return isinstance(data.get("sites"), dict)


def wrap_flat_role_map(flat: dict[str, dict[str, str]], *, site_id: str = DEFAULT_SITE_ID, building_id: str = DEFAULT_BUILDING_ID) -> dict[str, Site]:
    building = Building(building_id=building_id, building_name=building_id, site_id=site_id)
    for eq_id, roles in flat.items():
        if not isinstance(roles, dict):
            continue
        building.equipment[eq_id] = Equipment(
            equipment_id=eq_id,
            equipment_name=eq_id,
            equipment_type=equipment_type_from_id(eq_id),
            site_id=site_id,
            building_id=building_id,
            roles={str(k): str(v) for k, v in roles.items()},
        )
    site = Site(site_id=site_id, site_name=site_id, buildings={building_id: building})
    return {site_id: site}


def sites_from_yaml(data: dict[str, Any]) -> dict[str, Site]:
    if not is_nested_role_map(data):
        flat = {k: v for k, v in data.items() if isinstance(v, dict)}
        return wrap_flat_role_map(flat)

    sites: dict[str, Site] = {}
    for sid, sraw in (data.get("sites") or {}).items():
        if not isinstance(sraw, dict):
            continue
        buildings: dict[str, Building] = {}
        for bid, braw in (sraw.get("buildings") or {}).items():
            if not isinstance(braw, dict):
                continue
            equipment: dict[str, Equipment] = {}
            for eid, eraw in (braw.get("equipment") or {}).items():
                if not isinstance(eraw, dict):
                    continue
                roles = eraw.get("roles") or {}
                equipment[eid] = Equipment(
                    equipment_id=eid,
                    equipment_name=str(eraw.get("name", eid)),
                    equipment_type=str(eraw.get("equipment_type", equipment_type_from_id(eid))),
                    site_id=str(sid),
                    building_id=str(bid),
                    source_id=str(eraw.get("source_id", "")),
                    roles={str(k): str(v) for k, v in roles.items()} if isinstance(roles, dict) else {},
                )
            buildings[bid] = Building(
                building_id=str(bid),
                building_name=str(braw.get("name", bid)),
                site_id=str(sid),
                timezone=str(braw.get("timezone", "UTC")),
                equipment=equipment,
            )
        sites[str(sid)] = Site(
            site_id=str(sid),
            site_name=str(sraw.get("name", sid)),
            timezone=str(sraw.get("timezone", "UTC")),
            buildings=buildings,
        )
    return sites


def flat_role_map_from_sites(sites: dict[str, Site]) -> dict[str, dict[str, str]]:
    """Legacy flat equipment_id → roles for runner compatibility."""
    out: dict[str, dict[str, str]] = {}
    for site in sites.values():
        for building in site.buildings.values():
            for eq in building.equipment.values():
                out[eq.equipment_id] = dict(eq.roles)
    return out


def equipment_context(sites: dict[str, Site], equipment_id: str) -> tuple[str, str, str]:
    for site in sites.values():
        for building in site.buildings.values():
            if equipment_id in building.equipment:
                eq = building.equipment[equipment_id]
                return site.site_id, building.building_id, eq.equipment_type
    return DEFAULT_SITE_ID, DEFAULT_BUILDING_ID, equipment_type_from_id(equipment_id)


def load_site_mapping(path: Path) -> dict[str, Site]:
    if not path.is_file():
        return wrap_flat_role_map({})
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return wrap_flat_role_map({})
    return sites_from_yaml(data)


def save_site_mapping(path: Path, sites: dict[str, Site]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(sites_to_yaml_dict(sites), sort_keys=False, default_flow_style=False), encoding="utf-8")


def migrate_flat_file(flat_path: Path, nested_path: Path, *, site_id: str = DEFAULT_SITE_ID, building_id: str = DEFAULT_BUILDING_ID) -> dict[str, Site]:
    data = yaml.safe_load(flat_path.read_text(encoding="utf-8")) or {}
    flat = {k: v for k, v in data.items() if isinstance(v, dict) and k != "sites"}
    sites = wrap_flat_role_map(flat, site_id=site_id, building_id=building_id)
    save_site_mapping(nested_path, sites)
    return sites


def upsert_equipment_roles(
    sites: dict[str, Site],
    *,
    site_id: str,
    building_id: str,
    equipment_id: str,
    equipment_type: str,
    roles: dict[str, str],
) -> None:
    site = sites.setdefault(site_id, Site(site_id=site_id, site_name=site_id))
    building = site.buildings.setdefault(building_id, Building(building_id=building_id, building_name=building_id, site_id=site_id))
    eq = building.equipment.get(equipment_id)
    if eq is None:
        eq = Equipment(
            equipment_id=equipment_id,
            equipment_name=equipment_id,
            equipment_type=equipment_type,
            site_id=site_id,
            building_id=building_id,
            roles=dict(roles),
        )
        building.equipment[equipment_id] = eq
    else:
        eq.roles.update(roles)
        eq.equipment_type = equipment_type
