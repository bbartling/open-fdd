"""W4 parity family table (checked-in plan data for scoped gates)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
FAMILIES_PATH = REPO / "tests" / "fixtures" / "si_cutover" / "w4_parity_families.json"

W4C_SI_ZONE_FAMILY = "W4c_si_zone"
W4B_AHU_ECON_FAMILY = "W4b_ahu_econ"


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
    ids = list(fam.get("rules") or [])
    if ids == ["*"]:
        return None
    return {str(r) for r in ids}


def family_meta(family: str) -> dict:
    doc = load_families_doc()
    fam = (doc.get("families") or {}).get(family)
    if not fam:
        raise KeyError(f"unknown parity family {family!r}")
    return dict(fam)


@lru_cache(maxsize=16)
def family_rule_ids(family: str) -> frozenset[str]:
    fam = family_meta(family)
    rules = fam.get("rules") or []
    if rules == ["*"]:
        raise ValueError(f"family {family!r} is full-matrix; no rule subset")
    return frozenset(str(r) for r in rules)


@lru_cache(maxsize=16)
def family_dataset_ids(family: str) -> frozenset[str]:
    fam = family_meta(family)
    datasets = fam.get("datasets")
    if not datasets:
        raise KeyError(f"family {family!r} has no datasets[] in {FAMILIES_PATH.name}")
    return frozenset(str(d) for d in datasets)


def sql_si_pack_enabled(rule_id: str) -> bool:
    """Postgres rules converted to SI storage in the W4c_si_zone family."""
    return rule_id in family_rule_ids(W4C_SI_ZONE_FAMILY)


def ahu_econ_si_sql_shipped(rule_id: str) -> bool:
    """AHU economizer/ventilation rules whose product SQL is SI-native (W4b)."""
    return rule_id in family_rule_ids(W4B_AHU_ECON_FAMILY)
