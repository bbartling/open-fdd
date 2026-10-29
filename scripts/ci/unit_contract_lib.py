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
    metric: dict[str, Any], quantity_id: str, canonical_value: float, target_unit: str
) -> float:
    """Map a canonical (metric storage) value into ``target_unit`` for IP oracle frames."""
    if quantity_id == "occupancy_mode":
        raise ValueError("occupancy_mode unsupported")
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
    offset = float(row["offset"])
    if abs(scale) < 1e-15:
        raise ValueError(f"non-invertible scale for {target_unit!r}")
    return (float(canonical_value) - offset) / scale


def infer_kind(param_key: str, unit: str) -> str:
    u = (unit or "").strip().strip("'\"")
    key = param_key.strip().lower()
    if key in TEMPERATURE_DIFFERENCE_KEYS or "delta" in key and key.endswith("_f"):
        return "temperature_difference"
    if key == "delta_supply_fan" or (
        key.startswith("eps_")
        and key not in {"eps_dsp", "eps_vfd_spd"}
        and u.lower() in {"degf", "°f", "degc"}
    ):
        return "temperature_difference"
    if u in {"degF", "°F"}:
        return "absolute_temperature"
    if u == "degC":
        return "temperature_difference" if key == "deadband_c" else "absolute_temperature"
    if u == "delta_degC":
        return "temperature_difference"
    if u == "degF_per_h":
        return "temperature_rate"
    if u in {"in_wc", "inwc"}:
        return "air_pressure"
    if u == "Pa":
        return "air_pressure"
    if u == "psi":
        return "hydronic_pressure"
    if u in {"cfm", "gpm"}:
        return "volumetric_flow"
    if u == "L_per_s":
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


def _float_close(a: float, b: float, *, rel: float = 1e-6, abs_tol: float = 1e-6) -> bool:
    return abs(float(a) - float(b)) <= max(abs_tol, rel * max(abs(float(a)), abs(float(b)), 1.0))


_VALUE_FIELDS = ("default", "min", "max", "step")

_CONVERTIBLE_KINDS = frozenset(
    {
        "absolute_temperature",
        "temperature_difference",
        "air_pressure",
        "volumetric_flow",
        "temperature_rate",
    }
)

_NON_CONVERTIBLE_KINDS = frozenset(
    {
        "duration_minutes",
        "duration_seconds",
        "boolean",
        "percent",
        "fraction",
        "count",
        "dimensionless",
        "hydronic_pressure",
        "interval_energy",
    }
)


def _conversion_quantity(kind: str, unit: str, param_key: str) -> str | None:
    if kind in _NON_CONVERTIBLE_KINDS:
        return None
    if kind in _CONVERTIBLE_KINDS:
        return kind
    if unit in ("degF", "°F", "degC", "°C", "inwc", "in_wc", "Pa", "cfm", "L_per_s"):
        q = infer_kind(param_key, unit)
        if q in _CONVERTIBLE_KINDS:
            return q
    return None


def _resolve_convert_kind(rule_id: str, branch_key: str, master_unit: str, master_kind: str) -> str:
    """Quantity kind used when validating SI numeric cutover from master IP storage."""
    try:
        inferred = infer_kind(branch_key, master_unit)
    except ValueError as exc:
        if master_kind in _CONVERTIBLE_KINDS | _NON_CONVERTIBLE_KINDS:
            return master_kind
        raise AssertionError(
            f"{rule_id}.{branch_key}: cannot infer kind for unit {master_unit!r} "
            f"(master kind={master_kind!r})"
        ) from exc
    if inferred in _CONVERTIBLE_KINDS:
        return inferred
    if master_kind in _CONVERTIBLE_KINDS | _NON_CONVERTIBLE_KINDS:
        return master_kind
    raise AssertionError(
        f"{rule_id}.{branch_key}: master kind {master_kind!r} is not SI-convertible "
        f"(infer_kind -> {inferred!r})"
    )


def _src_unit_for_convert(unit: str, quantity: str, param_key: str) -> str:
    u = str(unit or "")
    if quantity == "temperature_difference":
        if u in ("degF", "°F"):
            return "degF_delta"
        if u in ("degC", "°C"):
            return "degC_delta"
    if u == "°F":
        return "degF"
    if u == "°C":
        return "degC"
    return u


def _registry_params_by_rule(doc: Any) -> dict[str, dict[str, dict[str, Any]]]:
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for rule in doc.get("rules") or []:
        rid = str(rule.get("rule_id") or "")
        if not rid:
            continue
        params = rule.get("parameters") or {}
        out[rid] = {str(k): dict(v) for k, v in params.items() if isinstance(v, dict)}
    return out


def _master_param_for_branch_key(
    master_params: dict[str, dict[str, Any]], branch_key: str, renames: dict[str, str]
) -> tuple[str | None, dict[str, Any] | None]:
    if branch_key in master_params:
        return branch_key, master_params[branch_key]
    for old, new in renames.items():
        if new == branch_key and old in master_params:
            return old, master_params[old]
    return None, None


def _validate_registry_param_si_change(
    metric: dict[str, Any],
    *,
    rule_id: str,
    branch_key: str,
    master: dict[str, Any],
    branch: dict[str, Any],
) -> None:
    master_unit = str(master.get("unit") or "")
    branch_unit = str(branch.get("unit") or "")
    master_kind = str(master.get("kind") or infer_kind(branch_key, master_unit))
    branch_kind = str(branch.get("kind") or infer_kind(branch_key, branch_unit))

    value_changed = False
    for field in _VALUE_FIELDS:
        if field not in master and field not in branch:
            continue
        mv = master.get(field)
        bv = branch.get(field)
        if mv is None and bv is None:
            continue
        if mv is None or bv is None:
            value_changed = True
            break
        if not _float_close(float(mv), float(bv)):
            value_changed = True
            break

    unit_changed = master_unit != branch_unit
    kind_changed = master_kind != branch_kind

    if not value_changed and not unit_changed and not kind_changed:
        return

    if value_changed and not unit_changed and not kind_changed:
        raise AssertionError(
            f"{rule_id}.{branch_key}: numeric value changed without unit/kind change "
            f"(master unit={master_unit!r})"
        )

    if kind_changed and not unit_changed:
        raise AssertionError(
            f"{rule_id}.{branch_key}: kind changed without unit change "
            f"({master_kind} -> {branch_kind})"
        )

    convert_kind = _resolve_convert_kind(rule_id, branch_key, master_unit, master_kind)
    quantity = _conversion_quantity(convert_kind, master_unit, branch_key)
    if value_changed or unit_changed:
        if quantity is None:
            if value_changed:
                raise AssertionError(
                    f"{rule_id}.{branch_key}: value/unit change without convertible quantity "
                    f"(kind={master_kind} unit={master_unit!r})"
                )
            return
        src = _src_unit_for_convert(master_unit, quantity, branch_key)
        for field in _VALUE_FIELDS:
            if field not in master:
                continue
            if field not in branch:
                raise AssertionError(f"{rule_id}.{branch_key}.{field}: missing on branch after SI cutover")
            expected = convert_to_canonical(metric, quantity, float(master[field]), src)
            if not _float_close(expected, float(branch[field])):
                raise AssertionError(
                    f"{rule_id}.{branch_key}.{field}: SI value {branch[field]!r} != "
                    f"converted {expected!r} from master {master[field]!r} {master_unit!r}"
                )


def assert_registry_si_cutover_diff(metric: dict[str, Any]) -> None:
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("PyYAML required") from exc
    renames = load_json(RENAME_MAP).get("renames") or {}
    master_map = _registry_params_by_rule(yaml.safe_load(git_show_master("sql/fdd/registry.yaml")))
    branch_map = _registry_params_by_rule(yaml.safe_load(REGISTRY.read_text(encoding="utf-8")))
    for rule_id, branch_params in branch_map.items():
        master_params = master_map.get(rule_id)
        if master_params is None:
            raise AssertionError(
                f"registry {rule_id}: rule present on branch but not on origin/master"
            )
        for branch_key, branch_p in branch_params.items():
            _mk, master_p = _master_param_for_branch_key(master_params, branch_key, renames)
            if master_p is None:
                raise AssertionError(
                    f"registry {rule_id}.{branch_key}: new parameter not present on master"
                )
            _validate_registry_param_si_change(
                metric,
                rule_id=rule_id,
                branch_key=branch_key,
                master=master_p,
                branch=branch_p,
            )


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


def validate_registry_role_declarations_diff(
    master_doc: Any, branch_doc: Any, *, require_metadata_only_body: bool = True
) -> None:
    """Role-list guard for registry edits. SI cutover PRs set require_metadata_only_body=False."""
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

    if require_metadata_only_body and registry_without_role_lists(master_doc) != registry_without_role_lists(
        branch_doc
    ):
        raise AssertionError(
            "registry.yaml differs from origin/master beyond kind/effect metadata "
            "and SQL-justified optional_roles additions"
        )


def _tuning_params_by_rule(doc: dict[str, Any]) -> dict[str, dict[str, dict[str, Any]]]:
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for rule in doc.get("rules") or []:
        rid = str(rule.get("rule_id") or "")
        if not rid:
            continue
        params = rule.get("parameters") or {}
        out[rid] = {str(k): dict(v) for k, v in params.items() if isinstance(v, dict)}
    return out


def assert_tuning_si_cutover_diff(metric: dict[str, Any]) -> None:
    renames = load_json(RENAME_MAP).get("renames") or {}
    master = json.loads(git_show_master("sql/fdd/tuning_catalog.json"))
    branch = load_json(TUNING)
    master_map = _tuning_params_by_rule(master)
    branch_map = _tuning_params_by_rule(branch)
    for rule_id, branch_params in branch_map.items():
        master_params = master_map.get(rule_id)
        if master_params is None:
            raise AssertionError(
                f"tuning {rule_id}: rule present on branch but not on origin/master"
            )
        for branch_key, branch_p in branch_params.items():
            tun_key = str(branch_p.get("key") or branch_key)
            _mk, master_p = _master_param_for_branch_key(master_params, tun_key, renames)
            if master_p is None:
                master_p = master_params.get(branch_key)
            if master_p is None:
                raise AssertionError(
                    f"tuning {rule_id}.{branch_key}: new parameter not present on master"
                )
            _validate_registry_param_si_change(
                metric,
                rule_id=rule_id,
                branch_key=branch_key,
                master=master_p,
                branch=branch_p,
            )


def assert_metadata_only_registry_diff() -> None:
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("PyYAML required") from exc
    metric = load_json(METRIC_UNITS)
    master_text = git_show_master("sql/fdd/registry.yaml")
    branch_text = REGISTRY.read_text(encoding="utf-8")
    master_doc = yaml.safe_load(master_text)
    branch_doc = yaml.safe_load(branch_text)
    validate_registry_role_declarations_diff(master_doc, branch_doc, require_metadata_only_body=False)
    assert_registry_si_cutover_diff(metric)


def assert_metadata_only_tuning_diff() -> None:
    metric = load_json(METRIC_UNITS)
    assert_tuning_si_cutover_diff(metric)


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
