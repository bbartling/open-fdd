"""W4 parity family table (checked-in plan data for scoped gates)."""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
FAMILIES_PATH = REPO / "tests" / "fixtures" / "si_cutover" / "w4_parity_families.json"


def load_families_doc() -> dict:
    doc = json.loads(FAMILIES_PATH.read_text(encoding="utf-8"))
    if doc.get("schema") != "openfdd-si-parity-w4-families-v1":
        raise ValueError(f"{FAMILIES_PATH}: bad schema")
    return doc


def resolve_rule_scope(*, rules: tuple[str, ...] | None, family: str | None) -> set[str] | None:
    """Return rule_id set to filter parity, or None for all rules (full matrix)."""
    if rules and family:
        raise ValueError("use only one of rules= or family=")
    if rules:
        return {str(r).strip() for r in rules if str(r).strip()}
    if not family:
        return None
    doc = load_families_doc()
    fam = (doc.get("families") or {}).get(family)
    if not fam:
        raise KeyError(f"unknown parity family {family!r}")
    if "rules" not in fam:
        raise KeyError(f"parity family {family!r} has no rules list")
    ids = list(fam["rules"])
    if ids == ["*"]:
        return None
    return {str(r) for r in ids}


def resolve_analytics_scope(family: str | None) -> set[str] | None:
    """Analytics query stems a family owns: None = all 19, empty set = none.

    The full matrix (no family, or rules ``["*"]``) covers every query.
    """
    if not family:
        return None
    fam = family_meta(family)
    if list(fam.get("rules", [])) == ["*"]:
        return None
    queries = list(fam.get("analytics_queries", []))
    if queries == ["*"]:
        return None
    return {str(q) for q in queries}


def family_meta(family: str) -> dict:
    doc = load_families_doc()
    fam = (doc.get("families") or {}).get(family)
    if not fam:
        raise KeyError(f"unknown parity family {family!r}")
    return dict(fam)
