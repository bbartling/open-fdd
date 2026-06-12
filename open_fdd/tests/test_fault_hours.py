"""Unit tests for fault-hour analytics."""

from open_fdd.reports.fault_hours import aggregate_fault_hours, fault_hours_from_fdd_runs


def test_open_ended_active_fault_uses_duration():
    runs = [
        {
            "flagged": 3,
            "rows": 10,
            "analytics": {"estimated_fault_duration_sec": 1800},
            "equipment_name": "AHU-1",
            "fault_code": "X",
            "rule_name": "Test",
        }
    ]
    rows = fault_hours_from_fdd_runs(runs)
    assert rows[0]["elapsed_hours"] == 0.5


def test_grouping_by_severity():
    rows = [
        {"severity": "critical", "elapsed_hours": 1.0, "equipment": "A"},
        {"severity": "critical", "elapsed_hours": 2.0, "equipment": "B"},
        {"severity": "warning", "elapsed_hours": 1.0, "equipment": "C"},
    ]
    agg = aggregate_fault_hours(rows, group_by="severity")
    by_group = {r["group"]: r["elapsed_hours"] for r in agg}
    assert by_group["critical"] == 3.0
    assert by_group["warning"] == 1.0
