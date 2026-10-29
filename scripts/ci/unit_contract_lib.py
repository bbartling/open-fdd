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
SI_CONTRACT_VALUE_KEYS = ("default", "min", "max", "step")
SI_CONTRACT_DIFF_KEYS = frozenset({"unit", "label", *SI_CONTRACT_VALUE_KEYS})
_FLOAT_TOL = 1e-5
# SV-RANGE SQL limits are authored against °F literals; metric historian uses execution scale.
_SV_RANGE_SI_SQL_EXECUTION: dict[str, float] = {
    "range_scale_temperature": 5.0 / 9.0,
}


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


def convert_from_canonical(
    metric: dict[str, Any], quantity_id: str, canonical: float, target_unit: str
) -> float:
    by_token = build_conversion_index(metric)
    tok = normalize_alias(target_unit)
    row = by_token.get(tok)
    if row is None:
        raise ValueError(f"unknown alias {target_unit!r}")
    if row["quantity"] != quantity_id:
        raise ValueError(
            f"{target_unit!r} maps to {row['quantity']}, expected {quantity_id}"
        )
    scale = float(row["scale"])
    if scale == 0.0:
        raise ValueError(f"zero scale for {target_unit!r}")
    return (float(canonical) - float(row["offset"])) / scale


def infer_kind(param_key: str, unit: str) -> str:
    u = (unit or "").strip().strip("'\"")
    key = param_key.strip().lower()
    if key in TEMPERATURE_DIFFERENCE_KEYS or "delta" in key and key.endswith("_f"):
        return "temperature_difference"
    if u in {"degF", "°F"}:
        return "absolute_temperature"
    if u == "degC":
        return "temperature_difference" if key == "deadband_c" else "absolute_temperature"
    if u in {"degC_delta", "deltaC"}:
        return "temperature_difference"
    if u == "Pa":
        return "air_pressure"
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


def _quantity_for_param_spec(spec: dict[str, Any]) -> str | None:
    kind = str(spec.get("kind") or "")
    unit = str(spec.get("unit") or "")
    if kind == "absolute_temperature":
        return "absolute_temperature"
    if kind == "temperature_difference":
        return "temperature_difference"
    if kind == "temperature_rate":
        return "temperature_rate"
    if kind == "air_pressure":
        return "air_pressure"
    if kind == "hydronic_pressure":
        return "hydronic_pressure"
    if kind in ("duration_minutes", "duration_seconds"):
        return "duration_seconds" if kind == "duration_seconds" else "duration_minutes"
    if kind in ("percent", "fraction", "boolean", "count", "dimensionless"):
        return None
    if unit in ("degF", "degC", "°F", "°C"):
        return "absolute_temperature"
    if unit in ("degF_delta", "degC_delta", "deltaC"):
        return "temperature_difference"
    if unit in ("Pa", "inWC", "inH2O", "in_wc", "inwc", "psi", "kPa"):
        return "air_pressure"
    if unit in ("degF_per_h", "degC_per_h"):
        return "temperature_rate"
    return None


def _source_unit_for_convert(unit: str, quantity: str) -> str:
    if quantity == "temperature_difference" and unit == "degF":
        return "degF_delta"
    if quantity == "temperature_difference" and unit in ("degC", "°C"):
        return "degC_delta"
    if unit == "pct":
        return "percent"
    if unit.lower() in ("inwc", "in_wc"):
        return "inWC"
    return unit


def _param_to_canonical(
    metric: dict[str, Any],
    spec: dict[str, Any],
    field: str,
    *,
    quantity_override: str | None = None,
) -> float | None:
    if field not in spec:
        return None
    raw = spec[field]
    if raw is None:
        return None
    quantity = quantity_override or _quantity_for_param_spec(spec)
    if quantity == "absolute_temperature" and field == "step":
        quantity = "temperature_difference"
    if quantity is None:
        return float(raw)
    unit = str(spec.get("unit") or "")
    src = _source_unit_for_convert(unit, quantity)
    return convert_to_canonical(metric, quantity, float(raw), src)


def _canonical_values_match(a: float | None, b: float | None) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return abs(float(a) - float(b)) <= _FLOAT_TOL


def _validate_param_spec_kind_aware(
    metric: dict[str, Any],
    rule_id: str,
    param_key: str,
    master_spec: dict[str, Any],
    branch_spec: dict[str, Any],
) -> None:
    skip = SI_CONTRACT_DIFF_KEYS | STRIP_PARAM_KEYS
    keys = set(master_spec) | set(branch_spec)
    for key in sorted(keys):
        if key in skip:
            continue
        if master_spec.get(key) != branch_spec.get(key):
            raise AssertionError(
                f"{rule_id}.{param_key}: field {key!r} changed "
                f"(master={master_spec.get(key)!r} branch={branch_spec.get(key)!r})"
            )

    qty_m = _quantity_for_param_spec(master_spec)
    qty_b = _quantity_for_param_spec(branch_spec)

    for field in SI_CONTRACT_VALUE_KEYS:
        if field not in master_spec and field not in branch_spec:
            continue
        if master_spec.get(field) == branch_spec.get(field) and master_spec.get(
            "unit"
        ) == branch_spec.get("unit"):
            continue
        mc = _param_to_canonical(metric, master_spec, field)
        bc = _param_to_canonical(metric, branch_spec, field)
        if _canonical_values_match(mc, bc):
            continue
        if qty_b and qty_m != qty_b:
            mc_branch_qty = _param_to_canonical(
                metric, master_spec, field, quantity_override=qty_b
            )
            if _canonical_values_match(mc_branch_qty, bc):
                continue
        if (
            rule_id == "SV-RANGE"
            and field in ("default", "step")
            and param_key in _SV_RANGE_SI_SQL_EXECUTION
        ):
            scale = _SV_RANGE_SI_SQL_EXECUTION[param_key]
            master_val = float(master_spec.get(field, 0.0))
            branch_val = float(branch_spec.get(field, 0.0))
            if abs(master_val * scale - branch_val) <= _FLOAT_TOL:
                continue
        raise AssertionError(
            f"{rule_id}.{param_key}.{field}: SI contract mismatch "
            f"(master canonical={mc!r} branch canonical={bc!r}; "
            f"master={master_spec.get(field)!r} {master_spec.get('unit')!r} "
            f"branch={branch_spec.get(field)!r} {branch_spec.get('unit')!r})"
        )


def validate_kind_aware_si_rules_diff(
    metric: dict[str, Any],
    master_doc: Any,
    branch_doc: Any,
    *,
    doc_label: str,
) -> None:
    """Allow registry/tuning parameter SI rewrites when values match metric contract conversion."""
    master_rules = _rules_by_id(master_doc)
    branch_rules = _rules_by_id(branch_doc)
    if set(master_rules) != set(branch_rules):
        raise AssertionError(f"{doc_label}: rule_id set differs from origin/master")

    for rule_id, master_rule in master_rules.items():
        branch_rule = branch_rules[rule_id]
        skip = {"required_roles", "optional_roles", "parameters"}
        rule_keys = set(master_rule) | set(branch_rule)
        for key in sorted(rule_keys):
            if key in skip:
                continue
            if master_rule.get(key) != branch_rule.get(key):
                raise AssertionError(
                    f"{doc_label} {rule_id}: non-parameter field {key!r} changed"
                )

        master_params = master_rule.get("parameters") or {}
        branch_params = branch_rule.get("parameters") or {}
        if set(master_params) != set(branch_params):
            raise AssertionError(
                f"{doc_label} {rule_id}: parameter keys differ "
                f"(master={sorted(master_params)!r} branch={sorted(branch_params)!r})"
            )
        for param_key, master_spec in master_params.items():
            if not isinstance(master_spec, dict) or not isinstance(
                branch_params[param_key], dict
            ):
                if master_spec != branch_params[param_key]:
                    raise AssertionError(
                        f"{doc_label} {rule_id}.{param_key}: non-dict parameter changed"
                    )
                continue
            _validate_param_spec_kind_aware(
                metric,
                rule_id,
                param_key,
                master_spec,
                branch_params[param_key],
            )


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


def _rules_by_id(doc: Any) -> dict[str, dict[str, Any]]:
    rules = doc.get("rules") if isinstance(doc, dict) else None
    if not isinstance(rules, list):
        raise AssertionError("registry.yaml rules must be a list")
    out: dict[str, dict[str, Any]] = {}
    for rule in rules:
        if not isinstance(rule, dict):
            raise AssertionError("registry rule entries must be mappings")
        rid = rule.get("rule_id")
        if not rid:
            raise AssertionError("registry rule missing rule_id")
        out[str(rid)] = rule
    return out


def registry_without_role_lists(doc: Any) -> Any:
    import copy

    stripped = copy.deepcopy(doc)
    stripped = strip_registry_metadata(stripped)
    for rule in stripped.get("rules", []):
        if isinstance(rule, dict):
            rule.pop("required_roles", None)
            rule.pop("optional_roles", None)
    return stripped


def validate_registry_role_lists_diff(master_doc: Any, branch_doc: Any) -> None:
    """Allow only optional_roles additions justified by rule SQL history reads."""
    from check_rule_columns import sql_history_roles_for_rule

    master_rules = _rules_by_id(master_doc)
    branch_rules = _rules_by_id(branch_doc)
    if set(master_rules) != set(branch_rules):
        raise AssertionError(
            "registry.yaml rule_id set differs from origin/master "
            "(add/remove rule entries not allowed in metadata-only PRs)"
        )

    for rule_id, branch_rule in branch_rules.items():
        master_rule = master_rules[rule_id]
        master_req = list(master_rule.get("required_roles") or [])
        branch_req = list(branch_rule.get("required_roles") or [])
        if master_req != branch_req:
            raise AssertionError(
                f"registry.yaml {rule_id}: required_roles changed "
                f"(master={master_req!r} branch={branch_req!r})"
            )

        master_opt = {str(r).lower() for r in master_rule.get("optional_roles") or []}
        branch_opt = {str(r).lower() for r in branch_rule.get("optional_roles") or []}
        if not branch_opt.issuperset(master_opt):
            removed = sorted(master_opt - branch_opt)
            raise AssertionError(
                f"registry.yaml {rule_id}: optional_roles removal not allowed "
                f"(removed {removed!r})"
            )
        added = branch_opt - master_opt
        if not added:
            continue
        sql_roles = {r.lower() for r in sql_history_roles_for_rule(branch_rule)}
        for role in sorted(added):
            if role not in sql_roles:
                raise AssertionError(
                    f"registry.yaml {rule_id}: optional_roles addition `{role}` "
                    "is not referenced in the rule SQL FROM history SELECT"
                )


def validate_registry_role_declarations_diff(master_doc: Any, branch_doc: Any) -> None:
    """Role-list guard used by unit tests and non-SI metadata-only PRs."""
    validate_registry_role_lists_diff(master_doc, branch_doc)
    if registry_without_role_lists(master_doc) != registry_without_role_lists(branch_doc):
        raise AssertionError(
            "registry.yaml differs from origin/master beyond kind/effect metadata "
            "and SQL-justified optional_roles additions"
        )


def assert_metadata_only_registry_diff() -> None:
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("PyYAML required") from exc
    master_text = git_show_master("sql/fdd/registry.yaml")
    branch_text = REGISTRY.read_text(encoding="utf-8")
    master_doc = yaml.safe_load(master_text)
    branch_doc = yaml.safe_load(branch_text)
    validate_registry_role_lists_diff(master_doc, branch_doc)
    metric = load_json(METRIC_UNITS)
    if registry_without_role_lists(master_doc) == registry_without_role_lists(branch_doc):
        return
    validate_kind_aware_si_rules_diff(
        metric, master_doc, branch_doc, doc_label="registry.yaml"
    )


def assert_metadata_only_tuning_diff() -> None:
    master_raw = json.loads(git_show_master("sql/fdd/tuning_catalog.json"))
    branch_raw = load_json(TUNING)
    master = strip_registry_metadata(master_raw)
    branch = strip_registry_metadata(branch_raw)
    if master == branch:
        return
    metric = load_json(METRIC_UNITS)
    validate_kind_aware_si_rules_diff(
        metric, master_raw, branch_raw, doc_label="tuning_catalog.json"
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
