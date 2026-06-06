"""Arrow-native FDD execution — columnar rules over PyArrow Tables."""

from .backend import ArrowRuleResult, run_arrow_rule
from .column_map_from_model import build_column_map_from_model_points
from .config import ArrowRuntimeConfig, configure_arrow_runtime, get_arrow_runtime_config
from .rules import detect_rule_backend, legacy_row_allowed, migrate_legacy_threshold_hint

__all__ = [
    "ArrowRuleResult",
    "ArrowRuntimeConfig",
    "build_column_map_from_model_points",
    "configure_arrow_runtime",
    "detect_rule_backend",
    "get_arrow_runtime_config",
    "legacy_row_allowed",
    "migrate_legacy_threshold_hint",
    "run_arrow_rule",
]
