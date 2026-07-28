#!/usr/bin/env python3
"""Milestone D2 — SQL rule parity mutation / cookbook integrity checks.

Complements ``cookbook_parity_check.py`` with registry count, dual-cookbook
heading floors, high-risk keyword presence, and path-mutation guards that fail
if a protected cookbook file is missing (simulating accidental deletion).

Exit 0 when healthy.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore

ROOT = Path(__file__).resolve().parents[1]
COOKBOOK = ROOT / "docs" / "rules" / "cookbook"
REGISTRY = ROOT / "sql_rules" / "registry.yaml"

MIN_RULE_HEADINGS = 59
MIN_REGISTRY_RULES = 63
RULE_HEADING_RE = re.compile(r"^### [A-Z][A-Z0-9-]* —", re.MULTILINE)

# Dual cookbooks that must exist (mutation: deleting either must fail this script).
PROTECTED_COOKBOOK_PATHS = (
    COOKBOOK / "pandas-cookbook.md",
    COOKBOOK / "datafusion-sql-cookbook.md",
    COOKBOOK / "parity-matrix.md",
)

# High-risk gates / roles that must remain documented in both cookbooks.
HIGH_RISK_KEYWORDS = (
    "fan-status",
    "fan_status",
    "occupied",
    "occ_mode",
    "compressor",
    "oat_rat",  # OAT/RAT split / identifiability guard language
)


def _fail(msg: str) -> None:
    print(f"FAIL: {msg}", file=sys.stderr)
    raise SystemExit(1)


def check_registry_count() -> int:
    if not REGISTRY.is_file():
        _fail(f"missing {REGISTRY.relative_to(ROOT)}")
    text = REGISTRY.read_text(encoding="utf-8")
    if yaml is not None:
        data = yaml.safe_load(text)
        rules = data.get("rules") if isinstance(data, dict) else None
        if not isinstance(rules, list):
            _fail("sql_rules/registry.yaml: 'rules' must be a list")
        count = len(rules)
    else:
        count = len(re.findall(r"(?m)^\s+-\s+rule_id:\s+\S+", text))
    if count < MIN_REGISTRY_RULES:
        _fail(
            f"sql_rules/registry.yaml expected >= {MIN_REGISTRY_RULES} rules, found {count}"
        )
    print(f"PASS registry rule count ({count})")
    return count


def check_dual_cookbooks_and_headings() -> None:
    for path in PROTECTED_COOKBOOK_PATHS:
        if not path.is_file():
            _fail(f"protected cookbook missing (mutation): {path.relative_to(ROOT)}")
    for name in ("pandas-cookbook.md", "datafusion-sql-cookbook.md"):
        text = (COOKBOOK / name).read_text(encoding="utf-8")
        n = len(RULE_HEADING_RE.findall(text))
        if n < MIN_RULE_HEADINGS:
            _fail(f"{name}: expected >= {MIN_RULE_HEADINGS} rule headings, found {n}")
        print(f"PASS {name} headings ({n} >= {MIN_RULE_HEADINGS})")


def check_high_risk_keywords() -> None:
    for name in ("pandas-cookbook.md", "datafusion-sql-cookbook.md"):
        text = (COOKBOOK / name).read_text(encoding="utf-8")
        missing = [kw for kw in HIGH_RISK_KEYWORDS if kw not in text]
        if missing:
            _fail(f"{name} missing high-risk keyword(s): {missing}")
        print(f"PASS {name} high-risk keywords present")


def check_mutation_paths() -> None:
    """Explicit mutation section: paths that must exist or this check fails.

    Reviewers / CI treat absence of these files as a failed mutation (as if the
    cookbook were deleted). This does not rewrite files — it only asserts paths.
    """
    mutated_would_fail = []
    for path in PROTECTED_COOKBOOK_PATHS:
        rel = str(path.relative_to(ROOT))
        if path.is_file():
            print(f"PASS mutation guard: {rel} present (delete would fail)")
        else:
            mutated_would_fail.append(rel)
    if mutated_would_fail:
        _fail(
            "mutation paths missing (would fail if cookbooks deleted): "
            + ", ".join(mutated_would_fail)
        )


def main() -> int:
    print("== rule_parity_mutation_check (Milestone D2) ==")
    check_registry_count()
    check_dual_cookbooks_and_headings()
    check_high_risk_keywords()
    check_mutation_paths()
    print("All rule parity mutation checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
