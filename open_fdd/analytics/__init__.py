"""Open-FDD analytics helpers (oracle library surface)."""

from open_fdd.analytics.core import (
    dataset_time_span,
    mech_cooling_oat_bins,
    motor_run_hours_table,
    motor_run_hours_weekly,
)
from open_fdd.analytics.daytypes import day_type_series
from open_fdd.analytics.load_satisfaction import aggregate_load_satisfaction
from open_fdd.analytics.metering import build_meter_monthly_table, collect_meter_frames
from open_fdd.analytics.occupancy import OccupancySchedule, apply_schedule_occ_mode, occupied_mask
from open_fdd.analytics.poll import infer_poll_seconds
from open_fdd.analytics.rcx_plots import rcx_preset_coverage, zone_comfort_fail_ranking
from open_fdd.analytics.runtime_intervals import (
    UNLIMITED_GAP_SECONDS,
    hours_under_mask,
    interval_durations,
)
from open_fdd.analytics.site_model import equipment_type_from_id, resolve_equipment_type
from open_fdd.analytics.vav_health import vav_health_matrix, vav_health_summary

__all__ = [
    "OccupancySchedule",
    "UNLIMITED_GAP_SECONDS",
    "aggregate_load_satisfaction",
    "apply_schedule_occ_mode",
    "build_meter_monthly_table",
    "collect_meter_frames",
    "dataset_time_span",
    "day_type_series",
    "equipment_type_from_id",
    "hours_under_mask",
    "infer_poll_seconds",
    "interval_durations",
    "mech_cooling_oat_bins",
    "motor_run_hours_table",
    "motor_run_hours_weekly",
    "occupied_mask",
    "rcx_preset_coverage",
    "resolve_equipment_type",
    "vav_health_matrix",
    "vav_health_summary",
    "zone_comfort_fail_ranking",
]
