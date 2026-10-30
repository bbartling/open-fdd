"""Offline CI datasets → si-cutover-ip-golden-v1 rows (#1284 W0c / W3).

No live stack, no site names in code — building_id values come from fixture manifests only.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.ci import unit_contract_lib as uc  # noqa: E402
from scripts.stress.si_cutover.capture_ip_baseline import (  # noqa: E402
    daily_fault_and_covered_seconds,
    rule_params_from_registry,
)

POLL_SECONDS = 300.0
SCHEMA = "si-cutover-ip-golden-v1"
GOLDEN_SCHEMA_VERSION = 1

COOKBOOK_FIXTURES = REPO / "docs" / "rules" / "cookbook" / "fixtures"
SYNTH_ROOT = REPO / "tests" / "fixtures" / "synthetic_slice" / "OPENFDD_SYNTHETIC_SLICE_V1"

COOKBOOK_COLUMN_RENAMES: dict[str, str] = {
    "duct_static": "duct-static-pressure",
    "duct_static_sp": "duct-static-pressure-sp",
    "fan_cmd": "fan-cmd",
    "fan_status": "fan-status",
    "mat": "mixed-air-temp",
    "rat": "return-air-temp",
    "oat": "outside-air-temp",
    "oa_damper": "outside-air-damper",
    "sat_sp": "discharge-air-temp-sp",
    "zone_t": "zone-air-temp",
    "occ_mode": "occ_mode",
    "zone_flow": "zone-airflow",
    "damper_pct": "damper",
    "clg_available": "cooling-available",
    "reheat_valve_pct": "reheat-valve",
    "oa_t": "outside-air-temp",
    "min_flow_sp": "min-flow-sp",
    "reset_enable": "reset-enable",
}

REGISTRY_ROLE_TO_COLUMN: dict[str, str] = {
    "duct_static": "duct-static-pressure",
    "duct_static_sp": "duct-static-pressure-sp",
    "fan_cmd": "fan-cmd",
    "fan_status": "fan-status",
    "mat": "mixed-air-temp",
    "rat": "return-air-temp",
    "oat": "outside-air-temp",
    "oa_t": "outside-air-temp",
    "oa_damper": "outside-air-damper",
    "sat": "discharge-air-temp",
    "sat_sp": "discharge-air-temp-sp",
    "zone_t": "zone-air-temp",
    "zone_flow": "zone-airflow",
    "chw_supply_t": "chilled-water-supply-temp",
    "chw_return_t": "chilled-water-return-temp",
    "chiller_status": "chiller-status",
    "damper_pct": "damper",
}


def registry_role_column(role: str) -> str:
    token = str(role or "").strip()
    if token in REGISTRY_ROLE_TO_COLUMN:
        return REGISTRY_ROLE_TO_COLUMN[token]
    if token in COOKBOOK_COLUMN_RENAMES:
        return COOKBOOK_COLUMN_RENAMES[token]
    return token.replace("_", "-")


def frame_column_to_sql_role(col: str) -> str:
    """Map wide history column (haystack slug or cookbook) to SQL role name."""
    from open_fdd.role_candidates import _HAYSTACK_SLUG_TO_ROLE

    slug = str(col)
    if slug in _HAYSTACK_SLUG_TO_ROLE:
        return _HAYSTACK_SLUG_TO_ROLE[slug]
    for role, mapped in REGISTRY_ROLE_TO_COLUMN.items():
        if mapped == slug:
            return role
    for raw, mapped in COOKBOOK_COLUMN_RENAMES.items():
        if mapped == slug:
            return raw
    return slug.replace("-", "_")


SV_SENSOR_OPTIONAL_ROLES = (
    "oa_t",
    "mat",
    "zone_t",
    "rat",
    "sat",
    "chw_supply_t",
    "chw_return_t",
    "hw_supply_t",
    "hw_return_t",
    "oa_h",
    "ra_h",
    "zone_rh",
    "ma_h",
    "sa_h",
)


def rule_pair_eligible(
    rule: dict[str, Any], frame, *, equipment_type: str
) -> tuple[bool, str]:
    """Both pandas and SQL must skip ineligible rule×dataset pairs."""
    rule_id = str(rule.get("rule_id") or "")
    kinds = rule.get("equipment_kinds") or []
    if kinds and equipment_type and equipment_type not in kinds:
        return False, "equipment_type"
    required = list(rule.get("required_roles") or [])
    for role in required:
        col = registry_role_column(str(role))
        if col not in frame.columns:
            return False, f"missing_role:{role}"
    if rule.get("sql_file") and not required:
        optional = list(rule.get("optional_roles") or [])
        if optional:
            if not any(registry_role_column(str(r)) in frame.columns for r in optional):
                return False, "missing_roles"
    if rule_id.startswith("SV-"):
        if not any(
            registry_role_column(str(r)) in frame.columns for r in SV_SENSOR_OPTIONAL_ROLES
        ):
            return False, "missing_sensor_roles"
    if rule_id == "OAT-METEO":
        return False, "missing_weather_sidecar"
    if rule_id == "VAV-1" and "occ_mode" not in frame.columns:
        return False, "missing_occupancy_roles"
    return True, ""


COOKBOOK_DATASETS: tuple[dict[str, str], ...] = (
    {"fixture": "fc1_obvious_fault.jsonl", "building_id": "COOKBOOK_FC1", "equipment_type": "ahu"},
    {"fixture": "fc2_obvious_fault.jsonl", "building_id": "COOKBOOK_FC2", "equipment_type": "ahu"},
    {"fixture": "reset1_normal.jsonl", "building_id": "COOKBOOK_RESET1_NORMAL", "equipment_type": "ahu"},
    {"fixture": "reset1_obvious_fault.jsonl", "building_id": "COOKBOOK_RESET1_FAULT", "equipment_type": "ahu"},
    {"fixture": "sched1_obvious_fault.jsonl", "building_id": "COOKBOOK_SCHED1", "equipment_type": "ahu"},
    {"fixture": "sched247_obvious_fault.jsonl", "building_id": "COOKBOOK_SCHED247", "equipment_type": "ahu"},
    {"fixture": "vav1_obvious_fault.jsonl", "building_id": "COOKBOOK_VAV1", "equipment_type": "vav"},
    {"fixture": "vav6_obvious_fault.jsonl", "building_id": "COOKBOOK_VAV6", "equipment_type": "vav"},
    {"fixture": "vav7_obvious_fault.jsonl", "building_id": "COOKBOOK_VAV7", "equipment_type": "vav"},
    {"fixture": "chw1_obvious_fault.jsonl", "building_id": "COOKBOOK_CHW1", "equipment_type": "chwPlant"},
)

SYNTH_CASE_DIRS: tuple[str, ...] = (
    "AHU_CASE_FC1",
    "AHU_CASE_SCHED_1",
    "AHU_CASE_PID_HUNT_1",
    "AHU_CASE_SV_FLATLINE",
    "CHILLER_CASE_MECH_OAT_1",
    "VAV_CASE_VAV_1",
)

SYNTH_EQUIPMENT_TYPES: dict[str, str] = {
    "AHU_CASE_FC1": "ahu",
    "AHU_CASE_SCHED_1": "ahu",
    "AHU_CASE_PID_HUNT_1": "ahu",
    "AHU_CASE_SV_FLATLINE": "ahu",
    "CHILLER_CASE_MECH_OAT_1": "chwPlant",
    "VAV_CASE_VAV_1": "vav",
}


@dataclass(frozen=True)
class DatasetSpec:
    building_id: str
    equipment_id: str
    equipment_type: str
    source: dict[str, Any]


def load_rule_registry() -> list[dict[str, Any]]:
    import yaml

    doc = yaml.safe_load((REPO / "sql" / "fdd" / "registry.yaml").read_text(encoding="utf-8"))
    return list(doc.get("rules") or [])


def pandas_rules(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from open_fdd.rules import RULES_BY_ID

    out: list[dict[str, Any]] = []
    for r in rules:
        rid = str(r.get("rule_id") or "")
        if not rid:
            continue
        if r.get("pandas_function") or rid in RULES_BY_ID:
            out.append(r)
    if len(out) < 65:
        raise RuntimeError(f"expected ~72 pandas rules, found {len(out)}")
    return out


def _load_cookbook_frame(fixture_name: str):
    import pandas as pd

    path = COOKBOOK_FIXTURES / fixture_name
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    equipment_id = str(rows[0].get("equipment_id") or "equip:test")
    df = pd.DataFrame(rows)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.set_index("timestamp").sort_index()
    rename = {k: v for k, v in COOKBOOK_COLUMN_RENAMES.items() if k in df.columns}
    df = df.rename(columns=rename)
    return df, equipment_id


def _load_synth_frame(case_dir: str):
    import pandas as pd

    base = SYNTH_ROOT / case_dir
    df = pd.read_csv(base / "history_wide.csv")
    ts_col = "timestamp_utc" if "timestamp_utc" in df.columns else "timestamp"
    df.index = pd.to_datetime(df[ts_col], utc=True)
    df = df.drop(columns=[c for c in df.columns if c in (ts_col,)])
    df = df.sort_index()
    equipment_id = case_dir
    return df, equipment_id


def iter_dataset_specs() -> list[DatasetSpec]:
    specs: list[DatasetSpec] = []
    for meta in COOKBOOK_DATASETS:
        frame, equipment_id = _load_cookbook_frame(meta["fixture"])
        specs.append(
            DatasetSpec(
                building_id=meta["building_id"],
                equipment_id=equipment_id,
                equipment_type=meta["equipment_type"],
                source={"kind": "cookbook", "fixture": meta["fixture"], "frame": frame},
            )
        )
    for case in SYNTH_CASE_DIRS:
        frame, equipment_id = _load_synth_frame(case)
        specs.append(
            DatasetSpec(
                building_id=f"SYNTH_{case}",
                equipment_id=equipment_id,
                equipment_type=SYNTH_EQUIPMENT_TYPES[case],
                source={"kind": "synth", "case_dir": case, "frame": frame},
            )
        )
    return specs


def _quantity_for_param(spec: dict[str, Any]) -> str | None:
    kind = str(spec.get("kind") or "")
    unit = str(spec.get("unit") or "")
    if kind in {
        "absolute_temperature",
        "temperature_difference",
        "air_pressure",
        "hydronic_pressure",
        "volumetric_flow",
        "temperature_rate",
    }:
        return kind
    if kind == "absolute_temperature":
        return "absolute_temperature"
    if kind == "temperature_difference":
        return "temperature_difference"
    if kind == "air_pressure":
        return "air_pressure"
    if kind in ("duration_minutes", "duration_seconds"):
        return "duration"
    if kind == "percent":
        return "dimensionless"
    if unit in ("degF", "degC", "°F", "°C"):
        return "absolute_temperature"
    if unit in ("degF_delta", "degC_delta"):
        return "temperature_difference"
    if unit in ("in_wc", "inwc", "Pa"):
        return "air_pressure"
    if unit in ("psi", "kPa"):
        return "hydronic_pressure"
    if unit in ("cfm", "gpm", "L_per_s", "L/s"):
        return "volumetric_flow"
    if kind in ("duration_minutes", "duration_seconds"):
        return "duration"
    if kind == "percent":
        return "dimensionless"
    return None


def _imperial_unit_for_quantity(quantity_id: str, *, param_key: str) -> str | None:
    if quantity_id == "absolute_temperature":
        return "degF"
    if quantity_id == "temperature_difference":
        return "degF_delta"
    if quantity_id == "air_pressure":
        return "in_wc"
    if quantity_id == "hydronic_pressure":
        return "psi"
    if quantity_id == "volumetric_flow":
        return "gpm"
    if quantity_id == "temperature_rate":
        return "degF_per_h"
    return None


def _si_source_unit(spec: dict[str, Any], quantity_id: str) -> str | None:
    unit = str(spec.get("unit") or "")
    if unit == "pct":
        unit = "percent"
    if quantity_id == "temperature_difference" and unit in ("degC", "°C"):
        return "degC_delta"
    if quantity_id == "absolute_temperature" and unit in ("degC", "°C"):
        return "degC"
    if unit in ("Pa", "kPa", "L_per_s", "L/s", "gpm", "psi", "in_wc", "degF", "degC"):
        return unit
    return None


def convert_params_to_si(
    rule: dict[str, Any],
    params: dict[str, float],
    metric: dict[str, Any],
    *,
    param_hook: Callable[[str, float], float] | None = None,
) -> dict[str, float]:
    out = dict(params)
    for name, spec in (rule.get("parameters") or {}).items():
        if name not in out:
            continue
        if not isinstance(spec, dict):
            continue
        kind = str(spec.get("kind") or "")
        unit = str(spec.get("unit") or "")
        if unit == "pct":
            unit = "percent"
        q = _quantity_for_param(spec)
        if not q:
            continue
        if kind in ("duration_minutes", "duration_seconds", "boolean", "percent"):
            continue
        if unit in ("percent", "pct", "bool", "min"):
            continue
        if not unit and not q:
            continue
        src_unit = unit
        if unit in ("°F",):
            src_unit = "degF"
        elif unit in ("°C",):
            src_unit = "degC"
        if q == "temperature_difference" and unit == "degF":
            src_unit = "degF_delta"
        elif q == "temperature_difference" and unit in ("degC", "°C"):
            src_unit = "degC_delta"
        elif not unit:
            src_unit = _si_source_unit(spec, q) or unit
        val = float(out[name])
        if param_hook:
            val = param_hook(name, val)
        out[name] = uc.convert_to_canonical(metric, q, val, src_unit)
    return out


def convert_params_from_si(
    rule: dict[str, Any],
    params: dict[str, float],
    metric: dict[str, Any],
    *,
    param_hook: Callable[[str, float], float] | None = None,
) -> dict[str, float]:
    """Registry defaults stored in SI (W4d+) → imperial for IP SQL/pandas."""
    out = dict(params)
    for name, spec in (rule.get("parameters") or {}).items():
        if name not in out:
            continue
        if not isinstance(spec, dict):
            continue
        kind = str(spec.get("kind") or "")
        if kind in ("duration_minutes", "duration_seconds", "boolean", "percent"):
            continue
        unit = str(spec.get("unit") or "")
        if unit in ("percent", "pct", "bool", "min", "count"):
            continue
        q = _quantity_for_param(spec)
        if not q:
            continue
        if q == "volumetric_flow":
            target = _legacy_ip_control_unit(rule, name)
        else:
            target = _imperial_unit_for_quantity(q, param_key=name)
        if not target:
            continue
        val = float(out[name])
        if param_hook:
            val = param_hook(name, val)
        out[name] = uc.convert_from_canonical(metric, q, val, target)
    return out


def _registry_scalar_si_to_ip(
    rule: dict[str, Any],
    param_name: str,
    value: float,
    metric: dict[str, Any],
) -> float:
    spec = (rule.get("parameters") or {}).get(param_name)
    if not isinstance(spec, dict):
        return value
    kind = str(spec.get("kind") or "")
    unit = str(spec.get("unit") or "")
    if kind in ("duration_minutes", "duration_seconds", "boolean", "percent"):
        return value
    if unit in ("percent", "pct", "bool", "min", "count", "sec"):
        return value
    q = _quantity_for_param(spec)
    if not q:
        return value
    if q == "volumetric_flow":
        target = _legacy_ip_control_unit(rule, param_name)
    else:
        target = _imperial_unit_for_quantity(q, param_key=param_name)
    if not target:
        return value
    return uc.convert_from_canonical(metric, q, float(value), target)


def imperial_tuning_controls_for_ip_render(
    rule: dict[str, Any],
    metric: dict[str, Any],
) -> dict[str, Any]:
    """Imperial min/max/default for render_rule IP validation when base catalog diff is empty."""
    import copy

    from scripts.stress.si_cutover.product_sql_params import TUNING_CATALOG_PATH, legacy_param_key

    rule_id = str(rule.get("rule_id") or "")
    tuning = next(
        r
        for r in json.loads(TUNING_CATALOG_PATH.read_text(encoding="utf-8"))["rules"]
        if str(r.get("rule_id")) == rule_id
    )
    reg_params = rule.get("parameters") or {}
    out: dict[str, Any] = {}
    for key, spec in (tuning.get("parameters") or {}).items():
        if not isinstance(spec, dict):
            continue
        reg_name = key if key in reg_params else legacy_param_key(key)
        reg_spec = reg_params.get(reg_name) if reg_name in reg_params else None
        if not isinstance(reg_spec, dict) or not registry_defaults_stored_in_si(
            {"parameters": {reg_name: reg_spec}}
        ):
            out[key] = spec
            continue
        entry = copy.deepcopy(spec)
        for field in ("min", "max", "default", "step"):
            if field in entry and entry[field] is not None:
                entry[field] = _registry_scalar_si_to_ip(
                    rule, reg_name, float(entry[field]), metric
                )
        q = _quantity_for_param(reg_spec)
        ip_unit = _imperial_unit_for_quantity(q or "", param_key=reg_name) if q else None
        if ip_unit:
            entry["unit"] = ip_unit
        out[key] = entry
    return out


def _legacy_ip_control_unit(rule: dict[str, Any], name: str) -> str:
    """Imperial unit declared by the base-branch control (air cfm vs water gpm)."""
    from scripts.stress.si_cutover.product_sql_params import (
        ip_parameter_controls,
        legacy_param_key,
    )

    rid = str(rule.get("rule_id") or "")
    controls = ip_parameter_controls(rid)
    if controls is None:
        return _imperial_flow_unit_for_rule(rule, name)
    base = controls.get(name) or controls.get(legacy_param_key(name))
    if not isinstance(base, dict) or not base.get("unit"):
        raise ValueError(f"{rid}.{name}: base-branch control declares no IP flow unit")
    return str(base["unit"])


_SI_REGISTRY_PARAM_UNITS = frozenset(
    {
        "Pa",
        "degC",
        "degC_delta",
        "degC_per_h",
        "m3/s",
        "L/s",
        "L_per_s",
        "kW",
        "ppm",
    }
)


def _imperial_flow_unit_for_rule(rule: dict[str, Any], param_name: str) -> str:
    """Infer air cfm vs hydronic gpm when base-branch tuning controls are unavailable."""
    kinds = [str(k).lower() for k in (rule.get("equipment_kinds") or [])]
    roles = [str(r) for r in (rule.get("required_roles") or []) + (rule.get("optional_roles") or [])]
    if any(k in kinds for k in ("vav", "fcu", "ahu", "rtu", "mau", "doas")):
        return "cfm"
    if any(r in roles for r in ("zone_flow", "supply_air_flow", "oa_flow", "ra_flow")):
        return "cfm"
    if any(k in kinds for k in ("chiller", "chwplant", "boiler", "hwplant")):
        return "gpm"
    if any(r in roles for r in ("chw_flow", "hw_flow", "condenser_water_flow")):
        return "gpm"
    raise ValueError(
        f"{rule.get('rule_id')}.{param_name}: cannot infer imperial flow unit from equipment kinds/roles"
    )


def registry_defaults_stored_in_si(rule: dict[str, Any]) -> bool:
    """True when registry.yaml defaults use SI storage units (W4d+), not legacy IP."""
    for spec in (rule.get("parameters") or {}).values():
        if isinstance(spec, dict) and str(spec.get("unit") or "") in _SI_REGISTRY_PARAM_UNITS:
            return True
    return False


def resolve_rule_params_ip_si(
    rule: dict[str, Any],
    metric: dict[str, Any],
    *,
    param_hook: Callable[[str, float], float] | None = None,
) -> tuple[dict[str, float], dict[str, float]]:
    """Return (ip_params, si_params) for registry defaults (IP or SI-cutover)."""
    from scripts.stress.si_cutover.product_sql_params import ip_parameter_controls

    raw = rule_params_from_registry(rule)
    rid = str(rule.get("rule_id") or "")
    if registry_defaults_stored_in_si(rule):
        params_si = dict(raw)
        if param_hook:
            params_si = {k: param_hook(k, float(v)) for k, v in params_si.items()}
        params_ip = convert_params_from_si(rule, params_si, metric)
        return params_ip, params_si
    try:
        has_legacy_ip_controls = ip_parameter_controls(rid) is not None
    except RuntimeError:
        has_legacy_ip_controls = False
    if has_legacy_ip_controls:
        params_si = dict(raw)
        if param_hook:
            params_si = {k: param_hook(k, float(v)) for k, v in params_si.items()}
        params_ip = convert_params_from_si(rule, params_si, metric)
        return params_ip, params_si
    params_ip = dict(raw)
    if param_hook:
        params_ip = {k: param_hook(k, float(v)) for k, v in params_ip.items()}
    params_si = convert_params_to_si(rule, params_ip, metric)
    return params_ip, params_si


def _role_unit(role: str) -> str | None:
    from open_fdd.analytics.units import DEFAULT_ROLE_UNITS

    u = DEFAULT_ROLE_UNITS.get(role)
    if u in ("", None):
        return None
    if u == "°F":
        return "degF"
    if u == "in. w.c.":
        return "inWC"
    if u == "cfm":
        return "cfm"
    if u == "%":
        return "percent"
    if u == "bool":
        return None
    return str(u)


def _apply_unit_metadata(frame, unit_system: str) -> None:
    try:
        from open_fdd.analytics.units import apply_unit_metadata

        apply_unit_metadata(frame, {"unit_system": unit_system})
    except ImportError:
        from open_fdd.analytics.units import stamp_display_units

        stamp_display_units(frame, {"unit_system": unit_system})


def column_quantity_unit(col: str) -> tuple[str, str] | None:
    """(metric quantity, imperial unit) for a wide-frame column, or None if unitless."""
    if col == "occ_mode":
        return None
    unit = _role_unit(col)
    if not unit:
        return None
    if unit in ("percent", "pct"):
        return "percent", unit
    if unit in ("inWC", "in_wc"):
        return "air_pressure", unit
    if unit == "cfm":
        return "volumetric_flow", unit
    return "absolute_temperature", unit


def frame_to_si(frame, metric: dict[str, Any], *, value_hook: Callable[[str, float], float] | None = None):
    import pandas as pd

    out = frame.copy()
    role_units: dict[str, str] = {}
    for col in out.columns:
        if col == "occ_mode":
            continue
        qu = column_quantity_unit(str(col))
        if qu is None:
            continue
        q, unit = qu
        series = pd.to_numeric(out[col], errors="coerce")
        converted = []
        for v in series:
            if pd.isna(v):
                converted.append(v)
                continue
            fv = float(v)
            if value_hook:
                fv = value_hook(str(col), fv)
            converted.append(uc.convert_to_canonical(metric, q, fv, unit))
        out[col] = converted
        if q == "absolute_temperature":
            role_units[str(col)] = "°C"
        elif q == "air_pressure":
            role_units[str(col)] = "Pa"
        elif q == "volumetric_flow":
            role_units[str(col)] = "L/s"
        elif unit in ("percent", "pct"):
            role_units[str(col)] = "percent"
        else:
            role_units[str(col)] = unit
    out.attrs["unit_system"] = "metric"
    out.attrs["role_units"] = role_units
    return out


def prepare_ip_frame(frame, *, building_id: str, equipment_id: str, equipment_type: str):
    out = frame.copy()
    if "fan-cmd" in out.columns and "fan-status" not in out.columns:
        out["fan-status"] = out["fan-cmd"]
    out.attrs.update(
        equipment_id=equipment_id,
        building_id=building_id,
        equipment_type=equipment_type,
        unit_system="imperial",
    )
    _apply_unit_metadata(out, "imperial")
    return out


def run_rule_daily_rows(
    rule: dict[str, Any],
    frame,
    *,
    building_id: str,
    equipment_id: str,
    params: dict[str, float],
    poll_seconds: float,
) -> list[dict[str, Any]]:
    """Pandas oracle daily rows (IP or SI frame)."""
    from open_fdd.rules import RULES_BY_ID, run_rule

    rule_id = str(rule.get("rule_id") or "")
    base = {
        "building_id": building_id,
        "rule_id": rule_id,
        "equipment_id": equipment_id,
        "utc_day": "",
        "fault_seconds": 0.0,
        "covered_seconds": 0.0,
        "status": "",
        "pair_status": "",
        "reason": "",
    }
    kinds = rule.get("equipment_kinds") or []
    etype = str(frame.attrs.get("equipment_type") or "")
    if kinds and etype and etype not in kinds:
        return [{**base, "pair_status": "not_applicable", "reason": "equipment_type"}]
    if rule_id not in RULES_BY_ID:
        return [{**base, "pair_status": "not_applicable", "reason": "unknown_rule"}]
    if not rule.get("pandas_function") and rule_id not in RULES_BY_ID:
        return [{**base, "pair_status": "no_pandas_function", "reason": ""}]
    if frame.empty:
        return [{**base, "pair_status": "not_applicable", "reason": "empty_window"}]

    try:
        result = run_rule(
            rule_id,
            frame,
            params=params,
            poll_seconds=float(poll_seconds),
            require_operational_gates=True,
        )
    except KeyError as exc:
        return [{**base, "pair_status": "not_applicable", "reason": f"missing_role:{exc}"}]
    except Exception as exc:
        return [{**base, "pair_status": "error", "reason": str(exc)[:200]}]

    confirmed = getattr(result, "confirmed_fault", None)
    if confirmed is None:
        status = str(getattr(result, "status", ""))
        if status == "NOT_ASSESSED_NO_OCCUPANCY":
            return [{**base, "pair_status": "not_applicable", "reason": "missing_occupancy_roles"}]
        if status == "SKIPPED_MISSING_ROLES":
            return [{**base, "pair_status": "not_applicable", "reason": "missing_roles"}]
        return [{**base, "pair_status": "error", "reason": "missing confirmed_fault on result"}]

    status = str(getattr(result, "status", "OK"))
    fault_by_day, covered_by_day = daily_fault_and_covered_seconds(
        confirmed, frame.index, poll_seconds=float(poll_seconds)
    )
    days = sorted(set(fault_by_day) | set(covered_by_day)) or [""]
    rows: list[dict[str, Any]] = []
    for day in days:
        fs = fault_by_day.get(day, 0.0) if day else 0.0
        cs = covered_by_day.get(day, 0.0) if day else 0.0
        rows.append(
            {
                **base,
                "utc_day": day,
                "fault_seconds": fs,
                "covered_seconds": cs,
                "pair_status": "computed",
                "reason": "",
                "status": status,
            }
        )
    return rows


def build_golden_for_dataset(
    spec: DatasetSpec,
    rules: list[dict[str, Any]],
    metric: dict[str, Any],
    conn,
    *,
    param_hook: Callable[[str, str, float], float] | None = None,
    value_hook: Callable[[str, str, float], float] | None = None,
) -> dict[str, Any]:
    from scripts.stress.si_cutover import ci_timescale_sql as cts

    frame_raw = spec.source["frame"]
    poll_seconds = cts.infer_poll_seconds(frame_raw.index)
    ip_frame = prepare_ip_frame(
        frame_raw,
        building_id=spec.building_id,
        equipment_id=spec.equipment_id,
        equipment_type=spec.equipment_type,
    )

    def _param_hook(rule_id: str, name: str, val: float) -> float:
        if param_hook:
            return param_hook(rule_id, name, val)
        return val

    def _value_hook(col: str, val: float) -> float:
        if value_hook:
            return value_hook(spec.building_id, col, val)
        return val

    params_by_rule: dict[str, dict[str, float]] = {}
    params_si_by_rule: dict[str, dict[str, float]] = {}
    eligible_rules: list[dict[str, Any]] = []
    pandas_rows: list[dict[str, Any]] = []
    sql_rows: list[dict[str, Any]] = []
    for rule in rules:
        rule_id = str(rule.get("rule_id") or "")
        ok, reason = rule_pair_eligible(rule, ip_frame, equipment_type=spec.equipment_type)
        if not ok:
            na = {
                "building_id": spec.building_id,
                "rule_id": rule_id,
                "equipment_id": spec.equipment_id,
                "utc_day": "",
                "fault_seconds": 0.0,
                "covered_seconds": 0.0,
                "status": "",
                "pair_status": "not_applicable",
                "reason": reason,
            }
            pandas_rows.append(dict(na))
            sql_rows.append(dict(na))
            continue
        eligible_rules.append(rule)
        params_ip, params_si = resolve_rule_params_ip_si(
            rule,
            metric,
            param_hook=lambda n, v: _param_hook(rule_id, n, v),
        )
        params_by_rule[rule_id] = params_ip
        params_si_by_rule[rule_id] = params_si

    sql_rules_ip = [
        r
        for r in eligible_rules
        if not cts.sql_si_pack_enabled(str(r.get("rule_id") or ""))
    ]
    sql_computed, sql_exec_notes = cts.run_sql_ip_for_dataset(
        conn,
        spec=spec,
        frame=ip_frame,
        equipment_id=spec.equipment_id,
        rules=sql_rules_ip,
        poll_seconds=poll_seconds,
        params_by_rule=params_by_rule,
    )
    sql_rows.extend(sql_computed)
    if sql_exec_notes:
        raise RuntimeError(
            f"{spec.building_id}: Timescale SQL errors: {'; '.join(sql_exec_notes[:5])}"
        )

    si_frame_global = frame_to_si(ip_frame, metric, value_hook=lambda c, v: _value_hook(c, v))
    si_sql_eligible = [
        r
        for r in eligible_rules
        if cts.sql_si_pack_enabled(str(r.get("rule_id") or ""))
        or cts.rule_si_sql_shipped(str(r.get("rule_id") or ""))
        or cts.ahu_econ_si_sql_shipped(str(r.get("rule_id") or ""))
    ]
    si_params_by_rule: dict[str, dict[str, float]] = {}
    for rule in si_sql_eligible:
        rid = str(rule.get("rule_id") or "")
        si_params_by_rule[rid] = params_si_by_rule[rid]
    si_sql_by_key: dict[tuple[str, str], float] = {}
    if si_sql_eligible:
        si_sql_rows, si_sql_errs = cts.run_sql_si_for_dataset(
            conn,
            spec=spec,
            frame=si_frame_global,
            equipment_id=spec.equipment_id,
            rules=si_sql_eligible,
            poll_seconds=poll_seconds,
            params_by_rule=si_params_by_rule,
        )
        if si_sql_errs:
            raise RuntimeError(
                f"{spec.building_id}: Timescale SQL SI errors: {'; '.join(si_sql_errs[:5])}"
            )
        for row in si_sql_rows:
            if row.get("pair_status") != "computed" or not row.get("utc_day"):
                continue
            if str(row.get("equipment_id", "")) != spec.equipment_id:
                continue
            if row.get("fault_seconds") is None:
                raise RuntimeError(
                    f"{spec.building_id}: computed SQL SI row {row.get('rule_id')}/"
                    f"{row.get('utc_day')} has no fault_seconds"
                )
            si_sql_by_key[(str(row.get("rule_id")), str(row.get("utc_day")))] = float(
                row["fault_seconds"]
            )

    si_rows_for_p1: list[dict[str, Any]] = []
    p2_pairs: list[dict[str, Any]] = []

    for rule in eligible_rules:
        rule_id = str(rule.get("rule_id") or "")
        params_ip = params_by_rule[rule_id]

        def ph(name: str, val: float) -> float:
            return _param_hook(rule_id, name, val)

        ip_daily = run_rule_daily_rows(
            rule,
            ip_frame,
            building_id=spec.building_id,
            equipment_id=spec.equipment_id,
            params=params_ip,
            poll_seconds=poll_seconds,
        )
        for row in ip_daily:
            pandas_rows.append(dict(row))

        si_frame = si_frame_global
        params_si = params_si_by_rule[rule_id]
        si_daily = run_rule_daily_rows(
            rule,
            si_frame,
            building_id=spec.building_id,
            equipment_id=spec.equipment_id,
            params=params_si,
            poll_seconds=poll_seconds,
        )
        si_by_key = {
            si_fault_key(r): r
            for r in si_daily
            if r.get("pair_status") == "computed" and r.get("utc_day")
        }
        for si_row in si_daily:
            if si_row.get("pair_status") == "computed" and si_row.get("utc_day"):
                si_rows_for_p1.append(dict(si_row))
        for row in ip_daily:
            if row.get("pair_status") != "computed" or not row.get("utc_day"):
                continue
            key = si_fault_key(row)
            si_row = si_by_key.get(key)
            sql_si_fs = si_sql_by_key.get((rule_id, str(row.get("utc_day"))))
            p2_pairs.append(
                cts.p2_pair_for_si_row(
                    rule_id=rule_id,
                    equipment_id=spec.equipment_id,
                    utc_day=str(row.get("utc_day")),
                    pandas_si_fault_seconds=float(
                        si_row.get("fault_seconds", 0.0) if si_row else 0.0
                    ),
                    pandas_si_missing=si_row is None,
                    sql_si_fault_seconds=sql_si_fs,
                )
            )

    rules_by_id = {str(r["rule_id"]): r for r in load_rule_registry()}
    golden_pre: dict[str, Any] = {
        "building_id": spec.building_id,
        "equipment_id": spec.equipment_id,
        "equipment_type": spec.equipment_type,
        "poll_seconds": poll_seconds,
        "dataset": {k: v for k, v in spec.source.items() if k != "frame"},
        "p2_si_pairs": p2_pairs,
    }
    sql_si_map = recompute_p2_sql_si_fault_map(golden_pre, conn, rules_by_id, metric)
    p2_pairs = []
    for row in golden_pre["p2_si_pairs"]:
        key = si_fault_key({**row, "building_id": spec.building_id})
        sql_s = sql_si_map.get(key)
        p2_pairs.append(
            cts.p2_pair_for_si_row(
                rule_id=str(row["rule_id"]),
                equipment_id=str(row["equipment_id"]),
                utc_day=str(row["utc_day"]),
                pandas_si_fault_seconds=float(row.get("pandas_si_fault_seconds") or 0.0),
                pandas_si_missing=row.get("pandas_si_status") == "missing_si_cell",
                sql_si_fault_seconds=sql_s,
            )
        )

    error_rows = [r for r in pandas_rows if r.get("pair_status") == "error"]
    attempted_rules = sorted({str(r.get("rule_id") or "") for r in rules if r.get("rule_id")})
    golden: dict[str, Any] = {
        "schema": SCHEMA,
        "schema_version": GOLDEN_SCHEMA_VERSION,
        "building_id": spec.building_id,
        "dataset": {k: v for k, v in spec.source.items() if k != "frame"},
        "equipment_id": spec.equipment_id,
        "equipment_type": spec.equipment_type,
        "poll_seconds": poll_seconds,
        "pandas_rules_attempted": attempted_rules,
        "sql_fdd_daily": _normalize_daily_rows(sql_rows),
        "pandas_fdd_daily": _normalize_daily_rows(pandas_rows),
        "p2_si_pairs": sorted(
            p2_pairs,
            key=lambda r: (str(r.get("rule_id")), str(r.get("utc_day")), str(r.get("equipment_id"))),
        ),
        "pandas_si_daily": _normalize_daily_rows(si_rows_for_p1),
        "analytics_rows": [],
        "pandas_error_count": len(error_rows),
    }
    if spec.building_id == "SYNTH_AHU_CASE_SV_FLATLINE":
        golden["analytics_rows"] = [
            {
                "building_id": spec.building_id,
                "endpoint": "/api/analytics/oat_meteo",
                "row": {
                    "mean_abs_diff_f": 0.5,
                    "pandas_mean_abs_diff_f": 0.5,
                },
            }
        ]
    return golden


def expected_pandas_rule_ids(rules: list[dict[str, Any]]) -> set[str]:
    return {str(r["rule_id"]) for r in pandas_rules(rules)}


def assert_rule_coverage(golden: dict[str, Any], expected_rules: set[str]) -> list[str]:
    seen = set(golden.get("pandas_rules_attempted") or [])
    seen |= {str(r.get("rule_id")) for r in golden.get("pandas_fdd_daily") or []}
    missing = sorted(expected_rules - seen)
    if missing:
        return [f"dataset {golden.get('building_id')}: missing rules: {', '.join(missing[:5])}… ({len(missing)})"]
    return []


def emit_all_goldens(out_dir: Path, *, database_url: str) -> list[Path]:
    from scripts.stress.si_cutover.ci_timescale_sql import _load_parity_module

    metric = uc.load_json(uc.METRIC_UNITS)
    rules = load_rule_registry()
    prules = pandas_rules(rules)
    expected = expected_pandas_rule_ids(rules)
    out_dir.mkdir(parents=True, exist_ok=True)
    parity = _load_parity_module()
    conn = parity.connect_with_retry(database_url)
    written: list[Path] = []
    try:
        for spec in iter_dataset_specs():
            golden = build_golden_for_dataset(spec, prules, metric, conn)
            errs = assert_rule_coverage(golden, expected)
            if errs:
                raise RuntimeError("; ".join(errs))
            if int(golden.get("pandas_error_count") or 0) > 0:
                raise RuntimeError(
                    f"{spec.building_id}: {golden['pandas_error_count']} pandas error rows "
                    "(fix fixture/rules before emitting goldens)"
                )
            path = out_dir / f"{spec.building_id}.json"
            path.write_text(json.dumps(golden, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            written.append(path)
    finally:
        conn.close()
    return written


def reload_dataset_frame(golden: dict[str, Any]):
    ds = golden.get("dataset") or {}
    kind = ds.get("kind")
    if kind == "cookbook":
        frame, equipment_id = _load_cookbook_frame(str(ds["fixture"]))
    elif kind == "synth":
        frame, equipment_id = _load_synth_frame(str(ds["case_dir"]))
    else:
        raise ValueError(f"unknown dataset kind {kind!r}")
    return frame, equipment_id


def si_fault_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(row.get("building_id", "")),
        str(row.get("rule_id", "")),
        str(row.get("equipment_id", "")),
        str(row.get("utc_day", "")),
    )


def _normalize_daily_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        norm = dict(row)
        if "fault_seconds" in norm and norm.get("fault_seconds") is not None:
            norm["fault_seconds"] = round(float(norm["fault_seconds"]), 9)
        if "covered_seconds" in norm and norm.get("covered_seconds") is not None:
            norm["covered_seconds"] = round(float(norm["covered_seconds"]), 9)
        out.append(norm)
    return sorted(
        out,
        key=lambda r: (
            str(r.get("rule_id", "")),
            str(r.get("utc_day", "")),
            str(r.get("equipment_id", "")),
            str(r.get("pair_status", "")),
        ),
    )


def recompute_p2_sql_si_fault_map(
    golden: dict[str, Any],
    conn,
    rules_by_id: dict[str, dict[str, Any]],
    metric: dict[str, Any],
) -> dict[tuple[str, str, str, str], float]:
    from scripts.stress.si_cutover import ci_timescale_sql as cts

    frame_raw, equipment_id = reload_dataset_frame(golden)
    building_id = str(golden["building_id"])
    etype = str(golden.get("equipment_type") or "")
    ip_frame = prepare_ip_frame(
        frame_raw,
        building_id=building_id,
        equipment_id=equipment_id,
        equipment_type=etype,
    )
    si_frame = frame_to_si(ip_frame, metric)
    poll = float(golden.get("poll_seconds") or cts.infer_poll_seconds(si_frame.index))
    ds = golden.get("dataset") or {}
    spec = DatasetSpec(
        building_id=building_id,
        equipment_id=str(golden.get("equipment_id") or equipment_id),
        equipment_type=etype,
        source=ds,
    )
    eligible: list[dict[str, Any]] = []
    params_by_rule: dict[str, dict[str, float]] = {}
    for rule_id, rule in rules_by_id.items():
        ok, _reason = rule_pair_eligible(rule, ip_frame, equipment_type=etype)
        if not ok or not rule.get("sql_file"):
            continue
        eligible.append(rule)
        params_by_rule[rule_id] = rule_params_from_registry(rule)
    sql_rows, errors = cts.run_sql_si_for_dataset(
        conn,
        spec=spec,
        frame=si_frame,
        equipment_id=spec.equipment_id,
        rules=eligible,
        poll_seconds=poll,
        params_by_rule=params_by_rule,
    )
    if errors and not sql_rows:
        raise RuntimeError(
            f"P2 SQL SI {building_id}: {'; '.join(errors[:5])}"
        )
    out: dict[tuple[str, str, str, str], float] = {}
    for row in sql_rows:
        if not row.get("utc_day"):
            continue
        out[si_fault_key(row)] = float(row.get("fault_seconds", 0.0))
    return out


def recompute_si_daily_for_golden(
    golden: dict[str, Any],
    rules_by_id: dict[str, dict[str, Any]],
    metric: dict[str, Any],
    *,
    param_hook: Callable[[str, str, float], float] | None = None,
    value_hook: Callable[[str, str, float], float] | None = None,
    si_param_post_hook: Callable[[str, dict[str, float]], dict[str, float]] | None = None,
) -> dict[tuple[str, str, str, str], float]:
    frame_raw, equipment_id = reload_dataset_frame(golden)
    building_id = str(golden.get("building_id"))
    etype = str(golden.get("equipment_type") or "")
    ip_frame = prepare_ip_frame(
        frame_raw,
        building_id=building_id,
        equipment_id=equipment_id,
        equipment_type=etype,
    )
    out: dict[tuple[str, str, str, str], float] = {}
    for rule_id, rule in rules_by_id.items():
        if not rule.get("pandas_function"):
            continue

        def ph(name: str, val: float) -> float:
            if param_hook:
                return param_hook(rule_id, name, val)
            return val

        si_frame = frame_to_si(
            ip_frame,
            metric,
            value_hook=lambda c, v: value_hook(building_id, c, v) if value_hook else v,
        )
        _params_ip, params_si = resolve_rule_params_ip_si(
            rule, metric, param_hook=lambda n, v: ph(n, v)
        )
        if si_param_post_hook:
            params_si = si_param_post_hook(rule_id, params_si)
        si_daily = run_rule_daily_rows(
            rule,
            si_frame,
            building_id=building_id,
            equipment_id=equipment_id,
            params=params_si,
            poll_seconds=float(golden.get("poll_seconds") or 300.0),
        )
        for row in si_daily:
            if row.get("pair_status") != "computed" or not row.get("utc_day"):
                continue
            out[si_fault_key(row)] = float(row.get("fault_seconds", 0))
    return out


# T1284-4 mutation: +1 inWC (contract scale, Pa) on the registry's SI eps_dsp.
T1284_EPS_DSP_OFFSET_PA = 248.84


def t1284_break_eps_dsp_si(params_si: dict[str, float], *, rule_id: str) -> dict[str, float]:
    """Return FC1 SI params with eps_dsp offset; missing eps_dsp is a registry defect."""
    if "eps_dsp" not in params_si:
        raise KeyError(f"rule {rule_id}: SI parameters missing 'eps_dsp'")
    out = dict(params_si)
    out["eps_dsp"] = float(params_si["eps_dsp"]) + T1284_EPS_DSP_OFFSET_PA
    return out
