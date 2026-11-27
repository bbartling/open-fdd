"""Canonical point roles (``roles/openfdd-roles.json``) and the 5.0.x legacy-key reader.

Rule inputs, the catalog and the API use ``role``. ``legacy_keys`` and ``aliases`` resolve old
Open-FDD keys and the names the other vocabularies used. Ambiguous legacy names are not mapped
to one role: the caller decides from the point's function marker.
"""
from __future__ import annotations

import json
import warnings
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
ROLES_PATH = ROOT / "roles" / "openfdd-roles.json"
# 5.0.x pandas column names (role_map values such as discharge-air-temp). The file is the old
# key -> column map; both the key and the column resolve to the canonical role.
COLUMN_ALIASES_PATH = Path(__file__).resolve().parent / "data" / "pandas_column_aliases.json"

# Saved tuning keys that were 0-1 fraction thresholds on a position or a ratio, multiplied by 100 once.
# Boolean-gate keys (fan_on_min and the like) are retired and are not scaled.
PERCENT_PARAMETER_KEYS = frozenset({
    "valve_open_pct", "valve_open", "valve_shut", "econ1_damper_max", "econ2_damper",
    "clg_open_min", "econ3_damper_hi", "htg_open_min", "econ6_damper_max", "econ7_damper_min",
    "eps_vfd_spd", "clg_on_min", "econ_full_open", "econ_min_pos", "clg_full_min",
    "oa_damper_econ_low", "clg_inactive_max", "htg_on_min", "htg_full_min", "damper_low",
    "command_min", "position_error", "mode_valve_min", "null_fraction", "min_oa_frac",
    "reset_slope", "always_on_pct", "eps_airflow", "reheat_pct", "full_open_pct",
    "damper_closed_max", "reheat_cmd",
})
# These stay in percent inside the pandas rule (the ratio is scaled there). reset_slope is divided
# back to a per-degree slope at the rule input, so it is not in this set.
RAW_PERCENT_KEYS = frozenset({"null_fraction", "always_on_pct", "min_oa_frac", "eps_airflow"})
RETIRED_BOOLEAN_GATES = frozenset({"fan_on_min", "pump_hi", "tower_fan_hi", "load_sat_hi"})
CORE_VERSION = 5


@lru_cache(maxsize=1)
def load_roles() -> dict[str, Any]:
    return json.loads(ROLES_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def roles_by_name() -> dict[str, dict[str, Any]]:
    return {row["role"]: row for row in load_roles()["roles"]}


def rule_input_names() -> list[str]:
    """Canonical roles with ``rule_input: true``, sorted. ``supply_fan_speed_command`` is not one of them in 1.1.0."""
    return sorted(name for name, row in roles_by_name().items() if row.get("rule_input"))


def wire_unit(row: Mapping[str, Any]) -> str | None:
    """QUDT local name (``DEG_C``), or None for a boolean or enumeration."""
    unit = row.get("unit")
    if not unit:
        return None
    return str(unit).split(":", 1)[-1]


def contract_scale(row: Mapping[str, Any]) -> str:
    """Scale token stored on the input contract and the catalog."""
    unit = wire_unit(row)
    if unit:
        return unit
    if row.get("value_type") == "enumeration":
        return "enumeration"
    return "boolean"


@lru_cache(maxsize=1)
def _name_index() -> tuple[dict[str, str], frozenset[str]]:
    """(legacy or alias -> role, ambiguous names that must not be aliased)."""
    doc = load_roles()
    ambiguous = frozenset(doc.get("ambiguous_legacy_names") or {})
    out: dict[str, str] = {}
    for row in doc["roles"]:
        for key in list(row.get("legacy_keys") or []) + list(row.get("aliases") or []):
            if key in ambiguous or key == row["role"]:
                continue
            out[key] = row["role"]
    if COLUMN_ALIASES_PATH.is_file():
        previous = json.loads(COLUMN_ALIASES_PATH.read_text(encoding="utf-8"))
        for key, column in previous.items():
            role = out.get(key)
            if not role or key in ambiguous:
                continue
            for alias in (key, column):
                if alias in ambiguous or alias in out or alias == role:
                    continue
                out[alias] = role
    return out, ambiguous


def legacy_to_role() -> dict[str, str]:
    return dict(_name_index()[0])


def ambiguous_legacy_names() -> frozenset[str]:
    return _name_index()[1]


def resolve_role(name: str, *, warn: bool = False) -> str:
    """Canonical role for ``name``. A legacy key or alias warns once when ``warn`` is set.

    An unknown name, including an ambiguous legacy name, is returned unchanged.
    """
    if name in roles_by_name():
        return name
    mapped = _name_index()[0].get(name)
    if mapped is None:
        return name
    if warn:
        warnings.warn(
            f"role name {name!r} is a legacy key; use {mapped!r} (removed in 6.0)",
            DeprecationWarning,
            stacklevel=2,
        )
    return mapped


def rename_columns(frame, *, warn: bool = True):
    """Rename a DataFrame's legacy role columns to canonical names. Other columns stay."""
    import pandas as pd

    if not isinstance(frame, pd.DataFrame):
        raise TypeError("rename_columns expects a DataFrame")
    mapping = {}
    for column in frame.columns:
        key = str(column)
        if key in roles_by_name():
            continue
        mapped = _name_index()[0].get(key)
        if mapped and mapped not in frame.columns:
            mapping[column] = mapped
    if mapping and warn:
        warnings.warn(
            "legacy role columns renamed to canonical roles (removed in 6.0): "
            + ", ".join(f"{old} -> {new}" for old, new in sorted(mapping.items(), key=lambda kv: str(kv[0]))),
            DeprecationWarning,
            stacklevel=2,
        )
    return frame.rename(columns=mapping) if mapping else frame


def _scale_parameters(parameters: Mapping[str, Any]) -> dict[str, Any]:
    out = {}
    for key, value in parameters.items():
        if key in PERCENT_PARAMETER_KEYS and isinstance(value, (int, float)) and not isinstance(value, bool):
            out[key] = value * 100.0
        else:
            out[key] = value
    roles = out.get("roles")
    if isinstance(roles, dict):
        renamed = {}
        for role, spec in roles.items():
            renamed[resolve_role(str(role))] = spec
        out["roles"] = renamed
    sensors = out.get("sensors")
    if isinstance(sensors, dict):
        renamed_sensors = {}
        for series, spec in sensors.items():
            if isinstance(spec, dict) and "role" in spec:
                spec = {**spec, "role": resolve_role(str(spec["role"]))}
            renamed_sensors[series] = spec
        out["sensors"] = renamed_sensors
    return out


# Position roles whose stored samples were 0-1 fractions. si_scale 1 becomes 100; a previous
# percent-to-fraction factor of 0.01 becomes 1 (the sample is already percent).
_PERCENT_ROLES = None


def percent_roles() -> frozenset[str]:
    global _PERCENT_ROLES
    if _PERCENT_ROLES is None:
        _PERCENT_ROLES = frozenset(
            name for name, row in roles_by_name().items() if wire_unit(row) == "PERCENT"
        )
    return _PERCENT_ROLES


def migrate_saved(points: list[dict], configs: list[dict], version: int) -> tuple[list[dict], list[dict], int, bool]:
    """Rename stored roles and scale saved fraction tuning once.

    ``version`` is ``fdd.core_version``. At 5 or above the inputs are returned unchanged.
    Running it twice (the second call sees version 5) does not scale again.
    """
    if version >= CORE_VERSION:
        return points, configs, version, False
    percent = percent_roles()
    new_points = []
    for point in points:
        role = resolve_role(str(point.get("role") or ""))
        updated = {**point, "role": role or point.get("role")}
        scale = updated.get("si_scale", 1)
        if role in percent and isinstance(scale, (int, float)) and not isinstance(scale, bool):
            if abs(scale - 1.0) < 1e-12:
                updated["si_scale"] = 100.0
            elif abs(scale - 0.01) < 1e-12:
                updated["si_scale"] = 1.0
        new_points.append(updated)
    new_configs = []
    for config in configs:
        parameters = config.get("parameters") or {}
        if not isinstance(parameters, dict):
            new_configs.append(config)
            continue
        new_configs.append({**config, "parameters": _scale_parameters(parameters)})
    return new_points, new_configs, CORE_VERSION, True
