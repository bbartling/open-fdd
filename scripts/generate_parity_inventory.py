#!/usr/bin/env python3
"""Generate sql_rules/generated/parity_inventory.{yaml,json} from registry + pandas catalog.

Contract: 62 pandas diagnostics + 4 SQL-only analytics = 66 SQL registry entries.
Aliases (SV-SLEW, FC13, excess_runtime) are not extra rules.

Does not claim mask/duration parity — statuses come from registry.yaml plus
classified known differences.
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
TESTS_ROOT = ROOT / "tests"
PANDAS_COOKBOOK = "docs/rules/cookbook/pandas-cookbook.md"
SQL_COOKBOOK = "docs/rules/cookbook/datafusion-sql-cookbook.md"

SQL_ANALYTICS = frozenset(
    {
        "FAN-RUNTIME-HOURS",
        "AVG-ZONE-TEMP",
        "ZONE-COMFORT-PCT",
        "FAULT-ELAPSED-HOURS",
    }
)

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

DIFFERENCE_CLASSES = (
    "none",
    "alias",
    "missing_implementation",
    "intentional_non_applicability",
    "unsupported_datafusion_expression",
    "documentation_error",
    "semantic_gap",
)

# Classified from executable pandas vs SQL, not from padded counts.
KNOWN_DIFFERENCES: dict[str, dict] = {
    "CHW-1": {
        "class": "none",
        "note": (
            "Missing proof → pandas SKIPPED_MISSING_ROLES; SQL returns 0 fault hours "
            "(optional proof roles). Proven-off zeros do not accumulate ΔT hours."
        ),
    },
    "SCHED-247": {
        "class": "none",
        "note": (
            "4.3 ranked proof (status/current > command; pressure inferred only). "
            "SQL mean(on) >= always_on_pct over the analysis window matches pandas "
            "_sched247. Keep sql_screening; do not mark proven from B100 hours."
        ),
    },
    "FC7": {
        "class": "missing_implementation",
        "note": "concept_only — SQL file is a placeholder; do not claim twin parity",
    },
    "SV-RATE": {
        "class": "semantic_gap",
        "note": (
            "Pandas ROLE_TO_PROFILE has 30+ quantity/location slew limits; SQL windows "
            "five air temps against one STEADY_FAULT_PER_HOUR. Leave sql_screening; "
            "do not mark proven from B100 hours. Alias SV-SLEW is not an extra rule."
        ),
    },
    "FAN-RUNTIME-HOURS": {
        "class": "intentional_non_applicability",
        "note": "SQL analytics rollup — not a pandas diagnostic",
    },
    "AVG-ZONE-TEMP": {
        "class": "intentional_non_applicability",
        "note": "SQL analytics rollup — not a pandas diagnostic",
    },
    "ZONE-COMFORT-PCT": {
        "class": "intentional_non_applicability",
        "note": "SQL analytics rollup — not a pandas diagnostic",
    },
    "FAULT-ELAPSED-HOURS": {
        "class": "intentional_non_applicability",
        "note": "SQL analytics rollup — not a pandas diagnostic",
    },
}

GATE_PROOF_ROLES = {
    "fan_running": [
        "fan-status",
        "fan-speed-feedback",
        "fan-current",
        "fan-power",
        "airflow-proof",
        "fan-cmd",
    ],
    "hydronic_flow": [
        "pump-status",
        "chw-pump-status",
        "hw-pump-status",
        "pump-speed-feedback",
        "pump-current",
        "chw-flow",
        "water-flow",
        "chiller-status",
        "chiller-current",
        "chiller-power",
        "pump-cmd",
        "chw-pump-cmd",
        "hw-pump-cmd",
    ],
    "compressor": [
        "compressor-status",
        "equipment-enable",
        "fan-status",
        "fan-cmd",
    ],
    "control_loop": [
        "fan-status",
        "fan-speed-feedback",
        "fan-current",
        "fan-power",
        "airflow-proof",
        "fan-cmd",
        "loop-enabled",
    ],
    "equipment_energized": [
        "fan-status",
        "fan-speed-feedback",
        "fan-current",
        "fan-power",
        "airflow-proof",
        "fan-cmd",
        "pump-status",
        "chw-pump-status",
        "hw-pump-status",
        "pump-current",
        "chw-flow",
        "compressor-status",
        "equipment-enable",
    ],
    "always": [],
    "conditional": [],
}


def pandas_ids_from_catalog() -> list[str]:
    text = CATALOG.read_text(encoding="utf-8")
    ids = re.findall(r'CookbookRule\(\s*\n?\s*"([A-Z][A-Z0-9-]*)"', text)
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


def load_pandas_objects() -> tuple[dict, dict]:
    """Return (rules_by_id, gates) from the live package when importable."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    try:
        from open_fdd.rules.cookbook_catalog import RULES_BY_ID
        from open_fdd.rules.operational_gate import RULE_GATES
    except ImportError:
        return {}, {}
    return dict(RULES_BY_ID), dict(RULE_GATES)


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


def _slug(rule_id: str) -> str:
    return rule_id.lower()


def _docs_link(rule_id: str, *, sql: bool = False) -> str:
    page = SQL_COOKBOOK if sql else PANDAS_COOKBOOK
    return f"{page}#{_slug(rule_id)}"


def _scan_test_coverage() -> dict[str, list[str]]:
    hits: dict[str, list[str]] = {}
    if not TESTS_ROOT.is_dir():
        return hits
    for path in TESTS_ROOT.rglob("*.py"):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        rel = str(path.relative_to(ROOT)).replace("\\", "/")
        for m in re.findall(r"\b([A-Z]{2,}(?:-\d+|[A-Z0-9-]*)?)\b", text):
            hits.setdefault(m, [])
            if rel not in hits[m]:
                hits[m].append(rel)
    scripts = ROOT / "scripts"
    for path in scripts.glob("*oracle*.py"):
        rel = str(path.relative_to(ROOT)).replace("\\", "/")
        text = path.read_text(encoding="utf-8")
        for m in re.findall(r"\b([A-Z]{2,}(?:-\d+|[A-Z0-9-]*)?)\b", text):
            hits.setdefault(m, [])
            if rel not in hits[m]:
                hits[m].append(rel)
    return hits


def _default_thresholds(rule_obj, registry_params: dict) -> dict:
    out: dict = {}
    if rule_obj is not None:
        for p in getattr(rule_obj, "params", []) or []:
            out[p.key] = {
                "default": p.default,
                "unit": p.unit,
                "min": p.min,
                "max": p.max,
                "step": p.step,
                "label": p.label,
            }
        out.setdefault(
            "confirm_seconds",
            {
                "default": float(getattr(rule_obj, "confirm_seconds", 300) or 300),
                "unit": "sec",
            },
        )
        return out
    for key, spec in (registry_params or {}).items():
        if isinstance(spec, dict):
            out[key] = {
                "default": spec.get("default"),
                "unit": spec.get("unit"),
                "min": spec.get("min"),
                "max": spec.get("max"),
                "step": spec.get("step"),
                "label": spec.get("label"),
            }
    return out


def _proof_roles(rule_id: str, gates: dict) -> tuple[str | None, list[str], float | None]:
    spec = gates.get(rule_id)
    if spec is None:
        return None, [], None
    kind = getattr(spec, "kind", None)
    delay = getattr(spec, "startup_delay_seconds", None)
    roles = list(GATE_PROOF_ROLES.get(kind, []))
    return kind, roles, delay


def _difference(rule_id: str, aliases: list[str]) -> tuple[str, str]:
    if rule_id in KNOWN_DIFFERENCES:
        d = KNOWN_DIFFERENCES[rule_id]
        return d["class"], d["note"]
    if aliases:
        return "alias", f"aliases: {', '.join(aliases)} (not independent rules)"
    return "none", ""


def build_inventory() -> dict:
    pandas_ids = pandas_ids_from_catalog()
    if len(pandas_ids) != 62:
        raise SystemExit(
            f"FAIL: expected 62 pandas CookbookRule ids, found {len(pandas_ids)}"
        )

    reg = load_registry()
    if len(reg) != 66:
        raise SystemExit(f"FAIL: expected 66 registry rules, found {len(reg)}")

    by_sql = {r["rule_id"]: r for r in reg if isinstance(r, dict) and "rule_id" in r}
    aliases_index: dict[str, str] = {}
    for r in reg:
        rid = r["rule_id"]
        for a in r.get("aliases") or []:
            aliases_index[str(a)] = rid
    # Pandas-only alias documented in cookbook_catalog
    aliases_index.setdefault("SV-SLEW", "SV-RATE")
    aliases_index.setdefault("excess_runtime", "SCHED-1")

    pandas_objs, gates = load_pandas_objects()
    test_hits = _scan_test_coverage()

    seed_map = {
        "ECON-4": {"fault"},
        "FC1": {"normal", "fault"},
        "VAV-1": {"missing_required_role"},
        "VAV-2": {"fault", "normal", "missing_required_role"},
        "VAV-6": {"fault", "normal", "missing_required_role"},
        "RESET-1": {"fault", "normal", "missing_required_role"},
        "CHW-1": {"missing_required_role", "equipment_off", "fault", "threshold_boundary"},
        "SCHED-247": {"fault", "normal"},
    }

    concepts: list[dict] = []
    matrix: list[dict] = []

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
            aliases = aliases + ["SV-SLEW"]
        if pid == "SCHED-1" and "excess_runtime" not in aliases:
            aliases = aliases + ["excess_runtime"]

        rule_obj = pandas_objs.get(pid)
        title = getattr(rule_obj, "title", None) or r.get("description") or pid
        equipment = list(getattr(rule_obj, "equipment_kinds", None) or [])
        required = list(getattr(rule_obj, "required_roles", None) or r.get("required_roles") or [])
        optional = list(getattr(rule_obj, "optional_roles", None) or r.get("optional_roles") or [])
        pandas_impl = None
        if rule_obj is not None and getattr(rule_obj, "compute", None) is not None:
            pandas_impl = getattr(rule_obj.compute, "__name__", None)
        pandas_impl = pandas_impl or r.get("pandas_function") or pid.lower().replace("-", "_")
        gate_kind, proof_roles, startup = _proof_roles(pid, gates)
        if gate_kind is None:
            gate_kind = "fan_or_occupied_when_declared"
        diff_class, diff_note = _difference(sql_id if sql_id in KNOWN_DIFFERENCES else pid, aliases)
        coverage = sorted(
            set(test_hits.get(pid, []) + test_hits.get(sql_id, []) + test_hits.get("SV-SLEW", [])[:0])
        )
        if pid == "SV-RATE":
            coverage = sorted(set(coverage + test_hits.get("SV-SLEW", [])))

        concept = {
            "canonical_id": sql_id,
            "pandas_id": pid,
            "rule_id": pid,
            "title": title,
            "aliases": aliases,
            "kind": "diagnostic",
            "equipment_types": equipment,
            "equipment_kinds": equipment or None,
            "required_roles": required,
            "optional_roles": optional,
            "operational_proof_roles": proof_roles,
            "default_thresholds": _default_thresholds(rule_obj, r.get("parameters") or {}),
            "pandas_implementation": pandas_impl,
            "datafusion_sql_implementation": r.get("sql_file"),
            "sql_file": r.get("sql_file"),
            "documentation_link": _docs_link(pid),
            "sql_documentation_link": _docs_link(sql_id, sql=True),
            "test_coverage": coverage,
            "parity_status": level,
            "parity_level": level,
            "difference_class": diff_class,
            "known_semantic_differences": diff_note,
            "operational_gate": gate_kind,
            "startup_delay_seconds": startup,
            "confirm_seconds": getattr(rule_obj, "confirm_seconds", None)
            if rule_obj is not None
            else r.get("confirm_seconds"),
            "parameters": r.get("parameters") or {},
            "time_semantics": "row_or_interval_per_sql_file",
            "output_schema": list(r.get("output_columns") or []),
            "proof_fixtures": fixture_entries(sql_id, seed_map.get(sql_id)),
        }
        concepts.append(concept)
        matrix.append(
            {
                "rule_id": pid,
                "title": title,
                "equipment_types": equipment,
                "required_roles": required,
                "optional_roles": optional,
                "operational_proof_roles": proof_roles,
                "default_thresholds": concept["default_thresholds"],
                "pandas_implementation": pandas_impl,
                "datafusion_sql_implementation": r.get("sql_file"),
                "documentation_link": concept["documentation_link"],
                "test_coverage": coverage,
                "parity_status": level,
                "known_semantic_differences": diff_note,
                "difference_class": diff_class,
            }
        )

    for aid in sorted(SQL_ANALYTICS):
        if aid not in by_sql:
            raise SystemExit(f"FAIL: missing SQL analytics {aid}")
        r = by_sql[aid]
        level = r.get("parity_status") or "concept_only"
        diff_class, diff_note = _difference(aid, list(r.get("aliases") or []))
        coverage = sorted(test_hits.get(aid, []))
        concept = {
            "canonical_id": aid,
            "pandas_id": None,
            "rule_id": aid,
            "title": r.get("description") or aid,
            "aliases": list(r.get("aliases") or []),
            "kind": "sql_analytics",
            "equipment_types": [],
            "equipment_kinds": None,
            "required_roles": list(r.get("required_roles") or []),
            "optional_roles": list(r.get("optional_roles") or []),
            "operational_proof_roles": [],
            "default_thresholds": _default_thresholds(None, r.get("parameters") or {}),
            "pandas_implementation": None,
            "datafusion_sql_implementation": r.get("sql_file"),
            "sql_file": r.get("sql_file"),
            "documentation_link": _docs_link(aid, sql=True),
            "sql_documentation_link": _docs_link(aid, sql=True),
            "test_coverage": coverage,
            "parity_status": level,
            "parity_level": level,
            "difference_class": diff_class,
            "known_semantic_differences": diff_note,
            "operational_gate": None,
            "startup_delay_seconds": None,
            "confirm_seconds": r.get("confirm_seconds"),
            "parameters": r.get("parameters") or {},
            "time_semantics": "analytics_rollup",
            "output_schema": list(r.get("output_columns") or []),
            "proof_fixtures": [],
        }
        concepts.append(concept)
        matrix.append(
            {
                "rule_id": aid,
                "title": concept["title"],
                "equipment_types": [],
                "required_roles": concept["required_roles"],
                "optional_roles": [],
                "operational_proof_roles": [],
                "default_thresholds": concept["default_thresholds"],
                "pandas_implementation": None,
                "datafusion_sql_implementation": r.get("sql_file"),
                "documentation_link": concept["documentation_link"],
                "test_coverage": coverage,
                "parity_status": level,
                "known_semantic_differences": diff_note,
                "difference_class": diff_class,
            }
        )

    sql_ids = set(by_sql)
    concept_sql = {c["canonical_id"] for c in concepts}
    orphans = sorted(sql_ids - concept_sql)
    if orphans:
        raise SystemExit(f"FAIL: orphan SQL rules not in inventory: {orphans}")

    class_counts = {}
    for row in matrix:
        class_counts[row["difference_class"]] = class_counts.get(row["difference_class"], 0) + 1

    return {
        "schema_version": "parity-inventory-v2",
        "generated_by": "scripts/generate_parity_inventory.py",
        "counts": {
            "pandas_diagnostics": 62,
            "sql_analytics": 4,
            "sql_registry": 66,
            "concepts": len(concepts),
            "aliases": len(aliases_index),
            "building_100_cartesian": "48 equipment × 62 diagnostics",
        },
        "count_explanation": (
            "62 is the executable pandas cookbook (CookbookRule constructors). "
            "66 is the SQL registry: those 62 twins plus 4 SQL-only analytics. "
            "Aliases SV-SLEW, FC13, and excess_runtime are not extra rules."
        ),
        "parity_levels": sorted(PARITY_LEVELS),
        "difference_classes": list(DIFFERENCE_CLASSES),
        "difference_class_counts": class_counts,
        "aliases_index": aliases_index,
        "matrix": matrix,
        "concepts": concepts,
    }


def dump_inventory(inv: dict) -> tuple[str, str]:
    yaml_text = yaml.safe_dump(inv, sort_keys=False, allow_unicode=True)
    json_text = json.dumps(inv, indent=2, sort_keys=False) + "\n"
    return yaml_text, json_text


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="fail if generated files drift")
    args = ap.parse_args()

    inv = build_inventory()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    yaml_path = OUT_DIR / "parity_inventory.yaml"
    json_path = OUT_DIR / "parity_inventory.json"
    yaml_text, json_text = dump_inventory(inv)

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
    print("counts", inv["counts"])
    print("difference_class_counts", inv["difference_class_counts"])
    print(
        "levels",
        {
            lvl: sum(1 for c in inv["concepts"] if c["parity_level"] == lvl)
            for lvl in sorted(PARITY_LEVELS)
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
