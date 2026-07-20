"""Merge agent custom rules with the 50 canonical cookbook rules."""

from __future__ import annotations

import os
from typing import Iterable

from app.rules.cookbook_catalog import CookbookRule
from app.rules.cookbook_catalog import RULES as CANONICAL_RULES
from app.rules.cookbook_catalog import RULES_BY_ID as CANONICAL_BY_ID


def _load_agent_custom() -> list[CookbookRule]:
    from app.rules import custom_rules as cr

    return list(getattr(cr, "CUSTOM_RULES", []) or [])


def _load_examples_if_enabled() -> list[CookbookRule]:
    flag = (os.environ.get("VIBE19_INCLUDE_EXAMPLE_CUSTOM_RULES") or "").strip().lower()
    if flag not in {"1", "true", "yes"}:
        return []
    from app.rules.custom_boilerplate import EXAMPLE_CUSTOM_RULES

    return list(EXAMPLE_CUSTOM_RULES)


def custom_rules() -> list[CookbookRule]:
    """Agent ``CUSTOM_RULES`` plus optional boilerplate examples."""
    seen: set[str] = set()
    out: list[CookbookRule] = []
    for r in _load_examples_if_enabled() + _load_agent_custom():
        rid = str(r.id).upper()
        if not rid.startswith("CUSTOM-"):
            raise ValueError(f"Custom rule id must start with CUSTOM-, got {r.id!r}")
        if rid in CANONICAL_BY_ID:
            raise ValueError(f"Custom rule id collides with canonical catalog: {rid}")
        if rid in seen:
            continue
        seen.add(rid)
        out.append(r)
    return out


def active_rules() -> list[CookbookRule]:
    """Canonical 50 + custom extras (never replaces canonical)."""
    return list(CANONICAL_RULES) + custom_rules()


def active_rules_by_id() -> dict[str, CookbookRule]:
    by_id = {r.id: r for r in active_rules()}
    # Compatibility alias for SV-RATE
    if "SV-RATE" in by_id:
        by_id.setdefault("SV-SLEW", by_id["SV-RATE"])
    return by_id


def iter_active_rule_ids() -> Iterable[str]:
    for r in active_rules():
        yield r.id
