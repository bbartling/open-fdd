"""Offline tests for RCx chart preview and fault overlays."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from portfolio.central.trend_charts import fault_overlay_spans, overlays_from_readings


def test_fault_overlay_spans_contiguous():
    ts = ["2026-01-01T00:00:00Z", "2026-01-01T01:00:00Z", "2026-01-01T02:00:00Z", "2026-01-01T03:00:00Z"]
    flags = [0, 1, 1, 0]
    spans = fault_overlay_spans(ts, flags, label="SAT flatline", severity="warning")
    assert len(spans) == 1
    assert spans[0]["label"] == "SAT flatline"


def test_overlays_from_readings():
    readings = {
        "timestamps": ["2026-01-01T00:00:00Z", "2026-01-01T01:00:00Z"],
        "fault_plots": {"rule-1": [1, 0]},
        "fault_panels": [{"key": "rule-1", "title": "AHU SAT"}],
    }
    ovs = overlays_from_readings(readings)
    assert ovs


@pytest.mark.skipif(
    __import__("importlib").util.find_spec("matplotlib") is None,
    reason="matplotlib not installed",
)
@patch("portfolio.central.chart_preview.build_mechanical_narrative")
@patch("portfolio.central.chart_preview.build_mechanical_summary")
@patch("portfolio.central.chart_preview.resolve_token", return_value="tok")
@patch("portfolio.central.chart_preview.resolve_site_config")
@patch("portfolio.central.chart_preview.EdgeClient")
def test_build_rcx_preview_fault_bars(mock_client_cls, mock_site, _tok, mock_mech, mock_narr):
    mock_site.return_value = MagicMock(name="ACME", base_url="http://edge.test")
    mock_mech.return_value = {"warnings": [], "model_issues": []}
    mock_narr.return_value = {"narrative": "Test narrative", "counts": {"ahu": 1, "vav": 30}}
    client = mock_client_cls.return_value
    client.get_model_tree.return_value = {"points": []}
    client.get_analytics_overview.return_value = {
        "kpis": {"active_faults": 2, "total_fault_hours": 5.0},
        "faults_by_severity": [{"group": "warning", "elapsed_hours": 3}],
        "fault_hours_by_equipment": [{"group": "AHU-C", "elapsed_hours": 2}],
    }
    client.get_analytics_faults.return_value = {
        "faults": [{"fault_name": "SAT", "severity": "warning", "equipment": "AHU-C"}]
    }
    client.get_fdd_query_preset.return_value = {"rows": [], "columns": []}

    from portfolio.central.chart_preview import build_rcx_preview

    out = build_rcx_preview(site_id="acme", hours=24)
    assert out["fault_summary"]["active_faults"] == 1
    assert len(out["chart_previews"]) >= 1
    assert out["chart_previews"][0]["image_base64"]
