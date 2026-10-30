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
    metric: dict[str, Any], quantity_id: str, canonical: float, target_unit: str
) -> float:
    """Inverse of convert_to_canonical for parity IP paths after W4 SI registry defaults."""
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
    if scale == 0.0:
        raise ValueError(f"zero scale for alias {target_unit!r}")
    return (float(canonical) - offset) / scale


# Kinds without a metric quantity: the unit is a fixed token per kind.
NON_QUANTITY_KIND_UNITS: dict[str, frozenset[str]] = {
    "duration_seconds": frozenset({"sec"}),
    "duration_minutes": frozenset({"min"}),
    "boolean": frozenset({"bool"}),
    "count": frozenset({"count"}),
    "dimensionless": frozenset({"x", "unit", "ppm", "h"}),
}

# Kinds whose values convert through a metric_units.json quantity.
QUANTITY_KINDS = frozenset(
    {
        "absolute_temperature",
        "temperature_difference",
        "temperature_rate",
        "air_pressure",
        "hydronic_pressure",
        "volumetric_flow",
        "interval_energy",
        "percent",
        "fraction",
    }
)


def declared_kind(where: str, param: dict[str, Any]) -> str:
    """Return the parameter's declared kind; a missing or unknown kind is an error."""
    kind = param.get("kind")
    if not isinstance(kind, str) or not kind:
        raise ValueError(f"{where}: parameter has no declared kind")
    if kind not in QUANTITY_KINDS and kind not in NON_QUANTITY_KIND_UNITS:
        raise ValueError(f"{where}: unknown declared kind {kind!r}")
    return kind


def kind_source_unit(kind: str, unit: str) -> str:
    """Conversion-table alias for a declared unit (plain degrees are deltas for differences)."""
    u = unit.strip().strip("'\"")
    if kind == "temperature_difference":
        if u in ("degF", "°F"):
            return "degF_delta"
        if u in ("degC", "°C"):
            return "degC_delta"
    return u


def assert_unit_matches_kind(metric: dict[str, Any], where: str, kind: str, unit: str) -> None:
    """Declared unit must belong to the declared kind."""
    u = unit.strip().strip("'\"")
    if kind in NON_QUANTITY_KIND_UNITS:
        if u not in NON_QUANTITY_KIND_UNITS[kind]:
            raise ValueError(f"{where}: unit {unit!r} is not valid for kind {kind}")
        return
    row = build_conversion_index(metric).get(normalize_alias(kind_source_unit(kind, u)))
    if row is None:
        raise ValueError(f"{where}: unit {unit!r} has no conversion for kind {kind}")
    if row["quantity"] != kind:
        raise ValueError(
            f"{where}: unit {unit!r} belongs to {row['quantity']}, declared kind is {kind}"
        )


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


_VALUE_FIELDS = ("default", "min", "max", "step")
_SI_CUTOVER_FIELDS = frozenset({"kind", "effect", "unit", *_VALUE_FIELDS})


def _float_close(a: float, b: float, *, rel: float = 1e-6, abs_tol: float = 1e-6) -> bool:
    return abs(a - b) <= max(abs_tol, rel * max(abs(a), abs(b), 1.0))


def _rename_map() -> dict[str, str]:
    renames = load_json(RENAME_MAP).get("renames")
    if not isinstance(renames, dict):
        raise ValueError("parameter_si_rename_map.json renames must be a mapping")
    return {str(k): str(v) for k, v in renames.items()}


def _params_by_rule(doc: Any, label: str) -> dict[str, dict[str, dict[str, Any]]]:
    if not isinstance(doc, dict) or not isinstance(doc.get("rules"), list):
        raise AssertionError(f"{label}: rules must be a list")
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for rule in doc["rules"]:
        rid = str(rule.get("rule_id") or "")
        if not rid:
            raise AssertionError(f"{label}: rule missing rule_id")
        params = rule.get("parameters") or {}
        out[rid] = {str(k): v for k, v in params.items() if isinstance(v, dict)}
    return out


def _master_param(
    master_params: dict[str, dict[str, Any]], branch_key: str, renames: dict[str, str]
) -> dict[str, Any] | None:
    if branch_key in master_params:
        return master_params[branch_key]
    for old, new in renames.items():
        if new == branch_key and old in master_params:
            return master_params[old]
    return None


def validate_param_si_change(
    metric: dict[str, Any], where: str, master: dict[str, Any], branch: dict[str, Any]
) -> None:
    """A parameter may change only by converting its declared quantity to another unit.

    The branch declared kind is authoritative for the conversion; it may differ from
    master only when the unit changes as well (a kind correction during SI cutover).
    """
    branch_kind = declared_kind(f"{where} (branch)", branch)
    master_kind = declared_kind(f"{where} (master)", master)
    master_unit = str(master.get("unit") or "")
    branch_unit = str(branch.get("unit") or "")
    assert_unit_matches_kind(metric, f"{where} (branch)", branch_kind, branch_unit)
    if master_unit == branch_unit:
        if master_kind != branch_kind:
            raise AssertionError(
                f"{where}: kind changed {master_kind} -> {branch_kind} without a unit change"
            )
        for field in _VALUE_FIELDS:
            if master.get(field) != branch.get(field):
                raise AssertionError(f"{where}.{field}: value changed without a unit change")
        return
    if branch_kind not in QUANTITY_KINDS:
        raise AssertionError(
            f"{where}: unit changed {master_unit!r} -> {branch_unit!r} "
            f"but kind {branch_kind} has no quantity to convert"
        )
    assert_unit_matches_kind(metric, f"{where} (master unit)", branch_kind, master_unit)
    src = kind_source_unit(branch_kind, master_unit)
    dst = kind_source_unit(branch_kind, branch_unit)
    for field in _VALUE_FIELDS:
        if field not in master and field not in branch:
            continue
        if field not in master or field not in branch:
            raise AssertionError(f"{where}.{field}: present on only one side of the cutover")
        mv = float(master[field])
        bv = float(branch[field])
        if field == "step":
            # A step is an increment: convert the span, not the absolute point.
            expected = convert_to_canonical(
                metric, branch_kind, mv, src
            ) - convert_to_canonical(metric, branch_kind, 0.0, src)
        else:
            expected = convert_to_canonical(metric, branch_kind, mv, src)
        got = convert_to_canonical(metric, branch_kind, bv, dst)
        if not _float_close(expected, got):
            raise AssertionError(
                f"{where}.{field}: {bv!r} {branch_unit} != {mv!r} {master_unit} "
                f"converted as {branch_kind} ({expected!r})"
            )


def _validate_params_si_diff(
    metric: dict[str, Any], label: str, master_doc: Any, branch_doc: Any
) -> None:
    renames = _rename_map()
    master_map = _params_by_rule(master_doc, label)
    for rule_id, branch_params in _params_by_rule(branch_doc, label).items():
        master_params = master_map.get(rule_id)
        if master_params is None:
            continue
        for key, branch_p in branch_params.items():
            master_p = _master_param(master_params, key, renames)
            if master_p is None:
                raise AssertionError(f"{label} {rule_id}.{key}: parameter not present on master")
            validate_param_si_change(metric, f"{label} {rule_id}.{key}", master_p, branch_p)


def doc_for_metadata_diff(doc: Any, renames: dict[str, str]) -> Any:
    """Snapshot without per-parameter cutover fields; SI renames applied to keys.

    The removed fields are validated separately by validate_param_si_change.
    """
    import copy

    out = strip_registry_metadata(copy.deepcopy(doc))
    for rule in out.get("rules", []):
        params = rule.get("parameters")
        if not isinstance(params, dict):
            continue
        renamed: dict[str, Any] = {}
        for k, v in params.items():
            if isinstance(v, dict):
                v = {f: x for f, x in v.items() if f not in _SI_CUTOVER_FIELDS and f != "key"}
                if k in renames and v.get("sql_placeholder") == k.upper():
                    v["sql_placeholder"] = renames[k].upper()
            renamed[renames.get(k, k)] = v
        rule["parameters"] = renamed
    return out


def validate_equipment_kinds_diff(master_doc: Any, branch_doc: Any) -> None:
    """equipment_kinds may only widen; removing a kind narrows rule applicability."""
    master_rules = _rules_by_id(master_doc)
    for rule_id, branch_rule in _rules_by_id(branch_doc).items():
        master_rule = master_rules.get(rule_id)
        if master_rule is None:
            continue
        master_kinds = set(master_rule.get("equipment_kinds") or [])
        branch_kinds = set(branch_rule.get("equipment_kinds") or [])
        if not branch_kinds.issuperset(master_kinds):
            raise AssertionError(
                f"registry.yaml {rule_id}: equipment_kinds removal not allowed "
                f"(removed {sorted(master_kinds - branch_kinds)!r})"
            )


def _without_equipment_kinds(doc: Any) -> Any:
    for rule in doc.get("rules", []):
        if isinstance(rule, dict):
            rule.pop("equipment_kinds", None)
    return doc


def ensure_origin_master_ref() -> str:
    """Resolve a ref for master/base file content (shallow CI checkouts may lack origin/master)."""
    base = os.environ.get("GITHUB_BASE_REF", "master").strip() or "master"
    candidates = [f"origin/{base}", "origin/master", base, "master"]
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


def _git_merge_base(master_ref: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "merge-base", "HEAD", master_ref],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def _is_shallow_repository() -> bool:
    proc = subprocess.run(
        ["git", "rev-parse", "--is-shallow-repository"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"git rev-parse --is-shallow-repository failed: {proc.stderr.strip()}"
        )
    return proc.stdout.strip() == "true"


def ensure_metadata_diff_base_ref() -> str:
    """Merge-base of HEAD and the default branch (not the tip of master).

    Branches that are only behind master must not fail metadata diff when master
    moved without this branch touching registry files.
    """
    master_ref = ensure_origin_master_ref()
    proc = _git_merge_base(master_ref)
    if proc.returncode != 0 and _is_shallow_repository():
        # actions/checkout clones with depth 1, so HEAD and the default branch
        # share no history until the clone is deepened.
        unshallow = subprocess.run(
            ["git", "fetch", "--no-tags", "--unshallow", "origin"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        if unshallow.returncode != 0:
            raise RuntimeError(
                f"git fetch --unshallow origin failed: {unshallow.stderr.strip()}"
            )
        proc = _git_merge_base(master_ref)
    if proc.returncode != 0:
        raise RuntimeError(
            f"git merge-base HEAD {master_ref} failed: {proc.stderr.strip()}"
        )
    base = proc.stdout.strip()
    if not base:
        raise RuntimeError(f"empty merge-base for HEAD and {master_ref}")
    return base


def git_show_master(relpath: str) -> str:
    ref = ensure_metadata_diff_base_ref()
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
            rule.pop("output_units", None)
    return stripped


def _output_unit_entry(where: str, entry: Any) -> tuple[str, str]:
    """Return (unit, kind) of one ``output_units`` declaration; both are required."""
    if not isinstance(entry, dict) or set(entry) != {"unit", "kind"}:
        raise AssertionError(f"{where}: output_units entry must be a mapping of exactly unit and kind")
    unit, kind = entry["unit"], entry["kind"]
    if not isinstance(unit, str) or not unit or not isinstance(kind, str) or not kind:
        raise AssertionError(f"{where}: output_units unit and kind must be non-empty strings")
    return unit, kind


def validate_output_units_declarations(metric: dict[str, Any], master_doc: Any, branch_doc: Any) -> None:
    """``output_units`` is declaration-only metadata.

    Each entry names an emitted output column, a quantity kind from
    metric_units.json, and a unit that belongs to that kind. A declaration may
    be added; an existing one may not be removed or have its unit changed,
    because that would change reported values.
    """
    quantities = {str(q["id"]) for q in metric.get("quantities", [])}
    master_rules = _rules_by_id(master_doc)
    for rule_id, rule in _rules_by_id(branch_doc).items():
        declared = rule.get("output_units")
        master_declared = master_rules.get(rule_id, {}).get("output_units") or {}
        if declared is None:
            if master_declared:
                raise AssertionError(f"registry.yaml {rule_id}: output_units removed")
            continue
        if not isinstance(declared, dict):
            raise AssertionError(f"registry.yaml {rule_id}: output_units must be a mapping")
        columns = {str(c) for c in rule.get("output_columns") or []}
        for column, entry in declared.items():
            where = f"registry.yaml {rule_id}.output_units.{column}"
            if column not in columns or column == "equipment_id":
                raise AssertionError(f"{where}: not a declared output column")
            unit, kind = _output_unit_entry(where, entry)
            if kind not in QUANTITY_KINDS or kind not in quantities:
                raise AssertionError(f"{where}: kind {kind!r} is not a metric_units.json quantity")
            try:
                assert_unit_matches_kind(metric, where, kind, unit)
            except ValueError as exc:
                raise AssertionError(str(exc)) from exc
        for column, master_entry in master_declared.items():
            where = f"registry.yaml {rule_id}.output_units.{column}"
            if column not in declared:
                raise AssertionError(f"{where}: declaration removed")
            master_unit, _ = _output_unit_entry(where, master_entry)
            if _output_unit_entry(where, declared[column])[0] != master_unit:
                raise AssertionError(f"{where}: declared unit changed from {master_unit!r}")


def validate_registry_role_declarations_diff(master_doc: Any, branch_doc: Any) -> None:
    """Allow only optional_roles additions justified by rule SQL history reads."""
    from check_rule_columns import sql_history_roles_for_rule

    master_rules = _rules_by_id(master_doc)
    branch_rules = _rules_by_id(branch_doc)
    if set(master_rules) != set(branch_rules):
        raise AssertionError(
            "registry.yaml rule_id set differs from merge-base with the default branch "
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

    if registry_without_role_lists(master_doc) != registry_without_role_lists(branch_doc):
        raise AssertionError(
            "registry.yaml differs from merge-base with the default branch beyond "
            "kind/effect metadata, SQL-justified optional_roles additions and "
            "output_units declarations"
        )


def assert_metadata_only_registry_diff() -> None:
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("PyYAML required") from exc
    metric = load_json(METRIC_UNITS)
    renames = _rename_map()
    master_raw = yaml.safe_load(git_show_master("sql/fdd/registry.yaml"))
    branch_raw = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
    _validate_params_si_diff(metric, "registry", master_raw, branch_raw)
    validate_equipment_kinds_diff(master_raw, branch_raw)
    validate_output_units_declarations(metric, master_raw, branch_raw)
    validate_registry_role_declarations_diff(
        _without_equipment_kinds(doc_for_metadata_diff(master_raw, renames)),
        _without_equipment_kinds(doc_for_metadata_diff(branch_raw, renames)),
    )


def assert_metadata_only_tuning_diff() -> None:
    metric = load_json(METRIC_UNITS)
    renames = _rename_map()
    master_raw = json.loads(git_show_master("sql/fdd/tuning_catalog.json"))
    branch_raw = load_json(TUNING)
    _validate_params_si_diff(metric, "tuning", master_raw, branch_raw)
    if doc_for_metadata_diff(master_raw, renames) != doc_for_metadata_diff(branch_raw, renames):
        raise AssertionError(
            "tuning_catalog.json differs from merge-base with the default branch "
            "beyond kind/effect metadata and declared-kind SI cutover"
        )


def apply_tuning_catalog(data: dict[str, Any]) -> dict[str, Any]:
    """Validate declared kinds against units and derive tuner effects."""
    metric = load_json(METRIC_UNITS)
    for rule in data.get("rules", []):
        rid = rule.get("rule_id", "")
        params = rule.get("parameters") or {}
        for key, param in params.items():
            where = f"tuning {rid}.{key}"
            kind = declared_kind(where, param)
            assert_unit_matches_kind(metric, where, kind, str(param.get("unit") or ""))
            param["effect"] = derive_tuner_effect(rid, param.get("effect_in_sql"))
    return data
