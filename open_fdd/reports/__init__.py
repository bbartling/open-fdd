"""
Generic fault analytics and reporting.

Works with config-driven RuleRunner output. Provides fault duration,
motor runtime, and sensor stats when faults occur.
"""

from open_fdd.reports.fault_report import (
    analyze_bounds_episodes,
    analyze_flatline_episodes,
    flatline_period,
    flatline_period_range,
    print_bounds_episodes,
    print_column_mapping,
    print_flatline_episodes,
    print_summary,
    sensor_cols_from_column_map,
    summarize_all_faults,
    summarize_fault,
    time_range,
)

__all__ = [
    "analyze_bounds_episodes",
    "analyze_flatline_episodes",
    "flatline_period",
    "flatline_period_range",
    "print_bounds_episodes",
    "print_column_mapping",
    "sensor_cols_from_column_map",
    "print_flatline_episodes",
    "print_summary",
    "summarize_all_faults",
    "summarize_fault",
    "time_range",
]
