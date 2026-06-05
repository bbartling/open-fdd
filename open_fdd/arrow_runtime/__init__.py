"""Arrow-native FDD execution — columnar rules over PyArrow Tables."""

from .backend import ArrowRuleResult, run_arrow_rule
from .config import ArrowRuntimeConfig, configure_arrow_runtime, get_arrow_runtime_config
from .rules import detect_rule_backend, legacy_row_allowed, migrate_legacy_threshold_hint

__all__ = [
    "ArrowRuleResult",
    "ArrowRuntimeConfig",
    "configure_arrow_runtime",
    "detect_rule_backend",
    "get_arrow_runtime_config",
    "legacy_row_allowed",
    "migrate_legacy_threshold_hint",
    "run_arrow_rule",
]
