"""Deterministic effective rule catalog (defaults + overrides) and hashes.

The serialized document is the complete effective settings, not user overrides
alone. Key order is stable so Python and a future DataFusion hasher can compare
SHA-256 of the same JSON bytes.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from open_fdd.version import CATALOG_SCHEMA_VERSION

PRIORITY_TO_SEVERITY = {"P0": 1, "P1": 2, "P2": 3, "P3": 4}


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if value != value:  # NaN
            return None
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(value[k]) for k in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    raise TypeError(f"catalog values must be JSON primitives, got {type(value).__name__}")


def dumps_canonical(doc: dict[str, Any]) -> str:
    """Stable JSON: sorted keys, no whitespace, no default=str."""
    return json.dumps(_jsonable(doc), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_hex(doc: dict[str, Any]) -> str:
    return hashlib.sha256(dumps_canonical(doc).encode("utf-8")).hexdigest()


def _gate_row(rule_id: str) -> dict[str, Any]:
    from open_fdd.rules.operational_gate import (
        COMPRESSOR_ROLES,
        FAN_CMD_FALLBACK,
        FAN_PROOF_ROLES,
        PUMP_CMD_FALLBACK,
        PUMP_PROOF_ROLES,
        RULE_GATES,
    )

    spec = RULE_GATES.get(rule_id)
    if spec is None:
        return {
            "kind": "always",
            "startup_delay_seconds": 0.0,
            "minimum_active_coverage_pct": 5.0,
            "command_fallback_allowed": True,
            "proof_roles": [],
            "command_fallback_roles": [],
        }
    proof: list[str] = []
    cmd: list[str] = []
    if spec.kind == "fan_running":
        proof = list(FAN_PROOF_ROLES)
        cmd = list(FAN_CMD_FALLBACK)
    elif spec.kind == "hydronic_flow":
        proof = list(PUMP_PROOF_ROLES)
        cmd = list(PUMP_CMD_FALLBACK)
    elif spec.kind == "compressor":
        proof = list(COMPRESSOR_ROLES)
    elif spec.kind == "equipment_energized":
        proof = list(FAN_PROOF_ROLES) + list(PUMP_PROOF_ROLES) + list(COMPRESSOR_ROLES)
        cmd = list(FAN_CMD_FALLBACK) + list(PUMP_CMD_FALLBACK)
    elif spec.kind == "control_loop":
        proof = list(FAN_PROOF_ROLES) + ["loop-enabled"]
        cmd = list(FAN_CMD_FALLBACK)
    return {
        "kind": spec.kind,
        "startup_delay_seconds": float(spec.startup_delay_seconds),
        "minimum_active_coverage_pct": float(spec.minimum_active_coverage_pct),
        "command_fallback_allowed": bool(spec.command_fallback_allowed),
        "proof_roles": proof,
        "command_fallback_roles": cmd,
    }


def _sql_index() -> dict[str, dict]:
    from pathlib import Path

    try:
        import yaml
    except ImportError:
        return {}
    root = Path(__file__).resolve().parents[1]
    path = root / "sql_rules" / "registry.yaml"
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out: dict[str, dict] = {}
    for row in data.get("rules") or []:
        if isinstance(row, dict) and row.get("rule_id"):
            out[str(row["rule_id"])] = row
    return out


def _rule_entry(rule, sql_row: dict | None, overrides: dict[str, Any] | None) -> dict[str, Any]:
    params = {p.key: p.default for p in rule.params}
    units = {p.key: p.unit for p in rule.params}
    if overrides:
        for key, val in overrides.items():
            if key in params or key in {
                "confirm_seconds",
                "require_operational_gate",
                "minimum_active_coverage_pct",
                "startup_delay_min",
                "min_valid_coverage",
            }:
                params[key] = val
    gate = _gate_row(rule.id)
    sql = sql_row or {}
    priority = str(sql.get("priority") or "P1")
    confirm = float(rule.confirm_seconds)
    if overrides:
        if "confirm_seconds" in overrides:
            confirm = float(overrides["confirm_seconds"])
        elif "confirm_min" in overrides:
            confirm = float(overrides["confirm_min"]) * 60.0
    return {
        "rule_id": rule.id,
        "title": rule.title,
        "family": rule.family,
        "applicability": list(rule.equipment_kinds),
        "required_roles": list(rule.required_roles),
        "optional_roles": list(rule.optional_roles),
        "operational_proof_roles": list(gate["proof_roles"]),
        "command_fallback_roles": list(gate["command_fallback_roles"]),
        "gate": gate,
        "units": units,
        "thresholds": params,
        "confirm_seconds": confirm,
        "startup_delay_seconds": float(gate["startup_delay_seconds"]),
        "severity": PRIORITY_TO_SEVERITY.get(priority, 2),
        "priority": priority,
        "sql_file": sql.get("sql_file"),
        "min_valid_coverage": float(params.get("min_valid_coverage", 0.5)),
    }


def effective_catalog(
    *,
    overrides_by_rule: dict[str, dict[str, Any]] | None = None,
    include_sql_analytics: bool = True,
) -> dict[str, Any]:
    """Complete effective catalog: packaged defaults plus optional overrides."""
    from open_fdd.rules.cookbook_catalog import RULES

    overrides_by_rule = overrides_by_rule or {}
    sql_idx = _sql_index()
    rules = [_rule_entry(r, sql_idx.get(r.id) or sql_idx.get("FC13-SAT-HIGH" if r.id == "FC13" else r.id), overrides_by_rule.get(r.id)) for r in RULES]
    analytics: list[dict[str, Any]] = []
    if include_sql_analytics:
        for rid in sorted(
            {
                "FAN-RUNTIME-HOURS",
                "AVG-ZONE-TEMP",
                "ZONE-COMFORT-PCT",
                "FAULT-ELAPSED-HOURS",
            }
        ):
            row = sql_idx.get(rid) or {}
            analytics.append(
                {
                    "rule_id": rid,
                    "title": row.get("description") or rid,
                    "family": "sql_analytics",
                    "applicability": [],
                    "required_roles": list(row.get("required_roles") or []),
                    "optional_roles": list(row.get("optional_roles") or []),
                    "operational_proof_roles": [],
                    "command_fallback_roles": [],
                    "gate": {"kind": "always"},
                    "units": {},
                    "thresholds": {
                        k: (v.get("default") if isinstance(v, dict) else v)
                        for k, v in (row.get("parameters") or {}).items()
                    },
                    "confirm_seconds": float(row.get("confirm_seconds") or 0),
                    "startup_delay_seconds": 0.0,
                    "severity": PRIORITY_TO_SEVERITY.get(str(row.get("priority") or "P1"), 2),
                    "priority": row.get("priority") or "P1",
                    "sql_file": row.get("sql_file"),
                    "min_valid_coverage": 0.0,
                }
            )
    return {
        "schema_version": CATALOG_SCHEMA_VERSION,
        "rule_count": len(rules),
        "sql_analytics_count": len(analytics),
        "overrides_applied": sorted(overrides_by_rule),
        "rules": rules,
        "sql_analytics": analytics,
    }


def rule_catalog_hash() -> str:
    """Hash of packaged defaults (no user overrides)."""
    return sha256_hex(effective_catalog(overrides_by_rule=None))


def effective_config_hash(overrides_by_rule: dict[str, dict[str, Any]] | None = None) -> str:
    """Hash of defaults plus the supplied overrides."""
    return sha256_hex(effective_catalog(overrides_by_rule=overrides_by_rule))


def sql_shared_fields_document() -> dict[str, Any]:
    """Subset comparable to a Rust hasher over registry.yaml."""
    idx = _sql_index()
    rows = []
    for rid in sorted(idx):
        r = idx[rid]
        params = r.get("parameters") or {}
        defaults = {
            k: (v.get("default") if isinstance(v, dict) else v) for k, v in params.items()
        }
        rows.append(
            {
                "rule_id": rid,
                "sql_file": r.get("sql_file"),
                "required_roles": list(r.get("required_roles") or []),
                "confirm_seconds": r.get("confirm_seconds"),
                "thresholds": defaults,
            }
        )
    return {"schema_version": CATALOG_SCHEMA_VERSION, "rules": rows}


def sql_registry_hash() -> str:
    return sha256_hex(sql_shared_fields_document())
