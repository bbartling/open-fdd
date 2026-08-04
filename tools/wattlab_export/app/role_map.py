"""Simple YAML role mapping — flat and nested multi-site (no Haystack/Oxigraph)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import yaml

from app.mapping_wizard import (
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
    "outside_air_temp": "outside-air-temp",
    "outside_air_temp_f": "outside-air-temp",
    "discharge_air_temp": "discharge-air-temp",
    "discharge_air_temp_f": "discharge-air-temp",
    "return_air_temp": "return-air-temp",
    "mixed_air_temp": "mixed-air-temp",
    "zone_temp": "zone-air-temp",
    "space_temp": "zone-air-temp",
    "supply_fan_cmd": "fan-cmd",
    "cooling_valve": "cooling-valve",
    "outdoor_air_damper": "outside-air-damper",
}

POINT_ROLE_CANONICAL: dict[str, str] = {
    "discharge_air_temp": "discharge-air-temp",
    "return_air_temp": "return-air-temp",
    "mixed_air_temp": "mixed-air-temp",
    "outside_air_temp": "outside-air-temp",
    "oat": "outside-air-temp",
    "zone_temp": "zone-air-temp",
    "space_temp": "zone-air-temp",
    "chw_valve": "cooling-valve",
    "cooling_valve": "cooling-valve",
    "heating_valve": "heating-valve",
    "hw_valve": "heating-valve",
    "reheat_valve": "reheat-valve",
    # Zone / VAV damper (not OA) — never treat generic "damper" as OA damper
    "damper": "damper",
    "zone_damper": "damper",
    "vav_damper": "damper",
    "oa_damper": "outside-air-damper",
    "outdoor_air_damper": "outside-air-damper",
    "airflow": "zone-airflow",
    "fan_cmd": "fan-cmd",
    "fan_speed": "fan-cmd",
    "supply_fan": "fan-cmd",
    "return_fan_speed": "return-fan-cmd",
    "return_fan_cmd": "return-fan-cmd",
    "fan_status": "fan-status",
    "occ_mode": "occupied",
    "chw_supply": "chilled-water-supply-temp",
    "chw_return": "chilled-water-return-temp",
    "chiller": "chiller-status",
    "chiller_command": "chiller-status",
    "power": "chiller-power",
    "chw_pump_status": "chw-pump-status",
    "chw_pump": "chw-pump-cmd",
    "primary_chw_pump_status": "chw-pump-status",
    "primary_chw_pump": "chw-pump-status",
}

COL_PATTERN_ROLES: list[tuple[tuple[str, ...], str]] = [
    (("discharge_air_temp_f", "da-t"), "discharge-air-temp"),
    (("dat_reset", "sat_sp", "sat_setpoint"), "discharge-air-temp-sp"),
    (("return_air_temp", "ra-t"), "return-air-temp"),
    (("mixed_air_temp", "mat"), "mixed-air-temp"),
    # Prefer real OAT columns — not oat_*_setpoint / enable setpoints
    (("outside_air_temp", "oa-t", "oat_f"), "outside-air-temp"),
    (("ex_dmpr", "oa_damper", "outdoor_air_damper", "oad_pos"), "outside-air-damper"),
    (("chw_valve", "clg_valve", "cooling_valve"), "cooling-valve"),
    (("hw_valve", "htg_valve", "heating_valve"), "heating-valve"),
    # Supply fan before generic fan_speed (avoids return_fan_speed winning)
    (("supply_fan_speed", "supply_fan_cmd"), "fan-cmd"),
    (("return_fan_speed", "return_fan_cmd", "rf_speed"), "return-fan-cmd"),
    (("supply_fan_status", "supplyfanstatus"), "fan-status"),
    (("fan_cmd",), "fan-cmd"),
    (("fan_status", "fan_proof"), "fan-status"),
    (("da_p_setpoint", "duct_static_sp"), "duct-static-pressure-sp"),
    (("da_p_inwc", "duct_static"), "duct-static-pressure"),
    (("space_temp", "spacetemp"), "zone-air-temp"),
    (("reheat_valve", "rht_valve", "reheat"), "reheat-valve"),
    # Prefer actuator *command* over position feedback for PID hunting
    (("vavactuatorcommand", "vav_actuator_cmd", "actuatorcommand"), "damper"),
    (("damper_pct", "damper_pos", "dpr_pos", "vavactuatorposition", "vavactuator"), "damper"),
    (("mad_c_pct", "mad_c", "mixed_air_damper"), "outside-air-damper"),
    (("actflow", "airflow_cfm"), "zone-airflow"),
    (("minflowsp", "min_airflow"), "min-flow-sp"),
    (("vav_disch", "dischargeairtemp"), "vav-discharge-air-temp"),
    (("ductintemp", "duct_in"), "vav-inlet-air-temp"),
    # Central plant
    (("chws_t", "chw_supply", "chilled_water_supply"), "chilled-water-supply-temp"),
    (("chwr_t", "chw_return", "chilled_water_return"), "chilled-water-return-temp"),
    (("hws_t", "hw_supply"), "hot-water-supply-temp"),
    (("hwr_t", "hw_return"), "hot-water-return-temp"),
    (("chiller_1_command", "chiller_2_command", "chiller_command"), "chiller-status"),
    (("chiller_1_amps", "chiller_2_amps", "amps_a"), "chiller-amps"),
    (("power_demand_this_interval", "meter_power_sum_kw", "elec_kw", "building_kw"), "elec-power"),
    (("chiller_power", "meter_chiller"), "chiller-power"),
    (("gas_flow", "nat_gas", "gas_therm", "gas_cfh"), "gas-flow"),
    (("hwp1_c", "hwp2_c", "hwp3_c", "hw_pump_cmd", "hw_pump_speed"), "hw-pump-cmd"),
    (("hwp1_s", "hwp2_s", "hwp3_s", "pump_status"), "pump-status"),
    # Designated CHW pump for chiller runtime (data-model role; prefer over chiller cmd)
    (("chw_pump_status", "cwp1_s", "cwp2_s", "primary_chw_pump_status"), "chw-pump-status"),
    (("chw_pump_cmd", "cwp1_c", "cwp2_c", "primary_chw_pump_cmd", "chw_pump_speed"), "chw-pump-cmd"),
    (("cw_pump_cmd", "tower_pump_cmd", "condenser_pump"), "cw-pump-cmd"),
    (("tower_fan_cmd", "tower_fan_speed", "cw_fan_cmd", "ct_fan_speed", "cooling_tower_fan"), "tower-fan-cmd"),
]

ROLE_COLUMN_RANK: dict[str, tuple[str, ...]] = {
    "zone-air-temp": ("spacetemp", "space_temp", "zone_temp"),
    "zone-airflow": ("actflow", "flow_input", "airflow"),
    "min-flow-sp": ("minflowsp", "min_airflow"),
    "discharge-air-temp": ("discharge_air_temp_f", "da-t"),
    "discharge-air-temp-sp": ("dat_reset", "sat_sp"),
    "outside-air-damper": ("ex_dmpr", "oa_damper", "outdoor_air_damper", "mad_c"),
    "damper": ("vavactuatorcommand", "actuatorcommand", "damper_pct", "dpr_pos"),
    # Prefer supply fan over return fan for AHU runtime
    "fan-cmd": ("supply_fan_speed", "supply_fan", "sf_", "fan_cmd"),
    "fan-status": ("supply_fan_status", "supplyfanstatus", "supply_fan", "fan_status"),
    "outside-air-temp": ("outside_air_temp", "oa_t", "oat_f"),
    "chilled-water-supply-temp": ("chws_t", "chw_supply"),
    "chilled-water-return-temp": ("chwr_t", "chw_return"),
    "chiller-status": ("chiller_1_command", "chiller_2_command", "chiller_command", "command"),
    "chiller-amps": ("amps_a", "current_sum", "amps"),
    "chiller-power": ("power_demand_this_interval", "meter_power_sum", "power"),
    "hw-pump-cmd": ("hwp1_c", "hwp2_c", "hw_pump"),
    "pump-status": ("hwp1_s", "hwp2_s", "pump_status"),
    "chw-pump-status": ("chw_pump_status", "cwp1_s", "cwp2_s", "primary_chw_pump"),
    "chw-pump-cmd": ("chw_pump_cmd", "cwp1_c", "cwp2_c"),
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
    if role in {"fan-cmd", "fan-status"} and "return" in cl:
        return 90
    # Demote setpoints / min-position masquerading as OA damper command
    if role == "outside-air-damper" and (
        "setpoint" in cl or "minimum" in cl or "min_pos" in cl or "minpos" in cl
    ):
        return 95
    # Zone damper role must not steal AHU OA / MAD columns
    if role == "damper" and any(
        x in cl for x in ("ex_dmpr", "oa_damper", "outdoor_air", "mad_c", "oad_")
    ):
        return 95
    # Prefer outdoor / exhaust damper cmd over mixed-air damper for oa_damper_pct
    if role == "outside-air-damper" and "mad_c" in cl and "ex_dmpr" not in cl and "oa_damper" not in cl:
        return 35
    # Demote setpoints masquerading as OAT
    if role == "outside-air-temp" and ("setpoint" in cl or "enable" in cl or "reset" in cl):
        return 95
    # Never treat terminal load % as a control AO role
    if "terminalload" in cl or "terminal_load" in cl:
        return 100
    prefs = ROLE_COLUMN_RANK.get(role, ())
    for i, p in enumerate(prefs):
        if p in cl:
            return i
    if "alarm" in cl or "limit" in cl or ("setpoint" in cl and role == "zone-air-temp"):
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
        for role in ("fan-cmd", "fan-status"):
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
    skip = {"chw_pump_equipment", "notes", "equipment_type", "plant_group"}
    for role, col in eq_map.items():
        if role in skip or not col or not isinstance(col, str):
            continue
        if col in out.columns:
            out[role] = pd.to_numeric(out[col], errors="coerce")
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
    "enrich_role_map_from_equipment",
    "load_role_map",
    "load_role_map_nested",
    "roles_from_columns_csv",
    "save_role_map",
    "suggest_roles",
    "validate_required_roles",
]
