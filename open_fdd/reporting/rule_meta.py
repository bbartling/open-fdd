"""Resolve human-readable rule titles / summaries for Engineering Findings."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

# Fan-off / duct-static corroboration applies only to these rules.
DUCT_STATIC_RULE_IDS = frozenset({"FAN-OFF-STATIC", "AHU-DUCTHI", "FC1"})


@lru_cache(maxsize=1)
def _catalog() -> dict[str, Any]:
    try:
        from open_fdd.rules.cookbook_catalog import RULES_BY_ID

        return RULES_BY_ID
    except Exception:
        return {}


def rule_title(rule_id: str) -> str:
    rid = (rule_id or "").strip()
    if not rid:
        return ""
    if rid == "FAN-OFF-STATIC":
        return "Duct static with fan OFF"
    rule = _catalog().get(rid)
    if rule is not None and getattr(rule, "title", None):
        return str(rule.title)
    return rid


def rule_summary(rule_id: str) -> str:
    rid = (rule_id or "").strip()
    if not rid:
        return ""
    if rid == "FAN-OFF-STATIC":
        return (
            "Duct static remains high while the supply fan is proven OFF — "
            "strong instrumentation / reference-tubing suspicion."
        )
    rule = _catalog().get(rid)
    if rule is not None:
        summary = (getattr(rule, "summary", None) or "").strip()
        if summary:
            return summary
        title = (getattr(rule, "title", None) or "").strip()
        if title:
            return f"{title}."
    return f"Open-FDD rule {rid}."


def rule_label(rule_id: str, fallback: str | None = None) -> str:
    """Prefer catalog title; fall back to caller label or raw id."""
    title = rule_title(rule_id)
    if title and title != rule_id:
        return title
    fb = (fallback or "").strip()
    return fb or rule_id


def is_duct_static_rule(rule_id: str) -> bool:
    return (rule_id or "").strip() in DUCT_STATIC_RULE_IDS


def legend_rows(rule_ids: list[str] | set[str]) -> list[dict[str, str]]:
    """Unique rule_id → title / summary rows sorted by id."""
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for rid in sorted({str(r).strip() for r in rule_ids if r}):
        if rid in seen:
            continue
        seen.add(rid)
        out.append({"rule_id": rid, "title": rule_title(rid), "summary": rule_summary(rid)})
    return out
