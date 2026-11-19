"""Open-FDD pandas cookbook registry (+ optional CUSTOM-* agent rules)."""

from open_fdd.rules.base import RuleResult
from open_fdd.rules.cookbook_catalog import RULES as CANONICAL_RULES
from open_fdd.rules.cookbook_catalog import RULES_BY_ID as CANONICAL_RULES_BY_ID
from open_fdd.rules.cookbook_catalog import catalog
from open_fdd.rules.custom_registry import active_rules, active_rules_by_id, custom_rules
from open_fdd.rules.runner import infer_equipment_kind, run_all_cookbook_rules, run_batch, run_cookbook_rule
from open_fdd.rules.summary import summarize

# Canonical Open-FDD cookbook (never shrink this silently).
CANONICAL_RULE_COUNT = len(CANONICAL_RULES)

# Active catalog = canonical + agent CUSTOM-* rules from custom_rules.py
RULES = active_rules()
RULES_BY_ID = active_rules_by_id()


def _context(df, equipment_id, equipment_type, site_id, building_id):
    """The frame with explicit context applied. Explicit keywords win over ``df.attrs``; ``df`` is not modified."""
    overrides = {
        key: value
        for key, value in (
            ("equipment_id", equipment_id),
            ("equipment_type", equipment_type),
            ("site_id", site_id),
            ("building_id", building_id),
        )
        if value is not None
    }
    if not overrides:
        return df
    frame = df.copy(deep=False)
    frame.attrs = {**dict(df.attrs), **overrides}
    return frame


def run_all(
    df,
    params_by_rule: dict | None = None,
    poll_seconds: float = 300.0,
    weather=None,
    require_operational_gates: bool = True,
    *,
    equipment_id: str | None = None,
    equipment_type: str | None = None,
    site_id: str | None = None,
    building_id: str | None = None,
) -> list[RuleResult]:
    """Run every active rule on one equipment frame (Haystack role columns, SI).

    Equipment context comes from the keywords when given, else from ``df.attrs`` (``equipment_id``,
    ``equipment_type``, ``site_id``, ``building_id``). An unstamped frame is type ``UNKNOWN`` and every rule is
    ``NOT_APPLICABLE_EQUIPMENT_TYPE``; :func:`summarize` explains an all-skipped run.
    """
    d = _context(df, equipment_id, equipment_type, site_id, building_id)
    return run_all_cookbook_rules(
        d,
        equipment_id=str(d.attrs.get("equipment_id", "") or ""),
        poll_seconds=poll_seconds,
        params_by_rule=params_by_rule,
        weather=weather,
        site_id=str(d.attrs.get("site_id", "") or ""),
        building_id=str(d.attrs.get("building_id", "") or ""),
        equipment_type=str(d.attrs.get("equipment_type", "") or ""),
        require_operational_gates=require_operational_gates,
    )


def run_rule(
    rule_id: str,
    df,
    params: dict | None = None,
    poll_seconds: float = 300.0,
    weather=None,
    require_operational_gates: bool = True,
    *,
    equipment_id: str | None = None,
    equipment_type: str | None = None,
    site_id: str | None = None,
    building_id: str | None = None,
) -> RuleResult:
    """Run one rule; equipment context as in :func:`run_all`."""
    rule = RULES_BY_ID[rule_id]
    d = _context(df, equipment_id, equipment_type, site_id, building_id)
    eid = str(d.attrs.get("equipment_id", "") or "")
    return run_cookbook_rule(
        rule,
        d,
        equipment_id=eid,
        equipment_kind=infer_equipment_kind(
            eid,
            df=d,
            equipment_type=str(d.attrs.get("equipment_type", "") or ""),
        ),
        poll_seconds=poll_seconds,
        params_by_rule={rule_id: params or {}},
        weather=weather,
        site_id=str(d.attrs.get("site_id", "") or ""),
        building_id=str(d.attrs.get("building_id", "") or ""),
        equipment_type=str(d.attrs.get("equipment_type", "") or ""),
        require_operational_gates=require_operational_gates,
    )


__all__ = [
    "RULES",
    "RULES_BY_ID",
    "CANONICAL_RULES",
    "CANONICAL_RULES_BY_ID",
    "CANONICAL_RULE_COUNT",
    "RuleResult",
    "catalog",
    "custom_rules",
    "active_rules",
    "infer_equipment_kind",
    "run_all",
    "run_rule",
    "run_all_cookbook_rules",
    "run_batch",
    "run_cookbook_rule",
    "summarize",
]
