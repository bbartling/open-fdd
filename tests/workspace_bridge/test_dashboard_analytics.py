"""Tests for dashboard analytics API and RCx report generation."""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from open_fdd.reports.fault_hours import (
    aggregate_fault_hours,
    fault_hours_from_fdd_runs,
)

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "tests" / "fixtures" / "demo_fdd_results.json"


def test_fault_hours_from_fdd_runs_simple():
    runs = [
        {
            "site_id": "acme",
            "equipment_name": "AHU-C",
            "equipment_family": "AHU",
            "fault_code": "SAT-FLAT",
            "rule_name": "AHU SAT flatline 1h",
            "severity": "warning",
            "flagged": 4,
            "rows": 24,
            "analytics": {
                "fault_samples": 4,
                "total_samples": 24,
                "estimated_fault_duration_sec": 3600,
            },
        }
    ]
    rows = fault_hours_from_fdd_runs(runs)
    assert len(rows) == 1
    assert rows[0]["equipment"] == "AHU-C"
    assert rows[0]["elapsed_hours"] == 1.0


def test_aggregate_fault_hours_by_equipment():
    rows = [
        {"equipment": "AHU-C", "elapsed_hours": 2.0, "severity": "warning"},
        {"equipment": "AHU-C", "elapsed_hours": 1.5, "severity": "warning"},
        {"equipment": "VAV-1", "elapsed_hours": 0.5, "severity": "warning"},
    ]
    agg = aggregate_fault_hours(rows, group_by="equipment")
    assert agg[0]["group"] == "AHU-C"
    assert agg[0]["elapsed_hours"] == 3.5


def test_rcx_docx_contains_sections_and_chart():
    pytest.importorskip("docx")
    from open_fdd.reports.rcx_docx import build_rcx_docx

    fault_rows = [
        {
            "equipment": "AHU-C",
            "equipment_type": "AHU",
            "fault_code": "SAT-FLAT",
            "fault_name": "AHU SAT flatline",
            "severity": "warning",
            "elapsed_hours": 2.5,
            "samples_flagged": 4,
            "samples_evaluated": 24,
        }
    ]
    payload = build_rcx_docx(
        site_id="acme",
        site_name="Acme Lab",
        window={"start": "2026-01-01T00:00:00Z", "end": "2026-01-02T00:00:00Z"},
        fault_rows=fault_rows,
        overview={"active_faults": 1, "total_fault_hours": 2.5},
        sections=["executive_summary", "fault_analytics", "fdd_rule_trends"],
        charts=["fault_hours_by_equipment", "active_faults_table"],
    )
    assert payload[:2] == b"PK"
    from docx import Document

    doc = Document(io.BytesIO(payload))
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "Retro-Commissioning Analytics Report" in text
    assert "AHU-C" in text
    assert "FDD rule trend screenshots" in text


def test_analytics_overview_endpoint(raw_client):
    resp = raw_client.get("/api/analytics/overview")
    assert resp.status_code == 200
    body = resp.json()
    assert "kpis" in body
    assert "top_faults" in body


def test_analytics_faults_endpoint(raw_client):
    resp = raw_client.get("/api/analytics/faults?hours=24")
    assert resp.status_code == 200
    assert "faults" in resp.json()


def test_rcx_preview_endpoint(client):
    resp = client.post(
        "/api/reports/rcx/preview",
        json={"hours": 24, "catalog_only": True, "include_previews": False},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "available_charts" in body
    assert "sections" in body


def test_rcx_generate_mime(client):
    resp = client.post(
        "/api/reports/rcx/generate",
        json={"hours": 24, "sections": ["executive_summary"], "charts": []},
    )
    if resp.status_code == 503:
        pytest.skip("python-docx not installed")
    assert resp.status_code == 200
    assert (
        resp.headers.get("content-type")
        == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert resp.content[:2] == b"PK"
    assert resp.headers.get("X-OpenFDD-Saved-Filename", "").endswith(".docx")


def test_rcx_report_list_and_delete(client, tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    ws.mkdir(exist_ok=True)
    monkeypatch.setenv("OPENFDD_WORKSPACE_DIR", str(ws))
    from openfdd_bridge.rcx.report_store import save_report

    save_report("api-roundtrip.docx", b"PKtest")
    listed = client.get("/api/reports/rcx/list")
    assert listed.status_code == 200
    names = [r["filename"] for r in listed.json().get("reports") or []]
    assert "api-roundtrip.docx" in names
    deleted = client.delete("/api/reports/rcx/api-roundtrip.docx")
    assert deleted.status_code == 200
    assert client.get("/api/reports/rcx/list").json().get("count") == 0


@pytest.fixture
def demo_fdd_results(tmp_path, monkeypatch):
    if not FIXTURE.is_file():
        pytest.skip("demo fixture missing")
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "fdd_results.json").write_text(FIXTURE.read_text(), encoding="utf-8")
    monkeypatch.setenv("OFDD_DESKTOP_DATA_DIR", str(data_dir))
