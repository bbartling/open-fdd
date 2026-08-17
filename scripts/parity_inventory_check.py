#!/usr/bin/env python3
"""CI gate for Wave 0 parity inventory, statuses, aliases, fixtures, and SQL orphans."""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    print("FAIL: PyYAML required", file=sys.stderr)
    raise SystemExit(2)

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "sql_rules" / "registry.yaml"
INVENTORY = ROOT / "sql_rules" / "generated" / "parity_inventory.yaml"
CATALOG = ROOT / "open_fdd" / "rules" / "cookbook_catalog.py"
SQL_DIR = ROOT / "sql_rules"

SQL_ANALYTICS = frozenset(
    {
        "FAN-RUNTIME-HOURS",
        "AVG-ZONE-TEMP",
        "ZONE-COMFORT-PCT",
        "FAULT-ELAPSED-HOURS",
    }
)
ALLOWED_LEVELS = frozenset(
    {
        "concept_only",
        "sql_screening",
        "predicate_parity",
        "mask_parity",
        "duration_parity",
        "site_soak",
    }
)
FORBIDDEN_LEGACY = frozenset(
    {"proven_building_100", "ported_from_cookbook", "skipped_missing_roles"}
)


def fail(msg: str) -> None:
    print(f"FAIL: {msg}", file=sys.stderr)
    raise SystemExit(1)


def main() -> int:
    if not INVENTORY.is_file():
        fail("missing sql_rules/generated/parity_inventory.yaml — run generate_parity_inventory.py")

    inv = yaml.safe_load(INVENTORY.read_text(encoding="utf-8"))
    concepts = inv.get("concepts") or []
    counts = inv.get("counts") or {}

    if inv.get("schema_version") != "parity-inventory-v2":
        fail(f"schema_version={inv.get('schema_version')!r} want parity-inventory-v2")
    if counts.get("pandas_diagnostics") != 62:
        fail(f"inventory pandas_diagnostics={counts.get('pandas_diagnostics')} want 62")
    if counts.get("sql_analytics") != 4:
        fail(f"inventory sql_analytics={counts.get('sql_analytics')} want 4")
    if counts.get("sql_registry") != 66:
        fail(f"inventory sql_registry={counts.get('sql_registry')} want 66")
    if len(concepts) != 66:
        fail(f"inventory concepts={len(concepts)} want 66")
    matrix = inv.get("matrix") or []
    if len(matrix) != 66:
        fail(f"inventory matrix={len(matrix)} want 66")
    required_matrix = {
        "rule_id",
        "title",
        "equipment_types",
        "required_roles",
        "optional_roles",
        "operational_proof_roles",
        "default_thresholds",
        "pandas_implementation",
        "datafusion_sql_implementation",
        "documentation_link",
        "test_coverage",
        "parity_status",
        "known_semantic_differences",
        "difference_class",
    }
    allowed_diff = {
        "none",
        "alias",
        "missing_implementation",
        "intentional_non_applicability",
        "unsupported_datafusion_expression",
        "documentation_error",
        "semantic_gap",
    }
    for row in matrix:
        missing_keys = sorted(required_matrix - set(row))
        if missing_keys:
            fail(f"{row.get('rule_id')}: matrix missing {missing_keys}")
        if row.get("difference_class") not in allowed_diff:
            fail(f"{row.get('rule_id')}: bad difference_class={row.get('difference_class')}")
    chw = next(r for r in matrix if r["rule_id"] == "CHW-1")
    if chw.get("difference_class") not in {"none", "semantic_gap"}:
        fail(f"CHW-1 unexpected difference_class={chw.get('difference_class')}")
    sched = next(r for r in matrix if r["rule_id"] == "SCHED-247")
    if sched.get("difference_class") not in {"none", "semantic_gap"}:
        fail(f"SCHED-247 unexpected difference_class={sched.get('difference_class')}")
    sv_rate = next(r for r in matrix if r["rule_id"] == "SV-RATE")
    if sv_rate.get("difference_class") != "semantic_gap":
        fail(f"SV-RATE unexpected difference_class={sv_rate.get('difference_class')}")
    if "count_explanation" not in inv:
        fail("missing count_explanation for 62-versus-66")

    diag = [c for c in concepts if c.get("kind") == "diagnostic"]
    analytics = [c for c in concepts if c.get("kind") == "sql_analytics"]
    if len(diag) != 62 or len(analytics) != 4:
        fail(f"kind split diagnostic={len(diag)} analytics={len(analytics)}")

    analytics_ids = {c["canonical_id"] for c in analytics}
    if analytics_ids != SQL_ANALYTICS:
        fail(f"analytics ids {sorted(analytics_ids)} != {sorted(SQL_ANALYTICS)}")

    # Registry live check
    reg = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
    rules = reg.get("rules") or []
    if len(rules) != 66:
        fail(f"registry rules={len(rules)} want 66")

    levels = Counter()
    for r in rules:
        st = r.get("parity_status")
        if st in FORBIDDEN_LEGACY:
            fail(f"{r.get('rule_id')} still uses legacy parity_status={st}")
        if st not in ALLOWED_LEVELS:
            fail(f"{r.get('rule_id')} invalid parity_status={st}")
        levels[st] += 1

    # Aliases
    fc13 = next(r for r in rules if r["rule_id"] == "FC13-SAT-HIGH")
    if "FC13" not in (fc13.get("aliases") or []):
        fail("FC13-SAT-HIGH must retain alias FC13")
    sv = next(r for r in rules if r["rule_id"] == "SV-RATE")
    if "SV-SLEW" not in (sv.get("aliases") or []):
        fail("SV-RATE must retain alias SV-SLEW")

    # Catalog count
    cat = CATALOG.read_text(encoding="utf-8")
    pandas_ids = re.findall(r'CookbookRule\(\s*\n?\s*"([A-Z][A-Z0-9-]*)"', cat)
    pandas_ids = list(dict.fromkeys(pandas_ids))
    if len(pandas_ids) != 62:
        fail(f"cookbook_catalog CookbookRule count={len(pandas_ids)} want 62")
    if "SV-SLEW" not in cat:
        fail("cookbook_catalog must document SV-SLEW alias")

    # SQL file orphans / missing
    sql_files = {p.name for p in SQL_DIR.glob("*.sql")}
    for r in rules:
        sf = r.get("sql_file")
        if not sf or sf not in sql_files:
            fail(f"{r.get('rule_id')} sql_file missing: {sf}")
    referenced = {r.get("sql_file") for r in rules}
    orphan_sql = sorted(sql_files - referenced)
    if orphan_sql:
        fail(f"orphan SQL files not in registry: {orphan_sql}")

    # Fixture matrix: every diagnostic required case must exist on disk
    missing: list[str] = []
    for c in diag:
        for fx in c.get("proof_fixtures") or []:
            if not fx.get("required"):
                continue
            path = ROOT / fx["path"]
            marker = path / "README.md"
            hist = path / "history_wide.csv"
            expected = path / "expected.json"
            if not (marker.is_file() or hist.is_file() or expected.is_file()):
                missing.append(fx["path"])
    if missing:
        fail(
            f"{len(missing)} required fixture scaffold paths missing "
            f"(first 8: {missing[:8]})"
        )

    # Seed fixtures must be real (history + expected)
    seeds_ok = 0
    for c in diag:
        for fx in c.get("proof_fixtures") or []:
            if not fx.get("oracle_seed"):
                continue
            path = ROOT / fx["path"]
            if not (path / "history_wide.csv").is_file():
                fail(f"oracle seed missing history_wide.csv: {fx['path']}")
            if not (path / "expected.json").is_file():
                fail(f"oracle seed missing expected.json: {fx['path']}")
            seeds_ok += 1
    if seeds_ok < 3:
        fail(f"need >=3 oracle_seed fixtures present, found {seeds_ok}")

    # Advertised executable fixtures (present=true) must have history + expected.
    for c in diag:
        rid = str(c.get("rule_id") or "")
        for fx in c.get("proof_fixtures") or []:
            path = ROOT / fx["path"]
            hist = path / "history_wide.csv"
            expected = path / "expected.json"
            if fx.get("present"):
                if not hist.is_file() or not expected.is_file():
                    fail(
                        f"advertised executable fixture missing history/expected: {fx['path']}"
                    )
            if rid in {"VAV-7", "VAV-4", "FC7", "VAV-2", "VAV-6", "RESET-1"} and fx.get("required"):
                cols = path / "columns.csv"
                if not (hist.is_file() and expected.is_file() and cols.is_file()):
                    fail(
                        f"{rid} required fixture must include history_wide.csv, columns.csv, expected.json: {fx['path']}"
                    )

    print("OK: parity inventory contract")
    print("parity_level counts:", dict(levels))
    print(f"oracle_seed fixtures: {seeds_ok}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
