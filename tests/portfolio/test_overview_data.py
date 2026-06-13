"""Tests for RCx Central overview data helpers."""

from __future__ import annotations

from portfolio.central.overview_data import build_overview_from_csv, fault_pie_from_csv


def test_fault_pie_from_csv_acme():
    pie = fault_pie_from_csv("acme")
    assert isinstance(pie, list)
    if pie:
        assert "fault_code" in pie[0]
        assert pie[0]["count"] >= 1


def test_overview_csv_delta():
    out = build_overview_from_csv("acme")
    assert "active_faults" in out
    assert "fault_pct_change" in out
    assert "snapshot" in out.get("data_source", "").lower() or "csv" in out.get("data_source", "").lower()
    assert "csv_snapshot" in out
