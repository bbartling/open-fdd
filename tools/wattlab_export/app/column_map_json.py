"""Haystack-like point → CSV column map (rules read the same point names).

Authors (humans / LLMs) use Project Haystack–style names: ``siteRef``, ``equip``,
``device``, ``equipType``, ``points`` with tags like ``discharge-air-temp``.
Runtime role_map / DataFrames use those same names — no intermediate vocabulary.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pandas as pd

from app.role_map import enrich_role_map_from_equipment, roles_from_columns_csv, suggest_roles
from app.site_model import equipment_type_from_id
from app.units import DEFAULT_ROLE_UNITS

SCHEMA_VERSION = 1
DEFAULT_BUILDING_ID = ""  # filled from the loaded folder name at runtime
DEFAULT_SITE_REF = "default_site"

# Mechanical families used for UI grouping (cookbook `family` field).
FAMILY_ORDER: list[str] = [
    "sensor",
    "control",
    "ahu",
    "vav",
    "plant",
    "heatpump",
    "weather",
    "trim",
    "schedule",
    "custom",
    "other",
]
FAMILY_LABELS: dict[str, str] = {
    "sensor": "1 · Sensor validation",
    "control": "2 · Control loops",
    "ahu": "3 · AHU / air handling",
    "vav": "4 · VAV / terminal",
    "plant": "5 · Central plant",
    "heatpump": "6 · Heat pump",
    "weather": "7 · Weather / OAT",
    "trim": "8 · Trim & respond",
    "schedule": "9 · Schedule / runtime",
    "other": "10 · Other",
}

# Preferred display / inventory name for each logical point (identity for most).
# Kept as a dict so Data Model / plots can still resolve a label.
POINT_DISPLAY: dict[str, str] = {
    "discharge-air-temp": "discharge-air-temp",
    "discharge-air-temp-sp": "discharge-air-temp-sp",
    "mixed-air-temp": "mixed-air-temp",
    "return-air-temp": "return-air-temp",
    "outside-air-temp": "outside-air-temp",
    "outside-air-humidity": "outside-air-humidity",
    "outside-air-damper": "outside-air-damper",
    "cooling-valve": "cooling-valve",
    "heating-valve": "heating-valve",
    "fan-cmd": "fan-cmd",
    "return-fan-cmd": "return-fan-cmd",
    "fan-status": "fan-status",
    "duct-static-pressure": "duct-static-pressure",
    "duct-static-pressure-sp": "duct-static-pressure-sp",
    "zone-air-temp": "zone-air-temp",
    "zone-airflow": "zone-airflow",
    "min-flow-sp": "min-flow-sp",
    "damper": "damper",
    "reheat-valve": "reheat-valve",
    "vav-discharge-air-temp": "vav-discharge-air-temp",
    "vav-inlet-air-temp": "vav-inlet-air-temp",
    "ahu-discharge-air-temp": "ahu-discharge-air-temp",
    "chilled-water-supply-temp": "chilled-water-supply-temp",
    "chilled-water-return-temp": "chilled-water-return-temp",
    "hot-water-supply-temp": "hot-water-supply-temp",
    "hot-water-return-temp": "hot-water-return-temp",
    "occupied": "occupied",
    "chw-diff-pressure": "chw-diff-pressure",
    "chw-diff-pressure-sp": "chw-diff-pressure-sp",
    "chw-flow": "chw-flow",
    "chw-pump-cmd": "chw-pump-cmd",
    "chw-pump-status": "chw-pump-status",
    "cw-pump-cmd": "cw-pump-cmd",
    "tower-fan-cmd": "tower-fan-cmd",
    "cw-fan-cmd": "cw-fan-cmd",
    "chw-reset-request-sum": "chw-reset-request-sum",
    "chilled-water-supply-temp-sp": "chilled-water-supply-temp-sp",
    "cooling-coil-entering-temp": "cooling-coil-entering-temp",
    "cooling-coil-leaving-temp": "cooling-coil-leaving-temp",
    "condenser-water-supply-temp": "condenser-water-supply-temp",
    "condenser-water-return-temp": "condenser-water-return-temp",
    "heating-coil-entering-temp": "heating-coil-entering-temp",
    "heating-coil-leaving-temp": "heating-coil-leaving-temp",
    "hw-reset-request-sum": "hw-reset-request-sum",
    "loop-enabled": "loop-enabled",
    "preheat-leaving-temp": "preheat-leaving-temp",
    "vav-pressure-request-sum": "vav-pressure-request-sum",
    "vav-total-airflow": "vav-total-airflow",
    "web-outside-air-temp": "web-outside-air-temp",
    "web-outside-air-humidity": "web-outside-air-humidity",
    "web-outside-air-dewpoint": "web-outside-air-dewpoint",
    "web-outside-air-wetbulb": "web-outside-air-wetbulb",
    "elec-power": "elec-power",
    "building-power": "building-power",
    "meter-power": "meter-power",
    "chiller-power": "chiller-power",
    "gas-flow": "gas-flow",
    "gas-rate": "gas-rate",
    "nat-gas-flow": "nat-gas-flow",
    "gas-therm-rate": "gas-therm-rate",
    "pump-cmd": "pump-cmd",
    "hw-pump-cmd": "hw-pump-cmd",
    "control-output-pct": "control-output-pct",
    "chiller-status": "chiller-status",
    "chiller-amps": "chiller-amps",
    "pump-status": "pump-status",
    "hw-pump-status": "hw-pump-status",
    "compressor-status": "compressor-status",
    "compressor-cmd": "compressor-cmd",
    "compressor-stage-1": "compressor-stage-1",
    "compressor-stage-2": "compressor-stage-2",
    "compressor-power": "compressor-power",
    "compressor-current": "compressor-current",
    "heat-pump-cooling-status": "heat-pump-cooling-status",
    "unit-cooling-status": "unit-cooling-status",
    "vrf-outdoor-compressor-status": "vrf-outdoor-compressor-status",
    "equipment-enable": "equipment-enable",
    "fan-speed-feedback": "fan-speed-feedback",
    "fan-current": "fan-current",
    "fan-power": "fan-power",
    "airflow-proof": "airflow-proof",
    "dx-stage": "dx-stage",
    "dx-cool-cmd": "dx-cool-cmd",
    "cool-stage": "cool-stage",
    "dx-cooling": "dx-cooling",
    "pump-speed-feedback": "pump-speed-feedback",
    "pump-current": "pump-current",
    "water-flow": "water-flow",
    "bas-outside-air-temp": "bas-outside-air-temp",
}

# Alternate authoring tags → canonical point name.
POINT_ALIASES: dict[str, str] = {
    "discharge-air-temperature": "discharge-air-temp",
    "dischargeAirTemp": "discharge-air-temp",
    "da-temp": "discharge-air-temp",
    "discharge-air-sp": "discharge-air-temp-sp",
    "sat-sp": "discharge-air-temp-sp",
    "mixedAirTemp": "mixed-air-temp",
    "returnAirTemp": "return-air-temp",
    "outdoor-air-temp": "outside-air-temp",
    "outsideAirTemp": "outside-air-temp",
    "oa-temp": "outside-air-temp",
    "oa-damper": "outside-air-damper",
    "cool-valve": "cooling-valve",
    "clg-valve": "cooling-valve",
    "heat-valve": "heating-valve",
    "htg-valve": "heating-valve",
    "supply-fan-cmd": "fan-cmd",
    "supply-fan-status": "fan-status",
    "duct-static": "duct-static-pressure",
    "duct-static-sp": "duct-static-pressure-sp",
    "zone-temp": "zone-air-temp",
    "space-air-temp": "zone-air-temp",
    "space-temp": "zone-air-temp",
    "zoneAirTemp": "zone-air-temp",
    "zone-flow": "zone-airflow",
    "discharge-air-flow": "zone-airflow",
    "airflow": "zone-airflow",
    "zone-damper": "damper",
    "vav-damper": "damper",
    "vav-discharge-temp": "vav-discharge-air-temp",
    "vav-inlet-temp": "vav-inlet-air-temp",
    "chw-supply-temp": "chilled-water-supply-temp",
    "chw-return-temp": "chilled-water-return-temp",
    "cw-supply-temp": "condenser-water-supply-temp",
    "cw-return-temp": "condenser-water-return-temp",
    "tower-leaving-temp": "condenser-water-supply-temp",
    "tower-entering-temp": "condenser-water-return-temp",
    "hw-supply-temp": "hot-water-supply-temp",
    "hw-return-temp": "hot-water-return-temp",
    "occ-mode": "occupied",
    "wx_oa_t": "web-outside-air-temp",
}

HAYSTACK_EQUIP_TYPE_TO_COOKBOOK: dict[str, str] = {
    "ahu": "AHU",
    "airHandlingUnit": "AHU",
    "air-handling-unit": "AHU",
    "vav": "VAV",
    "vav-box": "VAV",
    "terminal": "VAV",
    "chw": "CHW_PLANT",
    "chiller": "CHW_PLANT",
    "chwPlant": "CHW_PLANT",
    "chw-plant": "CHW_PLANT",
    "boiler": "BOILER",
    "boilerPlant": "BOILER",
    "hp": "HP",
    "heatPump": "HP",
    "heat-pump": "HP",
    "vrf": "VRF",
    "vrv": "VRF",
    "rtu": "AHU",
    "rooftop": "AHU",
    "weather": "WEATHER",
    "meteo": "WEATHER",
    "meter": "METER",
    "coolingTower": "COOLING_TOWER",
    "cooling-tower": "COOLING_TOWER",
    "cooling_tower": "COOLING_TOWER",
    "tower": "COOLING_TOWER",
    "unknown": "UNKNOWN",
}

COOKBOOK_EQUIP_TO_HAYSTACK: dict[str, str] = {
    "AHU": "ahu",
    "VAV": "vav",
    "CHW_PLANT": "chwPlant",
    "BOILER": "boiler",
    "HP": "heatPump",
    "VRF": "vrf",
    "WEATHER": "weather",
    "METER": "meter",
    "COOLING_TOWER": "coolingTower",
    "UNKNOWN": "unknown",
}

# Back-compat aliases used by Data Model / plot meta (display = point name).
COOKBOOK_TO_HAYSTACK_POINT = POINT_DISPLAY

_META_KEYS = {
    "version",
    "building_id",
    "building",
    "site",
    "siteRef",
    "site_id",
    "generated_by",
    "notes",
    "units",
    "equipment",
    "equip",
    "devices",
    "role_map",
}


def natural_key(text: str) -> list:
    """Sort FC2 before FC10, ECON-1 before ECON-10, etc."""
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", text)]


def family_label(family: str) -> str:
    return FAMILY_LABELS.get(family, FAMILY_LABELS["other"])


def _slug_point_key(name: str) -> str:
    s = str(name).strip()
    if s in POINT_DISPLAY or s in POINT_ALIASES:
        return s
    s2 = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", s)
    s2 = s2.replace("_", "-").replace(" ", "-").lower()
    s2 = re.sub(r"-+", "-", s2)
    return s2


def canonicalize_point(point_name: str) -> str:
    """Normalize an authoring point name to the canonical Haystack slug."""
    raw = str(point_name).strip()
    if raw in POINT_DISPLAY:
        return raw
    if raw in POINT_ALIASES:
        return POINT_ALIASES[raw]
    slug = _slug_point_key(raw)
    if slug in POINT_DISPLAY:
        return slug
    if slug in POINT_ALIASES:
        return POINT_ALIASES[slug]
    return slug


def haystack_point_to_cookbook(point_name: str) -> str | None:
    """Return canonical point name (kept name for call-sites during migration)."""
    raw = str(point_name).strip()
    if not raw:
        return None
    return canonicalize_point(raw)


def haystack_equip_type_to_cookbook(equip_type: str, equip_id: str = "") -> str:
    raw = str(equip_type or "").strip()
    if not raw:
        return equipment_type_from_id(equip_id) if equip_id else "UNKNOWN"
    if raw.upper() in COOKBOOK_EQUIP_TO_HAYSTACK:
        return raw.upper()
    for candidate in (raw, raw.lower(), _slug_point_key(raw)):
        if candidate in HAYSTACK_EQUIP_TYPE_TO_COOKBOOK:
            return HAYSTACK_EQUIP_TYPE_TO_COOKBOOK[candidate]
    return equipment_type_from_id(equip_id) if equip_id else "UNKNOWN"


def normalize_point_roles(points: dict[str, Any]) -> dict[str, str]:
    """Accept Haystack point names → canonical point → column."""
    out: dict[str, str] = {}
    for name, col in points.items():
        if not name or not col:
            continue
        out[canonicalize_point(str(name))] = str(col)
    return out


def empty_column_map(
    *,
    building_id: str = DEFAULT_BUILDING_ID,
    site_ref: str = DEFAULT_SITE_REF,
    generated_by: str = "manual",
) -> dict[str, Any]:
    return {
        "version": SCHEMA_VERSION,
        "siteRef": site_ref or DEFAULT_SITE_REF,
        "building": building_id or "UNNAMED_BUILDING",
        "building_id": building_id or "UNNAMED_BUILDING",
        "generated_by": generated_by,
        "notes": (
            "Haystack-like map: siteRef / equip / device / points → CSV columns. "
            "units keep plots from mixing °F with % / cfm. CSVs are not rewritten."
        ),
        "units": dict(DEFAULT_ROLE_UNITS),
        "equipment": {},
    }


def to_haystack_document(data: dict[str, Any]) -> dict[str, Any]:
    """Export map using Haystack-style keys (equip / points / equipType)."""
    norm = normalize_column_map(data)
    equip_out: dict[str, Any] = {}
    for eq_id, block in (norm.get("equipment") or {}).items():
        etype = str(block.get("equipment_type") or equipment_type_from_id(eq_id))
        roles = block.get("column_roles") or {}
        points = {POINT_DISPLAY.get(role, role): col for role, col in sorted(roles.items())}
        equip_out[eq_id] = {
            "equipType": COOKBOOK_EQUIP_TO_HAYSTACK.get(etype, etype.lower()),
            "device": str(block.get("device") or eq_id),
            "points": points,
        }
    return {
        "version": int(norm.get("version", SCHEMA_VERSION)),
        "siteRef": str(norm.get("siteRef") or DEFAULT_SITE_REF),
        "building": str(norm.get("building") or norm.get("building_id") or "UNNAMED_BUILDING"),
        "generated_by": str(norm.get("generated_by", "manual")),
        "notes": str(norm.get("notes", "")),
        "units": {
            POINT_DISPLAY.get(role, role): unit
            for role, unit in sorted((norm.get("units") or DEFAULT_ROLE_UNITS).items())
        },
        "equip": equip_out,
    }


def load_column_map_json(path: Path | str | None) -> dict[str, Any]:
    if path is None:
        return empty_column_map()
    p = Path(path)
    if not p.is_file():
        return empty_column_map()
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("column map JSON must be an object")
    return normalize_column_map(data)


def _extract_equip_blocks(data: dict[str, Any]) -> dict[str, Any]:
    """Pull equip/device/equipment dict from document shapes."""
    for key in ("equip", "equipment", "devices"):
        block = data.get(key)
        if isinstance(block, dict):
            return block
    if isinstance(data.get("role_map"), dict):
        return data["role_map"]
    flat: dict[str, Any] = {}
    for eq_id, roles in data.items():
        if eq_id in _META_KEYS:
            continue
        if isinstance(roles, dict) and roles and all(isinstance(v, str) for v in roles.values()):
            flat[str(eq_id)] = roles
    return flat


def normalize_column_map(data: dict[str, Any]) -> dict[str, Any]:
    """Accept Haystack (siteRef/equip/points) documents."""
    building = str(
        data.get("building")
        or data.get("building_id")
        or DEFAULT_BUILDING_ID
        or "UNNAMED_BUILDING"
    )
    site_ref = str(
        data.get("siteRef") or data.get("site_id") or data.get("site") or DEFAULT_SITE_REF
    )
    out = empty_column_map(
        building_id=building,
        site_ref=site_ref,
        generated_by=str(data.get("generated_by", "manual")),
    )
    out["notes"] = str(data.get("notes", out["notes"]))
    out["version"] = int(data.get("version", SCHEMA_VERSION))
    units = dict(DEFAULT_ROLE_UNITS)
    raw_units = data.get("units") if isinstance(data.get("units"), dict) else {}
    for k, v in raw_units.items():
        role = canonicalize_point(str(k))
        if v:
            units[role] = str(v)
    out["units"] = units

    equipment: dict[str, Any] = {}
    raw_equip = _extract_equip_blocks(data)
    for eq_id, block in raw_equip.items():
        if not isinstance(block, dict):
            continue
        if any(
            k in block
            for k in ("points", "column_roles", "roles", "equipType", "equipment_type", "device")
        ):
            points = block.get("points") or block.get("column_roles") or block.get("roles") or {}
            if not isinstance(points, dict):
                continue
            etype = haystack_equip_type_to_cookbook(
                str(block.get("equipType") or block.get("equipment_type") or ""),
                str(eq_id),
            )
            device = str(block.get("device") or eq_id)
            equipment[str(eq_id)] = {
                "equipment_type": etype,
                "device": device,
                "column_roles": normalize_point_roles(points),
            }
        elif block and all(isinstance(v, str) for v in block.values()):
            equipment[str(eq_id)] = {
                "equipment_type": equipment_type_from_id(str(eq_id)),
                "device": str(eq_id),
                "column_roles": normalize_point_roles(block),
            }

    out["equipment"] = equipment
    return out


def save_column_map_json(path: Path, data: dict[str, Any], *, haystack: bool = True) -> None:
    """Save map. Default export is Haystack-style (equip/points)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = to_haystack_document(data) if haystack else normalize_column_map(data)
    path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def column_map_to_role_map(data: dict[str, Any]) -> dict[str, dict[str, str]]:
    data = normalize_column_map(data)
    return {
        eq_id: dict(block.get("column_roles") or {})
        for eq_id, block in data.get("equipment", {}).items()
        if isinstance(block, dict)
    }


def merge_column_map_into_role_map(
    role_map: dict[str, dict[str, str]],
    column_map: dict[str, Any],
    *,
    prefer_json: bool = True,
) -> dict[str, dict[str, str]]:
    """Merge JSON map into runtime role_map. JSON wins when prefer_json=True."""
    out = {k: dict(v) for k, v in role_map.items()}
    for eq_id, roles in column_map_to_role_map(column_map).items():
        if prefer_json:
            merged = dict(out.get(eq_id, {}))
            merged.update(roles)
            out[eq_id] = merged
        else:
            merged = dict(roles)
            merged.update(out.get(eq_id, {}))
            out[eq_id] = merged
    return out


def build_column_map_from_equipment_frames(
    frames: dict[str, Any],
    *,
    building_id: str = DEFAULT_BUILDING_ID,
    site_ref: str = DEFAULT_SITE_REF,
    generated_by: str = "heuristic",
) -> dict[str, Any]:
    """Auto-build JSON map from loaded frames (columns.csv + header heuristics)."""
    resolved_id = (building_id or "").strip() or _infer_building_id(frames)
    data = empty_column_map(building_id=resolved_id, site_ref=site_ref, generated_by=generated_by)
    data["notes"] = (
        "Auto-generated Haystack-like points from columns.csv + header heuristics. "
        "Refine with the LLM prompt (discharge-air-temp, zone-air-temp, …)."
    )
    for eq_id, df in frames.items():
        cols_path = df.attrs.get("columns_path")
        rm: dict[str, dict[str, str]] = {}
        enrich_role_map_from_equipment(
            rm,
            eq_id,
            Path(cols_path) if cols_path else None,
            list(df.columns),
        )
        roles = rm.get(eq_id, {})
        if not roles:
            roles = suggest_roles(df)
        if cols_path:
            roles = {**roles_from_columns_csv(Path(cols_path)), **roles}
        present = set(df.columns)
        roles = {r: c for r, c in roles.items() if c in present}
        etype = str(df.attrs.get("equipment_type") or equipment_type_from_id(eq_id))
        data["equipment"][eq_id] = {
            "equipment_type": etype,
            "device": eq_id,
            "column_roles": dict(sorted(roles.items())),
        }
    return data


def validate_column_map_against_frames(
    column_map: dict[str, Any],
    frames: dict[str, Any],
) -> list[str]:
    """Return human-readable issues (missing equipment / missing columns)."""
    issues: list[str] = []
    data = normalize_column_map(column_map)
    for eq_id, block in data.get("equipment", {}).items():
        if eq_id not in frames:
            issues.append(f"{eq_id}: not in loaded equipment frames")
            continue
        cols = set(frames[eq_id].columns)
        for role, col in (block.get("column_roles") or {}).items():
            if col not in cols:
                hs = POINT_DISPLAY.get(role, role)
                issues.append(f"{eq_id}.{hs} → column '{col}' not in history CSV")
    return issues


LLM_COLUMN_MAP_PROMPT = """You are mapping HVAC historian CSV columns using Project Haystack–style names.

Rules later consume these exact point names. Return ONLY valid JSON matching this schema (no markdown fences):

{
  "version": 1,
  "siteRef": "<site slug>",
  "building": "<building folder name from Input>",
  "generated_by": "llm",
  "notes": "<short note>",
  "equip": {
    "<equip id>": {
      "equipType": "ahu|vav|chwPlant|boiler|heatPump|weather|meter|unknown",
      "device": "<same as equip id unless a clearer device name exists>",
      "points": {
        "<haystack-point-name>": "<exact_csv_column_name>"
      }
    }
  }
}

Preferred Haystack-like point names (use only when a real column exists):
discharge-air-temp, discharge-air-temp-sp, mixed-air-temp, return-air-temp,
outside-air-temp, outside-air-damper, cooling-valve, heating-valve,
fan-cmd, fan-status, duct-static-pressure, duct-static-pressure-sp,
zone-air-temp, zone-airflow, min-flow-sp, damper, reheat-valve,
vav-discharge-air-temp, vav-inlet-air-temp, vav-total-airflow,
chilled-water-supply-temp, chilled-water-return-temp, chilled-water-supply-temp-sp,
hot-water-supply-temp, hot-water-return-temp, condenser-water-supply-temp,
chw-diff-pressure, chw-flow, chw-pump-cmd, occupied, web-outside-air-temp

Also include a top-level "units" object (Haystack point name → unit string) so plots
never mix °F with % / cfm / in. w.c. Example: {"discharge-air-temp": "°F", "damper": "%"}.

Rules:
1. points values MUST be exact headers from history_columns (vendor names vary wildly).
2. Prefer columns.csv point_role hints when present.
3. Prefer primary sensors over alarms/setpoints/status for the same point.
4. NEVER map timestamp / time / date / datetime columns — pandas already owns the time index.
5. Omit points you cannot map confidently — rules will SKIPPED_MISSING_ROLES rather than guess wrong.
6. Do not invent equip ids; use only those listed under Input.
7. Do NOT rewrite or regenerate CSV files — output JSON only.
8. equipType must be a Haystack-like type from the list above (not free text).

Input follows:
"""


def _infer_building_id(frames: dict[str, Any]) -> str:
    for df in frames.values():
        bid = str(df.attrs.get("building_id") or "").strip()
        if bid:
            return bid
    return "UNNAMED_BUILDING"


def _columns_csv_label(cols_path: Any, equipment_id: str) -> str | None:
    """Prefer a portable relative label over absolute OneDrive/machine paths."""
    if not cols_path:
        return None
    p = Path(str(cols_path))
    try:
        parts = p.parts
        if len(parts) >= 3 and parts[-1].lower() == "columns.csv":
            return "/".join(parts[-3:])
    except Exception:
        pass
    return f"{equipment_id}/columns.csv"


def build_llm_prompt_for_frames(
    frames: dict[str, Any],
    *,
    building_id: str = DEFAULT_BUILDING_ID,
    site_ref: str = DEFAULT_SITE_REF,
    max_columns_per_equipment: int = 80,
) -> str:
    """Full copy-paste prompt: Haystack instructions + per-equip column inventory."""
    resolved_id = (building_id or "").strip() or _infer_building_id(frames)
    lines = [
        LLM_COLUMN_MAP_PROMPT.rstrip(),
        "",
        f"siteRef: {site_ref or DEFAULT_SITE_REF}",
        f"building: {resolved_id}",
        f"equip_count: {len(frames)}",
        "",
        "IMPORTANT: Do not modify or regenerate CSV files. Return only the Haystack-style JSON map.",
        "building is whatever folder was loaded (any site name — use the value above).",
        "Emit one equip entry per id below (many ahu + vav devices is normal).",
        "Skip timestamp columns; map only HVAC points.",
        "",
    ]
    for eq_id in sorted(frames.keys(), key=lambda x: natural_key(str(x))):
        df = frames[eq_id]
        etype = str(df.attrs.get("equipment_type") or equipment_type_from_id(eq_id))
        hs_type = COOKBOOK_EQUIP_TO_HAYSTACK.get(etype, etype.lower())
        cols = [str(c) for c in df.columns]
        if len(cols) > max_columns_per_equipment:
            cols = cols[:max_columns_per_equipment] + [
                f"... ({len(df.columns) - max_columns_per_equipment} more)"
            ]
        cols_label = _columns_csv_label(df.attrs.get("columns_path"), str(eq_id))
        lines.append(f"### equip={eq_id}  equipType={hs_type}  device={eq_id}")
        if cols_label:
            lines.append(f"columns_csv: {cols_label}")
        if isinstance(df.index, pd.DatetimeIndex) or getattr(df.index, "name", None) in {
            "timestamp",
            "timestamp_utc",
            "time",
            "datetime",
        }:
            lines.append("time_index: pandas DatetimeIndex (do not map as a point)")
        lines.append("history_columns:")
        for c in cols:
            lines.append(f"  - {c}")
        lines.append("")
    lines.append("Return the JSON object now.")
    return "\n".join(lines)
