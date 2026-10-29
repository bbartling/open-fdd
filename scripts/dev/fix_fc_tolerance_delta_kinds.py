#!/usr/bin/env python3
"""Set GL36 FC sensor tolerance params to kind temperature_difference (registry + tuning)."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "ci"))

import yaml  # noqa: E402

from unit_contract_lib import REGISTRY, TUNING  # noqa: E402

FC_RULES = frozenset(tuple(f"FC{i}" for i in range(1, 16)) + ("FC13-SAT-HIGH",))

# Duct-static / VFD fraction — not GL36 temperature sensor ε.
_NOT_TEMP_EPS = frozenset({"eps_dsp", "eps_vfd_spd"})


def is_gl36_temp_tolerance(name: str, unit: str) -> bool:
    if name == "delta_supply_fan":
        return True
    if not name.startswith("eps_") or name in _NOT_TEMP_EPS:
        return False
    return unit in ("degF", "degC", "°F", "degF_delta", "degC_delta")


def patch_registry_text(text: str) -> str:
    lines = text.splitlines()
    out: list[str] = []
    current_rule: str | None = None
    param_key: str | None = None
    param_unit: str | None = None
    for line in lines:
        m_rule = re.match(r"^\s+-\s+rule_id:\s+(\S+)", line)
        if m_rule:
            current_rule = m_rule.group(1)
            param_key = None
            param_unit = None
            out.append(line)
            continue
        m_key = re.match(r"^      (\w+):\s*$", line)
        if m_key:
            param_key = m_key.group(1)
            param_unit = None
            out.append(line)
            continue
        m_unit = re.match(r"^        unit:\s+(\S+)\s*$", line)
        if m_unit and param_key:
            param_unit = m_unit.group(1)
            out.append(line)
            continue
        if (
            current_rule in FC_RULES
            and param_key
            and param_unit
            and is_gl36_temp_tolerance(param_key, param_unit)
            and re.match(r"^        kind: absolute_temperature\s*$", line)
        ):
            out.append("        kind: temperature_difference")
            continue
        out.append(line)
    return "\n".join(out) + "\n"


def patch_tuning() -> int:
    data = json.loads(TUNING.read_text(encoding="utf-8"))
    n = 0
    for rule in data.get("rules") or []:
        rid = str(rule.get("rule_id") or "")
        if rid not in FC_RULES:
            continue
        for key, param in (rule.get("parameters") or {}).items():
            if not isinstance(param, dict):
                continue
            unit = str(param.get("unit") or "")
            if not is_gl36_temp_tolerance(str(key), unit):
                continue
            if param.get("kind") == "absolute_temperature":
                param["kind"] = "temperature_difference"
                n += 1
    TUNING.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return n


def main() -> int:
    text = REGISTRY.read_text(encoding="utf-8")
    patched = patch_registry_text(text)
    REGISTRY.write_text(patched, encoding="utf-8")
    n_tune = patch_tuning()
    print(f"Patched registry.yaml + tuning_catalog ({n_tune} tuning kind fixes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
