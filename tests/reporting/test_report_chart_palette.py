"""Permanent lock: Engineering Findings report bars use React RAINBOW_PALETTE."""

from __future__ import annotations

from open_fdd.analytics.charts import RAINBOW_PALETTE
from open_fdd.reporting import charts as rc
from open_fdd.reporting.models import ReportArtifacts


def _artifacts_with_candidates(n: int = 3) -> ReportArtifacts:
    cands = [
        {
            "equipment_id": f"AHU_{i}",
            "rule_id": f"FC{i}",
            "equipment_type": "AHU",
            "fault_hours": float(100 - 10 * i),
        }
        for i in range(1, n + 1)
    ]
    comfort = [
        {
            "equipment_id": f"VAV_{i}",
            "in_band_pct": float(40 + 5 * i),
            "flag_dead_sensor": False,
        }
        for i in range(1, n + 1)
    ]
    return ReportArtifacts(
        building="TEST",
        analysis_period="2026",
        generated_at="2026-09-22T00:00:00Z",
        findings=[],
        suppressed=[],
        candidates=cands,
        assessments=[],
        data_quality=[],
        comfort_summary={"rows": comfort},
        metrics={},
        field_checklist=[],
        assumptions={},
        quality_gate={},
    )


def _marker_colors(fig) -> list[str]:
    raw = fig.data[0].marker.color
    if isinstance(raw, str):
        return [raw]
    return [str(c) for c in list(raw)]


def test_report_chrome_bars_use_rainbow_palette(monkeypatch) -> None:
    """top_detections + comfort_ranking must cycle RAINBOW_PALETTE (not fixed blue/orange)."""
    captured: dict = {}

    def _capture(fig, name, out_dir):
        captured[name] = fig
        return {"name": name, "path": None}

    monkeypatch.setattr(rc, "_export", _capture)
    arts = _artifacts_with_candidates(3)
    rc.build_report_charts(arts, out_dir=None)

    top_colors = _marker_colors(captured["top_detections"])
    # Horizontal reverse: rank-0 (highest hours) is last in the color list.
    assert top_colors[-1] == RAINBOW_PALETTE[0]
    assert top_colors[-2] == RAINBOW_PALETTE[1]
    assert top_colors[-3] == RAINBOW_PALETTE[2]
    assert "#2b6cb0" not in top_colors

    comfort_colors = _marker_colors(captured["comfort_ranking"])
    assert comfort_colors[-1] == RAINBOW_PALETTE[0]
    assert "#c05621" not in comfort_colors
    assert "#2c5282" not in _marker_colors(captured["confidence_summary"])
