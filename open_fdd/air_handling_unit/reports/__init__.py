"""
AHU fault analytics and reporting.

Works with config-driven RuleRunner output.
"""

from open_fdd.air_handling_unit.reports.fault_report import (
    summarize_fault,
    summarize_all_faults,
    print_summary,
)

__all__ = ["summarize_fault", "summarize_all_faults", "print_summary"]
