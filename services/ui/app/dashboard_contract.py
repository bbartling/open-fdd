"""Frozen UI sections / chart APIs — do not vibe-code away without updating the spec."""

from __future__ import annotations

# Lazy radio sections in streamlit_app.py (do not collapse/rename without updating tests + spec).
REQUIRED_MAIN_SECTIONS: tuple[str, ...] = (
    "Overview",
    "Data Model",
    "Run Rules",
    "Results by Category",
    "FDD Plots",
    "RCx Plots",
    "Metering",
    "Export",
)

# Public chart helpers in app/charts.py used by FDD Plots / RCx / Overview / Metering.
REQUIRED_CHART_APIS: tuple[str, ...] = (
    "rule_result_chart",
    "multi_equipment_timeseries",
    "multi_equipment_box",
    "oat_scatter",
    "motor_weekly_runtime_chart",
    "mech_cooling_oat_histogram",
    "bas_vs_web_oat_histogram",
    "bas_vs_web_oat_overlay",
    "equipment_inspection_chart",
    "sensor_fault_chart",
    "vav_comfort_donut",
    "max_plot_points",
    "plotly_config",
)

# Other UI entry points that must remain importable.
REQUIRED_UI_ENTRYPOINTS: tuple[str, ...] = (
    "app.ui_rcx_tab:render_rcx_plots_tab",
    "app.rcx_plots:PRESETS",
    "app.rcx_plots:REQUIRED_RCX_PRESET_IDS",
    "app.rcx_plots:collect_oat_scatter",
    "app.rcx_plots:collect_role_series",
    "app.rcx_plots:collect_status_series",
    "app.rcx_plots:rcx_preset_coverage",
    "app.rcx_plots:pump_mode_summary_bundle",
    "app.data_model_tree:build_data_model_tree",
    "app.rule_card:build_rule_card",
    "app.docx_report:load_generic_rcx_report",
    "app.docx_report:applicable_rules_for_equipment",
    "app.report_downloads:render_overview_rcx_download",
    "app.browser_session:write_browser_session_pointer",
    "app.browser_session:read_browser_session_pointer",
    "app.browser_session:clear_browser_session_pointer",
    "app.model_seed:infer_schedules",
    "app.model_seed:operating_signatures",
    "app.open_meteo:fetch_open_meteo",
)
