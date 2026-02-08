"""
Generic fault analytics and reporting.

Works with config-driven RuleRunner output. Provides fault duration,
motor runtime, sensor stats, and visualization helpers.
"""

from open_fdd.reports.fault_report import (
    analyze_bounds_episodes,
    analyze_flatline_episodes,
    build_report_multi_equipment,
    flatline_period,
    flatline_period_range,
    load_rules_for_report,
    print_bounds_episodes,
    print_column_mapping,
    print_flatline_episodes,
    print_summary,
    sensor_cols_from_column_map,
    summarize_all_faults,
    summarize_fault,
    time_range,
)
from open_fdd.reports.fault_viz import (
    all_fault_events,
    build_rule_sensor_mapping,
    build_sensor_map_for_summarize,
    get_fault_events,
    plot_fault_analytics,
    plot_flag_true_bars,
    run_fault_analytics,
    zoom_on_event,
)

try:
    from open_fdd.reports.docx_generator import (
        build_report,
        events_from_dataframe,
        events_to_summary_table,
    )
    _docx_available = True
except ImportError:
    _docx_available = False

__all__ = [
    "all_fault_events",
    "analyze_bounds_episodes",
    "analyze_flatline_episodes",
    "build_rule_sensor_mapping",
    "build_sensor_map_for_summarize",
    "flatline_period",
    "flatline_period_range",
    "get_fault_events",
    "plot_fault_analytics",
    "plot_flag_true_bars",
    "print_bounds_episodes",
    "print_column_mapping",
    "print_flatline_episodes",
    "print_summary",
    "run_fault_analytics",
    "sensor_cols_from_column_map",
    "build_report_multi_equipment",
    "load_rules_for_report",
    "summarize_all_faults",
    "summarize_fault",
    "time_range",
    "zoom_on_event",
]

if _docx_available:
    __all__ += ["build_report", "events_from_dataframe", "events_to_summary_table"]
