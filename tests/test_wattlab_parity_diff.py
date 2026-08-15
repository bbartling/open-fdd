"""Classifier for WattLab dump-vs-dump — empty accepted list until soak evidence."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from wattlab_parity_diff import (  # noqa: E402
    _intentional_accepted,
    _sql_screening_pair,
    _status_ok,
)


def test_empty_accepted_list():
    ok, why = _intentional_accepted("CHW-1", "SKIPPED_EQUIPMENT_OFF", "FAULT", 0.0, 0.0)
    assert not ok
    assert why == ""
    ok, _ = _intentional_accepted("SCHED-247", "PASS", "FAULT", 0.0, 1561.0)
    assert not ok
    ok, _ = _intentional_accepted("FC7", "SKIPPED_MISSING_ROLES", "PASS", 0.0, 0.0)
    assert not ok


def test_other_rule_status_mismatch_not_intentional():
    ok, _ = _intentional_accepted("FC1", "PASS", "FAULT", 0.0, 12.0)
    assert not ok


def test_fault_intersection_hours_are_blockers():
    ok, _ = _sql_screening_pair("FC1", "FAULT", "FAULT", 10.0, 200.0)
    assert not ok
    ok, _ = _sql_screening_pair("AHU-SATDEV", "FAULT", "FAULT", 373.0, 1730.0)
    assert not ok


def test_na_vs_pass_is_not_fault_pass_blocker():
    """Classifier helper stays empty; compare_fdd accepts N/A omit separately."""
    ok, _ = _sql_screening_pair("AHU-DUCTHI", "NOT_APPLICABLE_EQUIPMENT_TYPE", "PASS", 0.0, 0.0)
    assert not ok


def test_compare_fdd_na_omit_accepted(tmp_path):
    from wattlab_parity_diff import compare_fdd

    o = tmp_path / "o"
    r = tmp_path / "r"
    o.mkdir()
    r.mkdir()
    (o / "fdd_findings.csv").write_text(
        "rule_id,equipment_id,status,fault_hours\n"
        "AHU-DUCTHI,VAV_1,NOT_APPLICABLE_EQUIPMENT_TYPE,0\n"
        "ECON-2,AHU_1,FAULT,10\n",
        encoding="utf-8",
    )
    (r / "fdd_findings.csv").write_text(
        "rule_id,equipment_id,status,fault_hours\n"
        "ECON-2,AHU_1,FAULT,10\n",
        encoding="utf-8",
    )
    rows = compare_fdd(o, r)
    na = next(x for x in rows if x.get("key") == "AHU-DUCTHI::VAV_1")
    assert na["severity"] == "accepted"
    hit = next(x for x in rows if x.get("key") == "ECON-2::AHU_1")
    assert hit["severity"] == "noise"


def test_one_sided_sensor_mean_not_blocker(tmp_path):
    from wattlab_parity_diff import compare_analytics_tables

    o = tmp_path / "o"
    r = tmp_path / "r"
    o.mkdir()
    r.mkdir()
    for name in (
        "motor_hours.csv",
        "motor_weekly.csv",
        "sensor_health_matrix.csv",
        "sensor_fault_summary.csv",
        "sensor_stats_all.csv",
        "sensor_stats_fan_on.csv",
        "sensor_stats_fan_off.csv",
        "sensor_diurnal_24h.csv",
        "setpoints.csv",
        "mech_cooling_oat_bins.csv",
        "mech_cooling_coverage.csv",
        "economizer_weather.csv",
        "operating_signatures.csv",
        "schedule_inference_table.csv",
        "weather_observed.csv",
        "meter_monthly_electric.csv",
        "rcx_preset_coverage.csv",
        "rcx_zone_comfort_ranking.csv",
    ):
        (o / name).write_text("equipment_id\nAHU_1\n", encoding="utf-8")
        (r / name).write_text("equipment_id\nAHU_1\n", encoding="utf-8")
    (o / "sensor_stats_all.csv").write_text(
        "equipment_id,signal,mean\nAHU_1,sat,70\n", encoding="utf-8"
    )
    (r / "sensor_stats_all.csv").write_text(
        "equipment_id,signal\nAHU_1,sat\n", encoding="utf-8"
    )
    rows = compare_analytics_tables(o, r)
    assert not any(
        x.get("artifact") == "sensor_stats_all.csv" and x.get("severity") == "blocker"
        for x in rows
    )


def test_skip_vs_fault_is_blocker():
    ok, _ = _sql_screening_pair("VAV-1", "SKIPPED_EQUIPMENT_OFF", "FAULT", 0.0, 12.0)
    assert not ok


def test_pass_aliases():
    assert _status_ok("PASS", "OK")
    assert _status_ok("SKIPPED_MISSING_ROLES", "SKIPPED_EQUIPMENT_OFF")
    assert not _status_ok("PASS", "FAULT")
