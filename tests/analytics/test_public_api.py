"""Stable analytics package exports."""

from __future__ import annotations


def test_analytics_public_exports():
    import open_fdd.analytics as a

    for name in (
        "OccupancySchedule",
        "infer_poll_seconds",
        "hours_under_mask",
        "occupied_mask",
        "build_meter_monthly_table",
        "dataset_time_span",
        "equipment_type_from_id",
        "zone_comfort_fail_ranking",
        "vav_health_matrix",
        "mech_cooling_oat_bins",
        "dump_tables",
    ):
        assert hasattr(a, name), name
