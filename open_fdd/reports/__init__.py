"""
Generic fault analytics and reporting.

Works with config-driven RuleRunner output. Provides fault duration,
motor runtime, and sensor stats when faults occur.
"""

from open_fdd.reports.fault_report import (
    analyze_flatline_episodes,
    flatline_period,
    flatline_period_range,
    print_flatline_episodes,
    print_summary,
    summarize_all_faults,
    summarize_fault,
    time_range,
)

__all__ = [
    "analyze_flatline_episodes",
    "flatline_period",
    "flatline_period_range",
    "print_flatline_episodes",
    "print_summary",
    "summarize_all_faults",
    "summarize_fault",
    "time_range",
]
