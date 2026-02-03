"""
Generic fault analytics and reporting.

Works with config-driven RuleRunner output. Provides fault duration,
motor runtime, and sensor stats when faults occur.
"""

from open_fdd.reports.fault_report import (
    summarize_fault,
    summarize_all_faults,
    print_summary,
)

__all__ = ["summarize_fault", "summarize_all_faults", "print_summary"]
