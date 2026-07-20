"""Open-FDD pandas cookbook registry (+ optional CUSTOM-* agent rules)."""

from app.rules.base import RuleResult
from app.rules.cookbook_catalog import RULES as CANONICAL_RULES
from app.rules.cookbook_catalog import RULES_BY_ID as CANONICAL_RULES_BY_ID
from app.rules.cookbook_catalog import catalog
from app.rules.custom_registry import active_rules, active_rules_by_id, custom_rules
from app.rules.runner import infer_equipment_kind, run_all_cookbook_rules, run_batch, run_cookbook_rule

# Canonical Open-FDD cookbook (never shrink this silently).
CANONICAL_RULE_COUNT = len(CANONICAL_RULES)

# Active catalog = canonical + agent CUSTOM-* rules from custom_rules.py
RULES = active_rules()
RULES_BY_ID = active_rules_by_id()


def run_all(
    df,
    params_by_rule: dict | None = None,
    poll_seconds: float = 300.0,
    weather=None,
    require_operational_gates: bool = True,
) -> list[RuleResult]:
    eq = df.attrs.get("equipment_id", "")
    return run_all_cookbook_rules(
        df,
        equipment_id=eq,
        poll_seconds=poll_seconds,
        params_by_rule=params_by_rule,
        weather=weather,
        require_operational_gates=require_operational_gates,
    )


def run_rule(
    rule_id: str,
    df,
    params: dict | None = None,
    poll_seconds: float = 300.0,
    weather=None,
    require_operational_gates: bool = True,
) -> RuleResult:
    rule = RULES_BY_ID[rule_id]
    return run_cookbook_rule(
        rule,
        df,
        equipment_id=df.attrs.get("equipment_id", ""),
        equipment_kind=infer_equipment_kind(
            str(df.attrs.get("equipment_id", "")),
            df=df,
            equipment_type=str(df.attrs.get("equipment_type", "")),
        ),
        poll_seconds=poll_seconds,
        params_by_rule={rule_id: params or {}},
        weather=weather,
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
]
