#!/usr/bin/env python3
"""Shared unit-contract helpers for W2a (#1284). Used by check_unit_contract and CI."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
METRIC_UNITS = ROOT / "sql/contract/metric_units.json"
RENAME_MAP = ROOT / "sql/contract/parameter_si_rename_map.json"
REGISTRY = ROOT / "sql/fdd/registry.yaml"
TUNING = ROOT / "sql/fdd/tuning_catalog.json"
MANIFEST = ROOT / "sql/contract/manifest.json"
GOLDENS = ROOT / "sql/contract/goldens/unit_vectors.json"

TEMPERATURE_DIFFERENCE_KEYS = frozenset(
    {
        "delta_f",
        "coil_delta_f",
        "pass_delta_f",
        "reset_err_f",
        "preheat_over_f",
        "excess_beyond_approach_f",
        "approach_max_f",
        "deadband_c",
    }
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def infer_kind(param_key: str, unit: str) -> str:
    u = (unit or "").strip().strip("'\"")
    key = param_key.strip().lower()
    if key in TEMPERATURE_DIFFERENCE_KEYS or "delta" in key and key.endswith("_f"):
        return "temperature_difference"
    if u in {"degF", "°F"}:
        return "absolute_temperature"
    if u == "degC":
        return "temperature_difference" if key == "deadband_c" else "absolute_temperature"
    if u == "degF_per_h":
        return "temperature_rate"
    if u in {"in_wc", "inwc"}:
        return "air_pressure"
    if u == "psi":
        return "hydronic_pressure"
    if u in {"cfm", "gpm"}:
        return "volumetric_flow"
    if u == "kWh":
        return "interval_energy"
    if u in {"pct", "%", "'%'"}:
        return "percent"
    if u == "frac":
        return "fraction"
    if u == "sec":
        return "duration_seconds"
    if u == "min":
        return "duration_minutes"
    if u == "h":
        return "dimensionless"
    if u == "bool":
        return "boolean"
    if u == "count":
        return "count"
    if u in {"x", "unit", "ppm"}:
        return "dimensionless"
    raise ValueError(f"cannot infer kind for param {param_key!r} unit {unit!r}")


def derive_tuner_effect(rule_id: str, effect_in_sql: bool | None) -> str:
    if rule_id == "SV-RATE":
        return "unsupported"
    if effect_in_sql:
        return "branch_sensitive"
    return "no_op"


def collect_alias_map(metric: dict[str, Any]) -> dict[str, tuple[str, str]]:
    """Map normalized alias token -> (quantity_id, canonical_unit)."""
    out: dict[str, tuple[str, str]] = {}
    for q in metric.get("quantities", []):
        qid = q["id"]
        canon = q["canonical_unit"]
        for alias in q.get("aliases") or []:
            tok = normalize_alias(alias)
            if not tok:
                continue
            if tok in out and out[tok] != (qid, canon):
                raise ValueError(f"duplicate alias {alias!r} across quantities")
            out[tok] = (qid, canon)
    return out


def normalize_alias(alias: str) -> str:
    raw = alias.strip().lower().replace("°", "deg")
    is_rate = "perh" in raw.replace("_", "").replace("/", "") or "/h" in raw
    is_delta = "delta" in raw or "δ" in alias or "Δ" in alias
    cleaned = re.sub(r"[^a-z0-9]", "", raw.replace("δ", "delta"))
    if is_delta and not cleaned.startswith("delta"):
        cleaned = f"delta{cleaned}"
    if is_rate and "perh" not in cleaned:
        cleaned = f"{cleaned}perh" if cleaned.endswith("h") else f"{cleaned}perh"
    return cleaned


def registry_param_blocks(text: str) -> list[tuple[str, str, int]]:
    """Yield (param_key, unit, line_index_of_unit) for each parameter block."""
    lines = text.splitlines()
    current_rule: str | None = None
    in_params = False
    current_key: str | None = None
    for i, line in enumerate(lines):
        m_rule = re.match(r"^\s+-\s+rule_id:\s+(\S+)", line)
        if m_rule:
            current_rule = m_rule.group(1)
            in_params = False
            current_key = None
            continue
        if re.match(r"^\s+parameters:\s*$", line):
            in_params = True
            current_key = None
            continue
        if not in_params:
            continue
        if re.match(r"^\s+\w", line) and not line.startswith("      "):
            in_params = False
            current_key = None
            continue
        m_key = re.match(r"^      (\w+):\s*$", line)
        if m_key:
            current_key = m_key.group(1)
            continue
        m_unit = re.match(r"^        unit:\s+(\S+)", line)
        if m_unit and current_key:
            yield current_key, m_unit.group(1), i
            continue


def inject_registry_kinds(text: str) -> str:
    lines = text.splitlines()
    inserts: dict[int, str] = {}
    for key, unit, unit_line in registry_param_blocks(text):
        kind_line_idx = unit_line + 1
        if kind_line_idx < len(lines) and re.match(r"^\s+kind:\s+", lines[kind_line_idx]):
            continue
        kind = infer_kind(key, unit)
        inserts[unit_line] = f"        kind: {kind}"
    if not inserts:
        return text
    out: list[str] = []
    for i, line in enumerate(lines):
        out.append(line)
        if i in inserts:
            out.append(inserts[i])
    return "\n".join(out) + ("\n" if text.endswith("\n") else "")


def apply_tuning_catalog(data: dict[str, Any]) -> dict[str, Any]:
    for rule in data.get("rules", []):
        rid = rule.get("rule_id", "")
        params = rule.get("parameters") or {}
        for key, param in params.items():
            unit = param.get("unit", "")
            param["kind"] = infer_kind(key, str(unit))
            effect = derive_tuner_effect(rid, param.get("effect_in_sql"))
            param["effect"] = effect
    return data
