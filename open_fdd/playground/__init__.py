"""
FDD rule authoring helpers.

**Default (3.0+):** Arrow-native rules via ``open_fdd.arrow_runtime`` and
``apply_faults_arrow(table, cfg, context)``.

**Legacy:** per-row ``evaluate(row, cfg, …)`` via ``sandbox`` (``backend: legacy_row`` only).
"""

from open_fdd.playground.cookbook import (
    DEFAULT_THRESHOLDS_F,
    ONE_HOUR_MS,
    attach_rolling_avg,
    cfg_threshold,
    hour_window_ready,
    normalize_rolling_avg_minutes,
    temp_unit_symbol,
    window_rows_1h,
)
from open_fdd.playground.arrow_templates import ARROW_TEMPLATES, DEFAULT_ARROW_RULE
from open_fdd.playground.sandbox import compile_evaluate, lint_python, rule_globals, sweep_rule
from open_fdd.playground.series import (
    build_series_context,
    evaluate_rules_on_series,
    readings_to_rows,
    slim_fdd_summary,
)

_LAZY_ROWS = frozenset({"dataframe_to_evaluate_rows", "readings_to_evaluate_rows"})


def __getattr__(name: str):
    if name in _LAZY_ROWS:
        from open_fdd.playground.rows import dataframe_to_evaluate_rows, readings_to_evaluate_rows

        return {
            "dataframe_to_evaluate_rows": dataframe_to_evaluate_rows,
            "readings_to_evaluate_rows": readings_to_evaluate_rows,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "ARROW_TEMPLATES",
    "DEFAULT_ARROW_RULE",
    "DEFAULT_THRESHOLDS_F",
    "ONE_HOUR_MS",
    "attach_rolling_avg",
    "build_series_context",
    "cfg_threshold",
    "compile_evaluate",
    "dataframe_to_evaluate_rows",
    "evaluate_rules_on_series",
    "hour_window_ready",
    "lint_python",
    "normalize_rolling_avg_minutes",
    "readings_to_evaluate_rows",
    "readings_to_rows",
    "rule_globals",
    "slim_fdd_summary",
    "sweep_rule",
    "temp_unit_symbol",
    "window_rows_1h",
]
