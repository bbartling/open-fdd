"""FDD fault analytics — Arrow-native edge path (no pandas in summarizer)."""

from __future__ import annotations

from openfdd_bridge.fdd_fault_analytics import format_fault_detail, summarize_fault_run


def test_summarize_fault_run_bounds_and_avg() -> None:
    rows = [
        {"timestamp": "2026-06-15T10:00:00Z", "temp": 70.0, "value_column": "oa-t"},
        {"timestamp": "2026-06-15T10:01:00Z", "temp": 92.0, "value_column": "oa-t"},
        {"timestamp": "2026-06-15T10:02:00Z", "temp": 68.0, "value_column": "oa-t"},
    ]
    flags = [False, True, True]
    out = summarize_fault_run(rows, flags, config={"bounds_low": 50, "bounds_high": 85})
    assert out["fault_samples"] == 2
    assert out["total_samples"] == 3
    assert out["avg_value_fault"] == 80.0
    assert out["bounds_low"] == 50.0
    assert out["bounds_high"] == 85.0
    assert "estimated_fault_duration_label" in out


def test_format_fault_detail() -> None:
    text = format_fault_detail(
        {
            "fault_samples": 2,
            "total_samples": 10,
            "avg_value_fault": 91.0,
            "value_unit": "°F",
            "bounds_low": 50,
            "bounds_high": 85,
            "value_columns": ["oa-t"],
        },
        source="demo",
    )
    assert "91" in text
    assert "oa-t" in text
