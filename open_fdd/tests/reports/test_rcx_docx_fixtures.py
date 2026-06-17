"""Fixture-driven RCx DOCX report validation."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
FIXTURE_DIR = REPO / "tests" / "fixtures" / "rcx"


@pytest.fixture
def fault_rows():
    return json.loads((FIXTURE_DIR / "fault_rows.json").read_text(encoding="utf-8"))


@pytest.fixture
def report_context():
    return json.loads((FIXTURE_DIR / "report_context.json").read_text(encoding="utf-8"))


def test_rcx_docx_fixture_sections(fault_rows, report_context):
    pytest.importorskip("docx")
    from docx import Document
    from open_fdd.reports.rcx_docx import DEFAULT_SECTIONS, build_rcx_docx

    blob = build_rcx_docx(
        site_id="acme",
        site_name="Acme Lab Building",
        window={"start": "2026-01-01T00:00:00Z", "end": "2026-01-02T00:00:00Z"},
        fault_rows=fault_rows,
        overview={"active_faults": 2, "total_fault_hours": 4.5},
        sections=DEFAULT_SECTIONS,
        report_context=report_context,
        equipment_bundle={"bundle_id": "ahu-c", "label": "AHU-C"},
    )
    doc = Document(io.BytesIO(blob))
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "Acme Lab Building" in text
    assert "Site ID: acme" in text
    assert "AHU-C" in text
    assert "Retro-Commissioning" in text
    assert "Runtime analytics" in text
    assert "Recommendations" in text
    assert "None" not in text.split("Building:")[0]
    assert "Traceback" not in text


def test_rcx_docx_active_fault_table(fault_rows):
    pytest.importorskip("docx")
    from docx import Document
    from open_fdd.reports.rcx_docx import build_rcx_docx

    blob = build_rcx_docx(
        site_id="demo",
        site_name="Demo Site",
        window={"start": "2026-01-01", "end": "2026-01-02"},
        fault_rows=fault_rows,
        sections=["executive_summary", "fault_analytics", "appendix_faults"],
    )
    doc = Document(io.BytesIO(blob))
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "SAT-FLAT" in text or "flatline" in text.lower()
