"""Lightweight multi-site / building / equipment model (no RDF)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

EQUIPMENT_TYPES = (
    "AHU",
    "VAV",
    "CHW_PLANT",
    "BOILER",
    "HP",
    "VRF",
    "WEATHER",
    "METER",
    "COOLING_TOWER",
    "UNKNOWN",
)


@dataclass
class Point:
    point_id: str
    point_name: str
    column_name: str
    role: str
    unit: str = ""
    kind: str = "sensor"
    tags: dict[str, str] = field(default_factory=dict)
    source_file: str = ""
    source_table: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "point_id": self.point_id,
            "point_name": self.point_name,
            "column_name": self.column_name,
            "role": self.role,
            "unit": self.unit,
            "kind": self.kind,
            "tags": dict(self.tags),
            "source_file": self.source_file,
            "source_table": self.source_table,
        }


@dataclass
class Equipment:
    equipment_id: str
    equipment_name: str
    equipment_type: str
    site_id: str
    building_id: str
    source_id: str = ""
    roles: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "equipment_id": self.equipment_id,
            "equipment_name": self.equipment_name,
            "equipment_type": self.equipment_type,
            "site_id": self.site_id,
            "building_id": self.building_id,
            "source_id": self.source_id,
            "roles": dict(self.roles),
        }


@dataclass
class Building:
    building_id: str
    building_name: str
    site_id: str
    timezone: str = "UTC"
    equipment: dict[str, Equipment] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "building_id": self.building_id,
            "building_name": self.building_name,
            "site_id": self.site_id,
            "timezone": self.timezone,
            "equipment": {k: v.to_dict() for k, v in self.equipment.items()},
        }


@dataclass
class Site:
    site_id: str
    site_name: str
    timezone: str = "UTC"
    buildings: dict[str, Building] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "site_id": self.site_id,
            "site_name": self.site_name,
            "timezone": self.timezone,
            "buildings": {k: v.to_dict() for k, v in self.buildings.items()},
        }

    def all_equipment(self) -> list[Equipment]:
        out: list[Equipment] = []
        for b in self.buildings.values():
            out.extend(b.equipment.values())
        return out


def sites_to_yaml_dict(sites: dict[str, Site]) -> dict[str, Any]:
    return {"sites": {sid: s.to_dict() for sid, s in sites.items()}}


# Alias → cookbook equipment_type. RTU is treated as AHU (+ DX roles when mapped).
_TYPE_ALIASES: dict[str, str] = {
    "AHU": "AHU",
    "AIRHANDLINGUNIT": "AHU",
    "AIR-HANDLING-UNIT": "AHU",
    "RTU": "AHU",
    "ROOFTOP": "AHU",
    "ROOFTOPUNIT": "AHU",
    "VAV": "VAV",
    "VAVBOX": "VAV",
    "TERMINAL": "VAV",
    "CHW_PLANT": "CHW_PLANT",
    "CHWPLANT": "CHW_PLANT",
    "CHILLER": "CHW_PLANT",
    "CHW": "CHW_PLANT",
    "BOILER": "BOILER",
    "BOILERPLANT": "BOILER",
    "COOLING_TOWER": "COOLING_TOWER",
    "COOLINGTOWER": "COOLING_TOWER",
    "TOWER": "COOLING_TOWER",
    "CT": "COOLING_TOWER",
    "HP": "HP",
    "HEATPUMP": "HP",
    "HEAT_PUMP": "HP",
    "HEAT-PUMP": "HP",
    "VRF": "VRF",
    "VRV": "VRF",
    "WEATHER": "WEATHER",
    "METEO": "WEATHER",
    "METER": "METER",
    "UNKNOWN": "UNKNOWN",
}


def normalize_equipment_type(raw: str | None) -> str:
    """Normalize aliases (heatPump, RTU, …) to cookbook types. Empty → \"\"."""
    if raw is None:
        return ""
    s = str(raw).strip()
    if not s:
        return ""
    key = "".join(ch for ch in s.upper() if ch.isalnum())
    if key in _TYPE_ALIASES:
        return _TYPE_ALIASES[key]
    compact = {"".join(ch for ch in a if ch.isalnum()): c for a, c in _TYPE_ALIASES.items()}
    if key in compact:
        return compact[key]
    return s.upper()


def equipment_type_from_id(equipment_id: str) -> str:
    u = equipment_id.upper().replace("\\", "/")
    if "WEATHER" in u:
        return "WEATHER"
    if "VAV" in u:
        return "VAV"
    if u.startswith("AHU") or "/AHU" in u or "RTU" in u:
        return "AHU"
    if "CHILLER" in u or u.startswith("CHW"):
        return "CHW_PLANT"
    if "TOWER" in u or "COOLING_TOWER" in u or "CT_" in u:
        return "COOLING_TOWER"
    if "BOILER" in u:
        return "BOILER"
    if ("HEAT" in u and "PUMP" in u) or u.startswith("HP") or "/HP" in u:
        return "HP"
    if "VRF" in u or "VRV" in u:
        return "VRF"
    if "METER" in u:
        return "METER"
    return "UNKNOWN"


def resolve_equipment_type(
    equipment_id: str,
    *,
    df: Any | None = None,
    role_map: dict[str, Any] | None = None,
    column_map: dict[str, Any] | None = None,
    sites: dict[str, Site] | None = None,
    explicit: str | None = None,
) -> str:
    """Canonical typed equipment resolver.

    Order: ``df.attrs['equipment_type']`` → ``explicit`` → role_map / site /
    column_map ``equipment_type`` / ``equipType`` → ``equipment_type_from_id`` only.
    """
    candidates: list[str] = []
    if df is not None:
        attrs = getattr(df, "attrs", None) or {}
        if isinstance(attrs, dict):
            for key in ("equipment_type", "equipType"):
                val = attrs.get(key)
                if val:
                    candidates.append(str(val))
    if explicit:
        candidates.append(str(explicit))
    eq_roles = (role_map or {}).get(equipment_id) if role_map else None
    if isinstance(eq_roles, dict):
        for key in ("equipment_type", "equipType"):
            val = eq_roles.get(key)
            if val:
                candidates.append(str(val))
    if column_map:
        equip_block = (column_map.get("equipment") or column_map.get("equip") or {}).get(
            equipment_id
        )
        if isinstance(equip_block, dict):
            for key in ("equipment_type", "equipType"):
                val = equip_block.get(key)
                if val:
                    candidates.append(str(val))
    if sites:
        for site in sites.values():
            for building in site.buildings.values():
                eq = building.equipment.get(equipment_id)
                if eq and eq.equipment_type:
                    candidates.append(str(eq.equipment_type))
    for raw in candidates:
        norm = normalize_equipment_type(raw)
        if norm and norm != "UNKNOWN":
            return norm
        if norm == "UNKNOWN":
            # keep looking for a stronger source; fall through
            continue
    # Last resort: id heuristic (or UNKNOWN from a candidate)
    for raw in candidates:
        norm = normalize_equipment_type(raw)
        if norm:
            return norm
    return equipment_type_from_id(equipment_id)


def stamp_equipment_type(
    df: Any,
    equipment_id: str,
    *,
    role_map: dict[str, Any] | None = None,
    column_map: dict[str, Any] | None = None,
    sites: dict[str, Site] | None = None,
    explicit: str | None = None,
) -> str:
    """Resolve type and write ``df.attrs['equipment_type']`` (overwrite)."""
    et = resolve_equipment_type(
        equipment_id,
        df=df,
        role_map=role_map,
        column_map=column_map,
        sites=sites,
        explicit=explicit,
    )
    if hasattr(df, "attrs") and isinstance(df.attrs, dict):
        df.attrs["equipment_type"] = et
    return et
