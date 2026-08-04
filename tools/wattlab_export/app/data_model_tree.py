"""Building data-model tree: equipment → points (Haystack tags → CSV columns).

AHU↔VAV topology (VAV fedBy AHU / AHU feeds VAVs) lives on the tree object
and is rendered as its own UI section — not mixed into point binding tables.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from app.column_map_json import COOKBOOK_TO_HAYSTACK_POINT
from app.role_map import apply_role_map
from app.rules import RULES
from app.site_model import resolve_equipment_type


@dataclass
class RoleBinding:
    cookbook_role: str
    haystack_tag: str
    csv_column: str | None
    present_in_history: bool
    required_by_rules: list[str] = field(default_factory=list)


@dataclass
class EquipmentModelNode:
    equipment_id: str
    equipment_type: str
    bindings: list[RoleBinding] = field(default_factory=list)
    applicable_rule_ids: list[str] = field(default_factory=list)
    fed_by: str | None = None  # parent AHU (VAV → AHU)
    feeds: list[str] = field(default_factory=list)  # child VAV ids (AHU → VAVs)


@dataclass
class BuildingDataModelTree:
    building_id: str
    equipment: list[EquipmentModelNode] = field(default_factory=list)
    vav_to_ahu: dict[str, str] = field(default_factory=dict)

    def to_rows(self) -> list[dict[str, Any]]:
        """Flat point bindings only (no topology columns)."""
        rows: list[dict[str, Any]] = []
        for eq in self.equipment:
            for b in eq.bindings:
                rows.append(
                    {
                        "equipment_id": eq.equipment_id,
                        "equipment_type": eq.equipment_type,
                        "haystack_point": b.haystack_tag,
                        "csv_column": b.csv_column or "",
                        "present_in_history": b.present_in_history,
                        "required_by_rules": ", ".join(b.required_by_rules),
                    }
                )
        return rows

    def topology_rows(self) -> list[dict[str, Any]]:
        """VAV fedBy AHU and AHU feeds VAVs — one row per directed link."""
        from app.topology_enrich import invert_vav_to_ahu

        rows: list[dict[str, Any]] = []
        feeds = invert_vav_to_ahu(self.vav_to_ahu)
        for ahu_id in sorted(feeds):
            children = feeds[ahu_id]
            rows.append(
                {
                    "equipment_id": ahu_id,
                    "relation": "feeds",
                    "related_ids": ", ".join(children),
                    "related_count": len(children),
                }
            )
        for vav_id, ahu_id in sorted(self.vav_to_ahu.items()):
            rows.append(
                {
                    "equipment_id": vav_id,
                    "relation": "fedBy",
                    "related_ids": ahu_id,
                    "related_count": 1,
                }
            )
        return rows


def _role_map_column(role_map: dict, equipment_id: str, role: str) -> str | None:
    block = role_map.get(equipment_id) or {}
    if not isinstance(block, dict):
        return None
    val = block.get(role)
    if isinstance(val, str) and val.strip():
        return val.strip()
    for col, mapped_role in block.items():
        if str(mapped_role).strip() == role and col not in {
            "equipment_type",
            "equipType",
            "plant_group",
            "chw_pump_equipment",
        }:
            return str(col)
    return None


def _roles_for_equipment_kind(kind: str) -> dict[str, list[str]]:
    """role → list of rule ids that require it for this equipment kind."""
    out: dict[str, list[str]] = {}
    for rule in RULES:
        if kind not in rule.equipment_kinds and kind != "unknown":
            if "unknown" not in rule.equipment_kinds and kind not in {
                "ahu",
                "vav",
                "chiller",
                "boiler",
                "heatpump",
                "weather",
                "zone",
            }:
                continue
        kinds = {k.lower() for k in rule.equipment_kinds}
        kind_l = kind.lower()
        if kind_l not in kinds and "unknown" not in kinds:
            aliases = {
                "ahu": {"ahu"},
                "vav": {"vav", "zone"},
                "chw_plant": {"chiller"},
                "chiller": {"chiller"},
                "boiler": {"boiler"},
                "hp": {"heatpump", "ahu"},
                "weather": {"weather"},
            }
            if not (kinds & aliases.get(kind_l, {kind_l})):
                continue
        for role in list(rule.required_roles) + list(rule.optional_roles or []):
            out.setdefault(role, []).append(rule.id)
    return out


def _infer_kind_key(equipment_type: str) -> str:
    et = (equipment_type or "UNKNOWN").upper()
    if et in {"AHU", "RTU"}:
        return "ahu"
    if et == "VAV":
        return "vav"
    if et in {"CHW_PLANT", "CHILLER"}:
        return "chiller"
    if et == "BOILER":
        return "boiler"
    if et in {"HP", "HEATPUMP"}:
        return "heatpump"
    if et == "WEATHER":
        return "weather"
    return "unknown"


def build_data_model_tree(
    frames: dict[str, pd.DataFrame],
    role_map: dict,
    *,
    building_id: str = "",
    vav_to_ahu: dict[str, str] | None = None,
) -> BuildingDataModelTree:
    """Assemble professional data-model inventory for UI + DOCX."""
    from app.topology_enrich import invert_vav_to_ahu

    topo = dict(vav_to_ahu or {})
    feeds_map = invert_vav_to_ahu(topo)
    tree = BuildingDataModelTree(building_id=building_id or "", vav_to_ahu=topo)
    for eq_id, raw in sorted(frames.items()):
        et = resolve_equipment_type(eq_id, df=raw, role_map=role_map)
        kind = _infer_kind_key(et)
        role_rules = _roles_for_equipment_kind(kind)
        mapped = apply_role_map(raw, eq_id, role_map)
        roles = set(role_rules)
        eq_block = role_map.get(eq_id) or {}
        if isinstance(eq_block, dict):
            for k, v in eq_block.items():
                if k in {"equipment_type", "equipType", "plant_group", "chw_pump_equipment"}:
                    continue
                if isinstance(v, str) and v.strip():
                    if k in COOKBOOK_TO_HAYSTACK_POINT or k in role_rules:
                        roles.add(k)
                    else:
                        roles.add(str(v).strip())
        for col in mapped.columns:
            if col in COOKBOOK_TO_HAYSTACK_POINT or col in role_rules:
                roles.add(col)

        applicable = [
            r.id
            for r in RULES
            if kind in {k.lower() for k in r.equipment_kinds}
            or "unknown" in {k.lower() for k in r.equipment_kinds}
        ]
        bindings: list[RoleBinding] = []
        for role in sorted(roles):
            hay = COOKBOOK_TO_HAYSTACK_POINT.get(role, role.replace("_", "-"))
            csv_col = _role_map_column(role_map, eq_id, role)
            present = role in mapped.columns and mapped[role].notna().any()
            if csv_col is None and present:
                csv_col = role if role in raw.columns else None
                if csv_col is None:
                    for c, rr in (eq_block.items() if isinstance(eq_block, dict) else []):
                        if str(rr).strip() == role:
                            csv_col = str(c)
                            break
            bindings.append(
                RoleBinding(
                    cookbook_role=role,
                    haystack_tag=hay,
                    csv_column=csv_col,
                    present_in_history=bool(present),
                    required_by_rules=sorted(set(role_rules.get(role, []))),
                )
            )
        fed_by = topo.get(eq_id) or (str(raw.attrs.get("fed_by") or "") or None)
        feeds = list(feeds_map.get(eq_id) or raw.attrs.get("feeds") or [])
        tree.equipment.append(
            EquipmentModelNode(
                equipment_id=eq_id,
                equipment_type=et,
                bindings=bindings,
                applicable_rule_ids=applicable,
                fed_by=fed_by if fed_by else None,
                feeds=feeds,
            )
        )
    return tree
