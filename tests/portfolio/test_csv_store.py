"""Tests for central portfolio CSV append logic."""

from __future__ import annotations

from pathlib import Path

from portfolio.store.csv_store import append_rollup, rows_from_rollup


def test_rows_from_rollup_and_append(tmp_path: Path):
    rollup = {
        "site_id": "acme",
        "building": {"traffic": "green", "status": "ok", "alert_count": 0, "fdd_alert_count": 1},
        "faults": {"active_by_code": {"AHU-SF-OFF-HRS": 1}, "active_count": 1},
        "fdd_batch": {"flagged_samples_by_code": {"AHU-SF-OFF-HRS": 5}},
        "runtime_metrics": {
            "ahu-01": {
                "equipment_name": "AHU-01",
                "fan_run_hours": 10.0,
                "system_run_hours": 6.0,
            }
        },
        "overrides": {
            "operator_override_points": 1,
            "points": [
                {
                    "device_instance": 1,
                    "object_identifier": "analog-value,1",
                    "object_name": "SAT-SP",
                    "priority_level": 8,
                    "value": 55,
                }
            ],
        },
        "agent": {"last_checkin_ok": True},
        "poll": {"summary_sentence": "steady"},
    }
    rows = rows_from_rollup(rollup, site_name="Acme", base_url="http://127.0.0.1:8765")
    assert len(rows["checkins"]) == 1
    assert rows["checkins"][0]["operator_overrides"] == 1
    assert len(rows["run_hours"]) == 1
    assert len(rows["faults"]) == 1
    assert len(rows["overrides"]) == 1

    counts = append_rollup(rollup, site_name="Acme", base_url="http://127.0.0.1:8765", data_dir=tmp_path)
    assert counts["checkins"] == 1
    csv_path = tmp_path / "data" / "checkins.csv"
    assert csv_path.is_file()
    text = csv_path.read_text(encoding="utf-8")
    assert "acme" in text
    assert "Acme" in text
