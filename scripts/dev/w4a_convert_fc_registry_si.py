#!/usr/bin/env python3
"""Convert FC1–FC15 + FC13-SAT-HIGH parameter defaults/units in registry + tuning (W4a)."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "ci"))

import yaml  # noqa: E402

from unit_contract_lib import (  # noqa: E402
    TUNING,
    REGISTRY,
    convert_to_canonical,
    infer_kind,
    load_json,
)

FC_RULES = frozenset(tuple(f"FC{i}" for i in range(1, 16)) + ("FC13-SAT-HIGH",))

# GL36 sensor tolerances are °F deltas in the cookbook/SQL math; registry kind stays absolute_temperature.
_CONVERT_AS_TEMP_DELTA = frozenset(
    {
        "eps_cclt",
        "eps_ccet",
        "eps_hcet",
        "eps_hclt",
        "eps_sat",
        "eps_mat",
        "eps_oat",
        "eps_rat",
        "delta_supply_fan",
    }
)

IMPERIAL_UNITS = frozenset({"degF", "inwc", "in_wc", "cfm", "degF_delta", "°F"})


def _quantity(kind: str, unit: str) -> str | None:
    if kind in ("duration_minutes", "duration_seconds", "boolean", "percent", "fraction"):
        return None
    if kind in ("absolute_temperature", "temperature_difference", "air_pressure", "volumetric_flow", "temperature_rate"):
        return kind
    if unit in ("degF", "°F"):
        return "absolute_temperature"
    if unit in ("degF_delta",):
        return "temperature_difference"
    if unit in ("inwc", "in_wc"):
        return "air_pressure"
    if unit == "cfm":
        return "volumetric_flow"
    return None


def _src_unit(q: str, unit: str) -> str:
    if q == "temperature_difference" and unit in ("degF", "°F"):
        return "degF_delta"
    if q == "absolute_temperature" and unit in ("degF", "°F"):
        return "degF"
    return unit


def _target_unit(q: str) -> str:
    if q == "absolute_temperature":
        return "degC"
    if q == "temperature_difference":
        return "degC"
    if q == "air_pressure":
        return "Pa"
    if q == "volumetric_flow":
        return "L_per_s"
    if q == "temperature_rate":
        return "delta_degC_per_h"
    raise ValueError(q)


def convert_param_spec(name: str, spec: dict[str, Any], metric: dict) -> dict[str, tuple[Any, Any]]:
    """Return patch map field -> (old, new) for numeric fields plus unit."""
    patches: dict[str, tuple[Any, Any]] = {}
    unit = str(spec.get("unit") or "")
    if unit not in IMPERIAL_UNITS:
        return patches
    kind = str(spec.get("kind") or infer_kind(name, unit))
    convert_kind = kind
    if unit in ("degF", "degF_delta", "°F") and name in _CONVERT_AS_TEMP_DELTA:
        convert_kind = "temperature_difference"
    q = _quantity(convert_kind, unit)
    if not q:
        return patches
    src = _src_unit(q, unit)
    for field in ("default", "min", "max", "step"):
        if field not in spec:
            continue
        old = float(spec[field])
        new = round(convert_to_canonical(metric, q, old, src), 9)
        patches[field] = (old, new)
        spec[field] = new
    new_unit = _target_unit(q)
    patches["unit"] = (unit, new_unit)
    spec["unit"] = new_unit
    return patches


def build_registry_patches(metric: dict) -> dict[tuple[str, str, str], tuple[Any, Any]]:
    doc = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
    out: dict[tuple[str, str, str], tuple[Any, Any]] = {}
    for rule in doc.get("rules") or []:
        rid = str(rule.get("rule_id") or "")
        if rid not in FC_RULES:
            continue
        for name, spec in (rule.get("parameters") or {}).items():
            if not isinstance(spec, dict):
                continue
            for field, (old, new) in convert_param_spec(str(name), spec, metric).items():
                out[(rid, str(name), field)] = (old, new)
    return out


def apply_registry_patches(text: str, patches: dict[tuple[str, str, str], tuple[Any, Any]]) -> str:
    lines = text.splitlines()
    out: list[str] = []
    current_rule: str | None = None
    param_key: str | None = None
    for line in lines:
        m_rule = re.match(r"^\s+-\s+rule_id:\s+(\S+)", line)
        if m_rule:
            current_rule = m_rule.group(1)
            param_key = None
            out.append(line)
            continue
        m_key = re.match(r"^      (\w+):\s*$", line)
        if m_key:
            param_key = m_key.group(1)
            out.append(line)
            continue
        replaced = False
        if current_rule and param_key:
            m_def = re.match(r"^        (default|min|max|step|unit):\s+(\S+)\s*$", line)
            if m_def:
                field = m_def.group(1)
                key = (current_rule, param_key, field)
                if key in patches:
                    _old, new = patches[key]
                    if field == "unit":
                        out.append(f"        unit: {new}")
                    else:
                        out.append(f"        {field}: {new}")
                    replaced = True
        if not replaced:
            out.append(line)
    return "\n".join(out) + "\n"


def convert_tuning_json(metric: dict) -> None:
    data = load_json(TUNING)
    for rule in data.get("rules") or []:
        rid = str(rule.get("rule_id") or "")
        if rid not in FC_RULES:
            continue
        for key, param in (rule.get("parameters") or {}).items():
            if isinstance(param, dict):
                convert_param_spec(str(key), param, metric)
    TUNING.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    metric = load_json(ROOT / "sql" / "contract" / "metric_units.json")
    original = REGISTRY.read_text(encoding="utf-8")
    patches = build_registry_patches(metric)
    REGISTRY.write_text(apply_registry_patches(original, patches), encoding="utf-8")
    convert_tuning_json(metric)
    print(f"Converted FC registry ({len(patches)} field patches) + tuning_catalog")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
