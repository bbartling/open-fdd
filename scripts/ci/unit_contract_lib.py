#!/usr/bin/env python3
"""Shared unit-contract helpers for W2a (#1284). Used by check_unit_contract and CI."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
METRIC_UNITS = ROOT / "sql/contract/metric_units.json"
RENAME_MAP = ROOT / "sql/contract/parameter_si_rename_map.json"
REGISTRY = ROOT / "sql/fdd/registry.yaml"
TUNING = ROOT / "sql/fdd/tuning_catalog.json"
MANIFEST = ROOT / "sql/contract/manifest.json"
GOLDENS = ROOT / "sql/contract/goldens/unit_vectors.json"
ALIAS_GOLDENS = ROOT / "sql/contract/goldens/alias_normalize_tokens.json"

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

STRIP_PARAM_KEYS = frozenset({"kind", "effect"})

# Wave 4d (#1284): registry defaults/units move to SI for these rules only.
W4D_SI_PLANT_RULES = frozenset(
    {
        "CHW-NOLOAD-1",
        "CHW-1",
        "CHW-2",
        "CHW-3",
        "CHW-4",
        "CW-OPT-1",
        "CW-APR-1",
        "CW-FAN-1",
        "HP-1",
        "TRIM-1",
        "TRIM-3",
        "TRIM-4",
    }
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_alias(alias: str) -> str:
    """Must match crates/fdd_core/src/units_contract.rs normalize_alias."""
    trimmed = alias.strip()
    if trimmed == "%":
        return "percent"
    raw = trimmed.lower().replace("°", "deg").replace("δ", "delta").replace("%", "percent")
    is_rate = (
        ("perh" in raw.replace("_", "").replace("/", "") or "/h" in raw)
        and ("delta" in raw or "deg" in raw or "°" in alias or "Δ" in alias)
    )
    is_delta = "delta" in raw or "δ" in alias or "Δ" in alias
    cleaned = re.sub(r"[^a-z0-9]", "", raw.replace("δ", "delta"))
    if is_delta and not cleaned.startswith("delta") and "delta" not in cleaned:
        cleaned = f"delta{cleaned}"
    if is_rate and "perh" not in cleaned:
        if cleaned.endswith("h"):
            cleaned = cleaned[:-1]
        cleaned = f"{cleaned}perh"
    return cleaned


def build_conversion_index(metric: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = metric.get("source_unit_conversions") or []
    by_token: dict[str, dict[str, Any]] = {}
    for row in rows:
        tok = normalize_alias(str(row["alias"]))
        if tok in by_token:
            prev = by_token[tok]
            if prev["quantity"] != row["quantity"] or prev["scale"] != row["scale"]:
                raise ValueError(f"conflicting conversion for token {tok}")
            continue
        by_token[tok] = row
    return by_token


def convert_to_canonical(
    metric: dict[str, Any], quantity_id: str, value: float, source_unit: str
) -> float:
    if quantity_id == "occupancy_mode":
        raise ValueError("occupancy_mode unsupported")
    by_token = build_conversion_index(metric)
    tok = normalize_alias(source_unit)
    row = by_token.get(tok)
    if row is None:
        raise ValueError(f"unknown alias {source_unit!r}")
    if row["quantity"] != quantity_id:
        raise ValueError(
            f"{source_unit!r} maps to {row['quantity']}, expected {quantity_id}"
        )
    return float(value) * float(row["scale"]) + float(row["offset"])


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
    out: dict[str, tuple[str, str]] = {}
    for q in metric.get("quantities", []):
        qid = q["id"]
        canon = q["canonical_unit"]
        for alias in q.get("aliases") or []:
            tok = normalize_alias(alias)
            if not tok:
                continue
            if tok in out and out[tok][0] != qid:
                raise ValueError(f"duplicate alias {alias!r} across quantities")
            out[tok] = (qid, canon)
    return out


def registry_param_blocks(text: str) -> list[tuple[str, str, str, int]]:
    """Yield (rule_id, param_key, unit, line_index_of_unit) for each parameter block."""
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
        if m_unit and current_key and current_rule:
            yield current_rule, current_key, m_unit.group(1), i
            continue


def registry_param_kind(text: str, rule_id: str, key: str, unit: str) -> str | None:
    lines = text.splitlines()
    in_rule = False
    for i, line in enumerate(lines):
        m_rule = re.match(r"^\s+-\s+rule_id:\s+(\S+)", line)
        if m_rule:
            in_rule = m_rule.group(1) == rule_id
            continue
        if not in_rule:
            continue
        if not re.match(rf"^      {re.escape(key)}:\s*$", line):
            continue
        saw_unit = False
        for j in range(i + 1, len(lines)):
            row = lines[j]
            if re.match(r"^      \w", row) and not row.startswith("        "):
                break
            if re.match(r"^\s+-\s+rule_id:", row):
                break
            if not row.startswith("        "):
                break
            if re.match(rf"^        unit: {re.escape(unit)}\s*$", row):
                saw_unit = True
                continue
            if saw_unit:
                m = re.match(r"^        kind: (\S+)\s*$", row)
                if m:
                    return m.group(1)
        return None
    return None


def strip_registry_metadata(doc: Any) -> Any:
    if isinstance(doc, dict):
        out = {}
        for k, v in doc.items():
            if k in STRIP_PARAM_KEYS:
                continue
            out[k] = strip_registry_metadata(v)
        return out
    if isinstance(doc, list):
        return [strip_registry_metadata(x) for x in doc]
    return doc


def registry_doc_for_metadata_diff(doc: Any) -> Any:
    """Registry snapshot for W2a metadata guard; W4d plant rules may change SI defaults."""
    stripped = strip_registry_metadata(doc)
    if not isinstance(stripped, dict) or "rules" not in stripped:
        return stripped
    kept = [
        r
        for r in stripped["rules"]
        if isinstance(r, dict) and r.get("rule_id") not in W4D_SI_PLANT_RULES
    ]
    kept.sort(key=lambda r: str(r.get("rule_id", "")))
    return {"rules": kept}


def ensure_origin_master_ref() -> str:
    """Resolve a ref for master/base file content (shallow CI checkouts may lack origin/master)."""
    override = os.environ.get("UNIT_CONTRACT_BASE_REF", "").strip()
    candidates = [override] if override else []
    base = os.environ.get("GITHUB_BASE_REF", "master").strip() or "master"
    candidates.extend([f"origin/{base}", "origin/master", base, "master"])
    for ref in candidates:
        if not ref:
            continue
        proc = subprocess.run(
            ["git", "rev-parse", "--verify", ref],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        if proc.returncode == 0:
            return ref
    fetch = subprocess.run(
        ["git", "fetch", "origin", f"{base}:refs/remotes/origin/{base}", "--depth=1"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if fetch.returncode != 0:
        raise RuntimeError(
            "could not resolve or fetch base ref for metadata diff "
            f"(tried {candidates!r}): {fetch.stderr}"
        )
    return f"origin/{base}"


def git_show_master(relpath: str) -> str:
    ref = ensure_origin_master_ref()
    proc = subprocess.run(
        ["git", "show", f"{ref}:{relpath}"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git show {ref}:{relpath} failed: {proc.stderr}")
    return proc.stdout


def assert_metadata_only_registry_diff() -> None:
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("PyYAML required") from exc
    master_text = git_show_master("sql/fdd/registry.yaml")
    branch_text = REGISTRY.read_text(encoding="utf-8")
    master_doc = registry_doc_for_metadata_diff(yaml.safe_load(master_text))
    branch_doc = registry_doc_for_metadata_diff(yaml.safe_load(branch_text))
    if master_doc != branch_doc:
        raise AssertionError(
            "registry.yaml differs from origin/master beyond kind/effect metadata "
            "(excluding W4d SI plant rules)"
        )


def assert_metadata_only_tuning_diff() -> None:
    master = strip_registry_metadata(json.loads(git_show_master("sql/fdd/tuning_catalog.json")))
    branch = strip_registry_metadata(load_json(TUNING))
    if master != branch:
        raise AssertionError(
            "tuning_catalog.json differs from origin/master beyond kind/effect metadata"
        )


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
