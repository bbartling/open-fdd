"""Tests for RCx trend statistics."""

from __future__ import annotations

from portfolio.central.rcx_stats import summarize_readings


def test_summarize_readings_fault_hours_and_bullets():
    readings = {
        "timestamps": [
            "2026-01-01T00:00:00Z",
            "2026-01-01T01:00:00Z",
            "2026-01-01T02:00:00Z",
        ],
        "series": {"dsp": [1.0, 1.2, 1.1]},
        "labels": {"dsp": "Duct static"},
        "fault_plots": {"fc1": [0, 1, 1]},
        "row_count": 3,
    }
    out = summarize_readings(readings, chart_id="ahu_dsp", title="AHU duct static")
    assert out["total_hours"] == 2.0
    assert out["fault_hours"] == 1.0
    assert out["fault_percent"] == 50.0
    assert out["stats_bullets"]
    assert "Duct static" in out["series_stats"]
