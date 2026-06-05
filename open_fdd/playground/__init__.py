"""
Portable Python FDD rule sandbox — same ``evaluate(row, cfg, …)`` contract as Rule Lab,
AWS ``fdd_lambda``, and edge batch runner.

Use from any pandas/Lambda pipeline::

    from open_fdd.playground.cookbook import cfg_threshold, window_rows_1h
    from open_fdd.playground.sandbox import compile_evaluate, sweep_rule
    from open_fdd.playground.rows import dataframe_to_evaluate_rows
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
from open_fdd.playground.rows import dataframe_to_evaluate_rows, readings_to_evaluate_rows
from open_fdd.playground.sandbox import compile_evaluate, lint_python, rule_globals, sweep_rule
from open_fdd.playground.series import (
    build_series_context,
    evaluate_rules_on_series,
    readings_to_rows,
    slim_fdd_summary,
)

__all__ = [
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
