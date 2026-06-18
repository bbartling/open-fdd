"""Tests for programmatic RCx intent API."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

REPO = Path(__file__).resolve().parents[2]


def _bench_tree() -> dict:
    model = json.loads((REPO / "workspace" / "data" / "bench_dual_source_model.json").read_text(encoding="utf-8"))
    return {"equipment": model.get("equipment") or [], "points": model.get("points") or []}


def test_resolve_sensor_columns_bench_model():
    from openfdd_bridge.rcx.rcx_intent import resolve_sensor_columns
    from openfdd_bridge.model_service import ModelService
    from openfdd_bridge.ttl_service import TtlService

    model_path = REPO / "workspace" / "data" / "bench_dual_source_model.json"
    if not model_path.is_file():
        pytest.skip("bench model missing")
    svc = ModelService()
    svc.import_json(json.loads(model_path.read_text(encoding="utf-8")), replace=True)
    TtlService().sync()

    with patch("openfdd_bridge.rcx.rcx_points.query_model_tree", return_value=_bench_tree()):
        out = resolve_sensor_columns("demo", ["OA-T", "stat_zn-t", "DUCT-T", "OA-H"])
    cols = out.get("columns") or []
    assert "oa-t" in cols
    assert len(out.get("unresolved") or []) <= 1


@patch("openfdd_bridge.rcx.chart_preview.query_model_tree", return_value=_bench_tree())
@patch("openfdd_bridge.rcx.rcx_points.query_model_tree", return_value=_bench_tree())
@patch("openfdd_bridge.rcx.chart_preview.build_mechanical_narrative")
@patch("openfdd_bridge.rcx.chart_preview.build_mechanical_summary")
@patch("openfdd_bridge.rcx.chart_preview.build_fault_analytics")
@patch("openfdd_bridge.rcx.chart_preview.build_overview")
@patch("openfdd_bridge.rcx.chart_preview.run_fdd_preset")
def test_rcx_intent_preview_endpoint(
    mock_preset,
    mock_overview,
    mock_faults,
    mock_mech_sum,
    mock_mech_narr,
    _tree_pts,
    _tree_preview,
    client,
):
    mock_mech_narr.return_value = {"narrative": "Bench", "counts": {}}
    mock_mech_sum.return_value = {"warnings": []}
    mock_overview.return_value = {"kpis": {"total_fault_hours": 0}, "faults_by_severity": []}
    mock_faults.return_value = {"faults": [], "fault_count_by_severity": []}
    mock_preset.return_value = {"rows": [], "columns": []}
    resp = client.post(
        "/api/reports/rcx/intent/preview",
        json={
            "site_id": "demo",
            "hours": 168,
            "sensors": ["oa-t", "stat_zn-t"],
            "show_fault_overlays": True,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "charts" in body
    assert "sections" in body
    assert body.get("sensors", {}).get("columns")


@patch("openfdd_bridge.rcx.chart_preview.query_model_tree", return_value=_bench_tree())
@patch("openfdd_bridge.rcx.rcx_points.query_model_tree", return_value=_bench_tree())
@patch("openfdd_bridge.rcx.chart_preview.build_mechanical_narrative")
@patch("openfdd_bridge.rcx.chart_preview.build_mechanical_summary")
@patch("openfdd_bridge.rcx.chart_preview.build_fault_analytics")
@patch("openfdd_bridge.rcx.chart_preview.build_overview")
@patch("openfdd_bridge.rcx.chart_preview.run_fdd_preset")
@patch("openfdd_bridge.rcx.chart_preview.read_chart_readings_with_plot_fallback")
def test_rcx_generate_intent_json(
    mock_readings,
    mock_preset,
    mock_overview,
    mock_faults,
    mock_mech_sum,
    mock_mech_narr,
    _tree_pts,
    _tree_preview,
    client,
):
    mock_mech_narr.return_value = {"narrative": "Bench", "counts": {}}
    mock_mech_sum.return_value = {"warnings": []}
    mock_overview.return_value = {"kpis": {"total_fault_hours": 0}, "faults_by_severity": []}
    mock_faults.return_value = {"faults": [], "fault_count_by_severity": []}
    mock_preset.return_value = {"rows": [], "columns": []}
    mock_readings.return_value = {
        "timestamps": ["2026-06-01T00:00:00Z", "2026-06-01T01:00:00Z"],
        "series": {"oa-t": [70.0, 71.0]},
        "labels": {"oa-t": "OA-T"},
        "row_count": 2,
    }
    resp = client.post(
        "/api/reports/rcx/generate-intent",
        json={
            "site_id": "demo",
            "hours": 168,
            "sensors": ["oa-t"],
            "show_fault_overlays": True,
            "save_to_volume": True,
        },
    )
    if resp.status_code == 503:
        pytest.skip("python-docx not installed")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("ok") is True
    assert body.get("filename", "").endswith(".docx")
    assert body.get("download_path", "").startswith("/api/reports/rcx/download/")
