"""Simple YAML role mapping — flat and nested multi-site (no Haystack/Oxigraph)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import yaml

from open_fdd.analytics.mapping_wizard import (
    DEFAULT_BUILDING_ID,
    DEFAULT_SITE_ID,
    flat_role_map_from_sites,
    is_nested_role_map,
    load_site_mapping,
    save_site_mapping,
    sites_from_yaml,
    wrap_flat_role_map,
)

ROLE_ALIASES = {
    "outside_air_temp": "outdoor_air_intake_temperature",
    "outside_air_temp_f": "outdoor_air_intake_temperature",
    "discharge_air_temp": "discharge_air_temperature",
    "discharge_air_temp_f": "discharge_air_temperature",
    "return_air_temp": "return_air_temperature",
    "mixed_air_temp": "mixed_air_temperature",
    "zone_temp": "zone_air_temperature",
    "space_temp": "zone_air_temperature",
    "supply_fan_cmd": "supply_fan_command",
    "cooling_valve": "cooling_valve_position_command",
    "outdoor_air_damper": "outdoor_air_intake_damper_position_command",
}

POINT_ROLE_CANONICAL: dict[str, str] = {
    "discharge_air_temp": "discharge_air_temperature",
    "return_air_temp": "return_air_temperature",
    "mixed_air_temp": "mixed_air_temperature",
    "outside_air_temp": "outdoor_air_intake_temperature",
    "oat": "outdoor_air_intake_temperature",
    "zone_temp": "zone_air_temperature",
    "space_temp": "zone_air_temperature",
    "chw_valve": "cooling_valve_position_command",
    "cooling_valve": "cooling_valve_position_command",
    "heating_valve": "heating_valve_position_command",
    "hw_valve": "heating_valve_position_command",
    "reheat_valve": "terminal_unit_heating_valve_position_command",
    # Zone / VAV damper (not OA) — never treat generic "damper_position" as OA damper
    "damper_position": "damper_position",
    "zone_damper": "damper_position",
    "vav_damper": "damper_position",
    "oa_damper": "outdoor_air_intake_damper_position_command",
    "outdoor_air_damper": "outdoor_air_intake_damper_position_command",
    "airflow": "discharge_air_volume_flow_rate",
    "supply_fan_command": "supply_fan_command",
    "fan_speed": "supply_fan_command",
    "supply_fan": "supply_fan_command",
    "return_fan_speed": "return_fan_command",
    "return_fan_cmd": "return_fan_command",
    "supply_fan_operating_status": "supply_fan_operating_status",
    "occupancy_status": "occupancy_status",
    "chw_supply": "supply_chilled_water_temperature",
    "chw_return": "return_chilled_water_temperature",
    "chiller": "chiller_operating_status",
    "chiller_command": "chiller_operating_status",
    "power": "chiller_electric_power",
    "chilled_water_pump_operating_status": "chilled_water_pump_operating_status",
    "chw_pump": "chilled_water_pump_command",
    "primary_chw_pump_status": "chilled_water_pump_operating_status",
    "primary_chw_pump": "chilled_water_pump_operating_status",
}

COL_PATTERN_ROLES: list[tuple[tuple[str, ...], str]] = [
    (("discharge_air_temp_f", "da-t"), "discharge_air_temperature"),
    (("dat_reset", "discharge_air_temperature_setpoint", "sat_setpoint"), "discharge_air_temperature_setpoint"),
    (("return_air_temp", "ra-t"), "return_air_temperature"),
    (("mixed_air_temp", "mixed_air_temperature"), "mixed_air_temperature"),
    # Prefer real OAT columns — not oat_*_setpoint / enable setpoints
    (("outside_air_temp", "oa-t", "oat_f"), "outdoor_air_intake_temperature"),
    (("ex_dmpr", "oa_damper", "outdoor_air_damper", "oad_pos"), "outdoor_air_intake_damper_position_command"),
    (("chw_valve", "clg_valve", "cooling_valve"), "cooling_valve_position_command"),
    (("hw_valve", "htg_valve", "heating_valve"), "heating_valve_position_command"),
    # Supply fan before generic fan_speed (avoids return_fan_speed winning)
    (("supply_fan_speed", "supply_fan_cmd"), "supply_fan_command"),
    (("return_fan_speed", "return_fan_cmd", "rf_speed"), "return_fan_command"),
    (("supply_fan_status", "supplyfanstatus"), "supply_fan_operating_status"),
    (("supply_fan_command",), "supply_fan_command"),
    (("supply_fan_operating_status", "fan_proof"), "supply_fan_operating_status"),
    (("da_p_setpoint", "discharge_air_static_pressure_setpoint"), "discharge_air_static_pressure_setpoint"),
    (("da_p_inwc", "discharge_air_static_pressure"), "discharge_air_static_pressure"),
    (("space_temp", "spacetemp"), "zone_air_temperature"),
    (("reheat_valve", "rht_valve", "reheat"), "terminal_unit_heating_valve_position_command"),
    # Prefer actuator *command* over position feedback for PID hunting
    (("vavactuatorcommand", "vav_actuator_cmd", "actuatorcommand"), "damper_position"),
    (("damper_position", "damper_pos", "dpr_pos", "vavactuatorposition", "vavactuator"), "damper_position"),
    (("mad_c_pct", "mad_c", "mixed_air_damper"), "outdoor_air_intake_damper_position_command"),
    (("actflow", "airflow_cfm"), "discharge_air_volume_flow_rate"),
    (("minflowsp", "min_airflow"), "discharge_air_volume_flow_rate_minimum"),
    (("vav_disch", "dischargeairtemp"), "terminal_unit_discharge_air_temperature"),
    (("ductintemp", "duct_in"), "terminal_unit_inlet_air_temperature"),
    # Central plant
    (("chws_t", "chw_supply", "chilled_water_supply"), "supply_chilled_water_temperature"),
    (("chwr_t", "chw_return", "chilled_water_return"), "return_chilled_water_temperature"),
    (("hws_t", "hw_supply"), "supply_hot_water_temperature"),
    (("hwr_t", "hw_return"), "return_hot_water_temperature"),
    (("chiller_1_command", "chiller_2_command", "chiller_command"), "chiller_operating_status"),
    (("chiller_1_amps", "chiller_2_amps", "amps_a"), "chiller_electric_current"),
    (("power_demand_this_interval", "meter_power_sum_kw", "elec_kw", "building_kw"), "elec-power"),
    (("chiller_electric_power", "meter_chiller"), "chiller_electric_power"),
    (("gas_flow", "nat_gas", "gas_therm", "gas_cfh"), "gas-flow"),
    (("hwp1_c", "hwp2_c", "hwp3_c", "hw_pump_cmd", "hw_pump_speed"), "hw-pump-cmd"),
    (("hwp1_s", "hwp2_s", "hwp3_s", "pump_operating_status"), "pump_operating_status"),
    # Designated CHW pump for chiller runtime (data-model role; prefer over chiller cmd)
    (("chilled_water_pump_operating_status", "cwp1_s", "cwp2_s", "primary_chw_pump_status"), "chilled_water_pump_operating_status"),
    (("chilled_water_pump_command", "cwp1_c", "cwp2_c", "primary_chw_pump_cmd", "chw_pump_speed"), "chilled_water_pump_command"),
    (("condenser_water_pump_command", "tower_pump_cmd", "condenser_pump"), "condenser_water_pump_command"),
    (("cooling_tower_fan_command", "tower_fan_speed", "cw_fan_cmd", "ct_fan_speed", "cooling_tower_fan"), "cooling_tower_fan_command"),
]

ROLE_COLUMN_RANK: dict[str, tuple[str, ...]] = {
    "zone_air_temperature": ("spacetemp", "space_temp", "zone_temp"),
    "discharge_air_volume_flow_rate": ("actflow", "flow_input", "airflow"),
    "discharge_air_volume_flow_rate_minimum": ("minflowsp", "min_airflow"),
    "discharge_air_temperature": ("discharge_air_temp_f", "da-t"),
    "discharge_air_temperature_setpoint": ("dat_reset", "discharge_air_temperature_setpoint"),
    "outdoor_air_intake_damper_position_command": ("ex_dmpr", "oa_damper", "outdoor_air_damper", "mad_c"),
    "damper_position": ("vavactuatorcommand", "actuatorcommand", "damper_position", "dpr_pos"),
    # Prefer supply fan over return fan for AHU runtime
    "supply_fan_command": ("supply_fan_speed", "supply_fan", "sf_", "supply_fan_command"),
    "supply_fan_operating_status": ("supply_fan_status", "supplyfanstatus", "supply_fan", "supply_fan_operating_status"),
    "outdoor_air_intake_temperature": ("outside_air_temp", "outdoor_air_intake_temperature", "oat_f"),
    "supply_chilled_water_temperature": ("chws_t", "chw_supply"),
    "return_chilled_water_temperature": ("chwr_t", "chw_return"),
    "chiller_operating_status": ("chiller_1_command", "chiller_2_command", "chiller_command", "command"),
    "chiller_electric_current": ("amps_a", "current_sum", "amps"),
    "chiller_electric_power": ("power_demand_this_interval", "meter_power_sum", "power"),
    "hw-pump-cmd": ("hwp1_c", "hwp2_c", "hw_pump"),
    "pump_operating_status": ("hwp1_s", "hwp2_s", "pump_operating_status"),
    "chilled_water_pump_operating_status": ("chilled_water_pump_operating_status", "cwp1_s", "cwp2_s", "primary_chw_pump"),
    "chilled_water_pump_command": ("chilled_water_pump_command", "cwp1_c", "cwp2_c"),
}


def _canonical_role(point_role: str, col: str) -> str | None:
    pr = point_role.strip().lower()
    if pr in POINT_ROLE_CANONICAL:
        return POINT_ROLE_CANONICAL[pr]
    if pr in ROLE_ALIASES:
        return ROLE_ALIASES[pr]
    cl = col.lower()
    for patterns, role in COL_PATTERN_ROLES:
        if any(p in cl for p in patterns):
            return role
    return None


def _rank_column(role: str, col: str) -> int:
    cl = col.lower()
    # Hard demote return-fan columns when mapping supply fan roles
    if role in {"supply_fan_command", "supply_fan_operating_status"} and "return" in cl:
        return 90
    # Demote setpoints / min-position masquerading as OA damper command
    if role == "outdoor_air_intake_damper_position_command" and (
        "setpoint" in cl
        or "minimum" in cl
        or "min_pos" in cl
        or "minpos" in cl
        or "enable" in cl
    ):
        return 95
    # Zone damper role must not steal AHU OA / MAD columns
    if role == "damper_position" and any(
        x in cl for x in ("ex_dmpr", "oa_damper", "outdoor_air", "mad_c", "oad_")
    ):
        return 95
    # Prefer outdoor / exhaust damper cmd over mixed-air damper for outdoor_air_intake_damper_position_command
    if role == "outdoor_air_intake_damper_position_command" and "mad_c" in cl and "ex_dmpr" not in cl and "oa_damper" not in cl:
        return 35
    # Demote setpoints masquerading as OAT
    if role == "outdoor_air_intake_temperature" and ("setpoint" in cl or "enable" in cl or "reset" in cl):
        return 95
    # Never treat terminal load % as a control AO role
    if "terminalload" in cl or "terminal_load" in cl:
        return 100
    prefs = ROLE_COLUMN_RANK.get(role, ())
    for i, p in enumerate(prefs):
        if p in cl:
            return i
    if "alarm" in cl or "limit" in cl or ("setpoint" in cl and role == "zone_air_temperature"):
        return 100
    return 50


def load_role_map(path: Path) -> dict[str, dict[str, str]]:
    """Load flat equipment→roles map (nested YAML is unwrapped)."""
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return {}
    if is_nested_role_map(data):
        return flat_role_map_from_sites(sites_from_yaml(data))
    return {str(k): {str(r): str(c) for r, c in v.items()} for k, v in data.items() if isinstance(v, dict)}


def load_role_map_nested(path: Path):
    return load_site_mapping(path)


def save_role_map(path: Path, mapping: dict[str, dict[str, str]], *, nested: bool = False) -> None:
    if nested:
        save_site_mapping(path, wrap_flat_role_map(mapping))
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(mapping, sort_keys=True), encoding="utf-8")


def roles_from_columns_csv(columns_path: Path | None) -> dict[str, str]:
    if columns_path is None or not Path(columns_path).is_file():
        return {}
    df = pd.read_csv(columns_path)
    col_key = "column" if "column" in df.columns else "col" if "col" in df.columns else df.columns[0]
    role_key = next((c for c in ("point_role", "role") if c in df.columns), None)
    candidates: dict[str, list[tuple[int, str]]] = {}
    for _, row in df.iterrows():
        col = str(row[col_key]).strip()
        if not col or col in ("col", "column"):
            continue
        pr = str(row[role_key]).strip() if role_key else ""
        role = _canonical_role(pr, col) if pr else None
        if role is None:
            for patterns, r in COL_PATTERN_ROLES:
                if any(p in col.lower() for p in patterns):
                    role = r
                    break
        if role is None:
            continue
        candidates.setdefault(role, []).append((_rank_column(role, col), col))
    out: dict[str, str] = {}
    for role, opts in candidates.items():
        opts.sort(key=lambda x: x[0])
        # Skip demoted matches (return-fan, OAT setpoints, etc.) when nothing better exists
        if opts[0][0] >= 90:
            continue
        out[role] = opts[0][1]
    return out


def enrich_role_map_from_equipment(
    role_map: dict[str, dict[str, str]],
    equipment_id: str,
    columns_path: Path | None,
    history_columns: list[str] | None = None,
) -> dict[str, dict[str, str]]:
    """Fill missing roles only — never overwrite an existing mapping with a weaker heuristic."""
    merged = dict(role_map.get(equipment_id, {}))
    for role, col in roles_from_columns_csv(columns_path).items():
        if role not in merged:
            merged[role] = col
    if history_columns:
        suggested = suggest_roles(pd.DataFrame(columns=history_columns))
        for role, col in suggested.items():
            if role not in merged:
                merged[role] = col
            elif _rank_column(role, col) < _rank_column(role, merged[role]):
                merged[role] = col
        # If fan roles point at return fan but supply exists, upgrade
        for role in ("supply_fan_command", "supply_fan_operating_status"):
            col = merged.get(role)
            if col and "return" in col.lower():
                better = suggested.get(role)
                if better and "supply" in better.lower():
                    merged[role] = better
        allowed = set(history_columns)
        merged = {role: col for role, col in merged.items() if col in allowed}
    role_map[equipment_id] = merged
    return role_map


def suggest_roles(df: pd.DataFrame) -> dict[str, str]:
    out: dict[str, str] = {}
    for col in df.columns:
        for patterns, role in COL_PATTERN_ROLES:
            if any(p in col.lower() for p in patterns):
                if role not in out or _rank_column(role, col) < _rank_column(role, out[role]):
                    out[role] = col
                break
    return out


def apply_role_map(df: pd.DataFrame, equipment_id: str, role_map: dict[str, dict[str, str]]) -> pd.DataFrame:
    eq_map = role_map.get(equipment_id, {})
    out = df.copy()
    # Meta keys are equipment links / notes — not timeseries columns
    skip = {"chw_pump_equipment", "notes", "equipment_type", "equipType", "plant_group"}
    for role, col in eq_map.items():
        if role in skip or not col or not isinstance(col, str):
            continue
        if col in out.columns:
            out[role] = pd.to_numeric(out[col], errors="coerce")
    return out


def is_flat_role_map(role_map: dict) -> bool:
    """True for a flat ``{column: role}`` map (the parity dataset / CSV shape) rather than ``{equipment: {role: column}}``."""
    return bool(role_map) and not any(isinstance(v, dict) for v in role_map.values())


def coerce_role_map(role_map: dict, frames: dict, *, equipment_type: str = "AHU") -> dict:
    """Return the nested ``{equipment: {role: column}}`` map the analytics functions use.

    A nested map is returned unchanged. A flat ``{column: role}`` map is applied to every frame (only the columns that frame
    has) and each equipment gets ``equipment_type`` (the frame's own ``attrs["equipment_type"]`` wins), so a flat map can never
    silently match nothing.
    """
    if not is_flat_role_map(role_map):
        return role_map
    out: dict[str, dict[str, str]] = {}
    for eq, frame in frames.items():
        cols = set(getattr(frame, "columns", []))
        eq_map = {role: col for col, role in role_map.items() if col in cols and isinstance(role, str)}
        eq_map["equipment_type"] = str((getattr(frame, "attrs", None) or {}).get("equipment_type") or equipment_type)
        out[eq] = eq_map
    return out


def resolve_role(df: pd.DataFrame, equipment_id: str, role_map: dict, role: str) -> pd.Series | None:
    mapped = apply_role_map(df, equipment_id, role_map)
    if role in mapped.columns:
        return mapped[role]
    return None


def validate_required_roles(equipment_id: str, df: pd.DataFrame, role_map: dict, required: list[str]) -> list[str]:
    mapped = apply_role_map(df, equipment_id, role_map)
    return [r for r in required if r not in mapped.columns or mapped[r].isna().all()]


__all__ = [
    "DEFAULT_BUILDING_ID",
    "DEFAULT_SITE_ID",
    "apply_role_map",
    "coerce_role_map",
    "is_flat_role_map",
    "enrich_role_map_from_equipment",
    "load_role_map",
    "load_role_map_nested",
    "roles_from_columns_csv",
    "save_role_map",
    "suggest_roles",
    "validate_required_roles",
]
