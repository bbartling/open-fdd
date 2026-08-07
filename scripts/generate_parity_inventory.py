#!/usr/bin/env python3
"""Generate sql_rules/generated/parity_inventory.{yaml,json} from registry + pandas catalog.

Wave 0 contract: explains 59 diagnostic concepts + 4 SQL analytics = 63 SQL entries.
Does not claim mask/duration parity — statuses come from registry.yaml.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    print("FAIL: PyYAML required (pip install pyyaml)", file=sys.stderr)
    raise SystemExit(2)

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "sql_rules" / "registry.yaml"
CATALOG = ROOT / "open_fdd" / "rules" / "cookbook_catalog.py"
OUT_DIR = ROOT / "sql_rules" / "generated"
FIXTURE_ROOT = ROOT / "crates" / "fdd_rules" / "fixtures" / "oracle"

SQL_ANALYTICS = frozenset(
    {
        "FAN-RUNTIME-HOURS",
        "AVG-ZONE-TEMP",
        "ZONE-COMFORT-PCT",
        "FAULT-ELAPSED-HOURS",
    }
)

# Pandas FC13 ↔ SQL FC13-SAT-HIGH
PANDAS_TO_SQL_CANONICAL = {
    "FC13": "FC13-SAT-HIGH",
}

FIXTURE_CASES = (
    "normal",
    "fault",
    "threshold_boundary",
    "missing_required_role",
    "equipment_off",
    "startup_delay",
    "irregular_sampling",
    "data_gap",
    "duplicate_timestamp",
    "out_of_order",
)

PARITY_LEVELS = frozenset(
    {
        "concept_only",
        "sql_screening",
        "predicate_parity",
        "mask_parity",
        "duration_parity",
        "site_soak",
    }
)


def pandas_ids_from_catalog() -> list[str]:
    text = CATALOG.read_text(encoding="utf-8")
    # Only CookbookRule("ID" ...) constructors in the RULES list region.
    ids = re.findall(r'CookbookRule\(\s*\n?\s*"([A-Z][A-Z0-9-]*)"', text)
    # Dedupe preserving order
    seen: set[str] = set()
    out: list[str] = []
    for i in ids:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


def load_registry() -> list[dict]:
    data = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
    rules = data.get("rules") if isinstance(data, dict) else None
    if not isinstance(rules, list):
        raise SystemExit("FAIL: sql_rules/registry.yaml missing rules list")
    return rules


def fixture_entries(rule_id: str, seed_cases: set[str] | None = None) -> list[dict]:
    seed_cases = seed_cases or set()
    entries = []
    for case in FIXTURE_CASES:
        rel = Path("crates/fdd_rules/fixtures/oracle") / rule_id / case
        abs_dir = ROOT / rel
        present = (abs_dir / "history_wide.csv").is_file() or (
            abs_dir / "expected.json"
        ).is_file()
        entries.append(
            {
                "case": case,
                "path": str(rel).replace("\\", "/"),
                "required": True,
                "present": present,
                "oracle_seed": case in seed_cases and present,
            }
        )
    return entries


def build_inventory() -> dict:
    pandas_ids = pandas_ids_from_catalog()
    if len(pandas_ids) != 59:
        raise SystemExit(
            f"FAIL: expected 59 pandas CookbookRule ids, found {len(pandas_ids)}"
        )

    reg = load_registry()
    if len(reg) != 63:
        raise SystemExit(f"FAIL: expected 63 registry rules, found {len(reg)}")

    by_sql = {r["rule_id"]: r for r in reg if isinstance(r, dict) and "rule_id" in r}
    aliases_index: dict[str, str] = {}
    for r in reg:
        rid = r["rule_id"]
        for a in r.get("aliases") or []:
            aliases_index[str(a)] = rid

    # Seed cases that must exist for Wave 0 end-to-end oracle
    seed_map = {
        "ECON-4": {"fault"},
        "FC1": {"normal", "fault"},
        "VAV-1": {"missing_required_role"},
    }

    concepts: list[dict] = []

    # Diagnostics: one concept per pandas id
    for pid in pandas_ids:
        sql_id = PANDAS_TO_SQL_CANONICAL.get(pid, pid)
        if sql_id not in by_sql:
            raise SystemExit(f"FAIL: pandas {pid} has no SQL entry (looked for {sql_id})")
        r = by_sql[sql_id]
        level = r.get("parity_status") or "concept_only"
        if level not in PARITY_LEVELS:
            raise SystemExit(f"FAIL: {sql_id} has invalid parity_status={level!r}")
        aliases = list(r.get("aliases") or [])
        if pid == "SV-RATE" and "SV-SLEW" not in aliases:
            # pandas alias must be explainable even if only on pandas side
            aliases = aliases + ["SV-SLEW"]
        concepts.append(
            {
                "canonical_id": sql_id,
                "pandas_id": pid,
                "aliases": aliases,
                "kind": "diagnostic",
                "pandas_implementation": r.get("pandas_function") or pid.lower().replace("-", "_"),
                "sql_file": r.get("sql_file"),
                "equipment_kinds": None,  # filled from catalog when available
                "required_roles": list(r.get("required_roles") or []),
                "optional_roles": list(r.get("optional_roles") or []),
                "operational_gate": "fan_or_occupied_when_declared",
                "startup_delay_seconds": None,
                "confirm_seconds": r.get("confirm_seconds"),
                "parameters": r.get("parameters") or {},
                "time_semantics": "row_or_interval_per_sql_file",
                "output_schema": list(r.get("output_columns") or []),
                "parity_level": level,
                "proof_fixtures": fixture_entries(sql_id, seed_map.get(sql_id)),
            }
        )

    # SQL analytics (no pandas diagnostic)
    for aid in sorted(SQL_ANALYTICS):
        if aid not in by_sql:
            raise SystemExit(f"FAIL: missing SQL analytics {aid}")
        r = by_sql[aid]
        level = r.get("parity_status") or "concept_only"
        concepts.append(
            {
                "canonical_id": aid,
                "pandas_id": None,
                "aliases": list(r.get("aliases") or []),
                "kind": "sql_analytics",
                "pandas_implementation": None,
                "sql_file": r.get("sql_file"),
                "equipment_kinds": None,
                "required_roles": list(r.get("required_roles") or []),
                "optional_roles": list(r.get("optional_roles") or []),
                "operational_gate": None,
                "startup_delay_seconds": None,
                "confirm_seconds": r.get("confirm_seconds"),
                "parameters": r.get("parameters") or {},
                "time_semantics": "analytics_rollup",
                "output_schema": list(r.get("output_columns") or []),
                "parity_level": level,
                "proof_fixtures": [],
            }
        )

    # Orphan / duplicate checks
    sql_ids = set(by_sql)
    concept_sql = {c["canonical_id"] for c in concepts}
    orphans = sorted(sql_ids - concept_sql)
    if orphans:
        raise SystemExit(f"FAIL: orphan SQL rules not in inventory: {orphans}")

    return {
        "schema_version": "parity-inventory-v1",
        "generated_by": "scripts/generate_parity_inventory.py",
        "counts": {
            "pandas_diagnostics": 59,
            "sql_analytics": 4,
            "sql_registry": 63,
            "concepts": len(concepts),
        },
        "parity_levels": sorted(PARITY_LEVELS),
        "aliases_index": aliases_index,
        "concepts": concepts,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="fail if generated files drift")
    args = ap.parse_args()

    inv = build_inventory()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    yaml_path = OUT_DIR / "parity_inventory.yaml"
    json_path = OUT_DIR / "parity_inventory.json"

    yaml_text = yaml.safe_dump(inv, sort_keys=False, allow_unicode=True)
    json_text = json.dumps(inv, indent=2, sort_keys=False) + "\n"

    if args.check:
        if not yaml_path.is_file() or not json_path.is_file():
            print("FAIL: generated inventory missing; run without --check", file=sys.stderr)
            return 1
        if yaml_path.read_text(encoding="utf-8") != yaml_text:
            print("FAIL: parity_inventory.yaml is stale; regenerate", file=sys.stderr)
            return 1
        if json_path.read_text(encoding="utf-8") != json_text:
            print("FAIL: parity_inventory.json is stale; regenerate", file=sys.stderr)
            return 1
        print("OK: generated inventory matches registry + catalog")
        return 0

    yaml_path.write_text(yaml_text, encoding="utf-8")
    json_path.write_text(json_text, encoding="utf-8")
    print(f"Wrote {yaml_path.relative_to(ROOT)}")
    print(f"Wrote {json_path.relative_to(ROOT)}")
    print(
        "counts",
        inv["counts"],
        "levels",
        {
            lvl: sum(1 for c in inv["concepts"] if c["parity_level"] == lvl)
            for lvl in sorted(PARITY_LEVELS)
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
