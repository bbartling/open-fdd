"""Tests for RCx AI analyst assessment."""

from __future__ import annotations

from unittest.mock import patch

import pytest


def test_build_override_commentary_empty():
    from openfdd_bridge.rcx.rcx_ai_insights import build_override_commentary

    lines = build_override_commentary({"override_count": 0, "overrides": []})
    assert len(lines) == 1
    assert "No active BACnet" in lines[0]


def test_build_override_commentary_p8_and_other():
    from openfdd_bridge.rcx.rcx_ai_insights import build_override_commentary

    lines = build_override_commentary(
        {
            "operator_priority": 8,
            "override_count": 3,
            "overrides": [
                {"device": 5007, "point": "SAT-SP", "operator_p8": True, "priority": 8},
                {"device": 5007, "point": "OA-DMP", "operator_p8": False, "priority": 11},
            ],
        }
    )
    text = " ".join(lines)
    assert "operator" in text.lower() or "P8" in text
    assert "5007" in text or "SAT-SP" in text


def test_build_rule_assessments_flags_gaps():
    from openfdd_bridge.rcx.rcx_ai_insights import build_rule_assessments

    rules = [
        {"rule_name": "Zone comfort", "fault_code": "VAV-C", "sensors": [{"column": "zn-t"}]},
        {"rule_name": "Unbound", "fault_code": "AHU-A", "sensors": []},
    ]
    lines = build_rule_assessments(rules, [], mech={"counts": {"ahu": 2, "vav": 0}})
    text = " ".join(lines)
    assert "binding" in text.lower()
    assert "Unbound" in text


def test_build_fallback_insights_includes_chart_narrative():
    from openfdd_bridge.rcx.rcx_ai_insights import build_fallback_insights

    out = build_fallback_insights(
        site_name="Demo Lab",
        window={"hours": 168, "start": "2026-06-01", "end": "2026-06-08"},
        fault_rows=[{"fault_code": "SAT-FLAT", "equipment": "AHU-1", "elapsed_hours": 2}],
        overview={"active_faults": 1, "total_fault_hours": 2},
        chart_previews=[
            {
                "chart_id": "ahu_sat_vs_setpoint",
                "title": "SAT vs setpoint",
                "stats": {
                    "fault_percent": 6.5,
                    "fault_hours": 10,
                    "total_hours": 168,
                    "stats_bullets": ["Dataset span: 7 day(s)"],
                },
            }
        ],
        report_context={"assigned_rules": [], "motor_runtime": [], "overrides": {"override_count": 0, "overrides": []}},
        mechanical_summary={"narrative": "Single AHU lab.", "counts": {"ahu": 1, "vav": 2, "zones": 4}},
    )
    assert out["source"] == "deterministic"
    assert out["paragraphs"]
    assert any("Demo Lab" in p for p in out["paragraphs"])
    assert out["chart_insights"]
    joined = " ".join(out["paragraphs"])
    assert "5%" in joined or "fault" in joined.lower()


@patch("openfdd_bridge.rcx.rcx_ai_insights.ollama_client.should_use_ollama_for_insight", return_value=False)
def test_generate_rcx_ai_insights_uses_fallback_when_ollama_disabled(_mock):
    from openfdd_bridge.rcx.rcx_ai_insights import generate_rcx_ai_insights

    out = generate_rcx_ai_insights(
        site_id="demo",
        site_name="Demo",
        window={"hours": 24},
        fault_rows=[],
        overview={"active_faults": 0},
        chart_previews=[],
        report_context={"assigned_rules": [], "motor_runtime": [], "overrides": {}},
        mechanical_summary={"counts": {"ahu": 1}},
    )
    assert out["source"] == "deterministic"
    assert out["paragraphs"]


def test_docx_contains_ai_section():
    pytest.importorskip("docx")
    from docx import Document
    import io
    from open_fdd.reports.rcx_docx import build_rcx_docx

    blob = build_rcx_docx(
        site_id="demo",
        site_name="Demo",
        window={"start": "a", "end": "b"},
        fault_rows=[],
        sections=["analyst_insights"],
        ai_insights={
            "source": "deterministic",
            "paragraphs": ["HVAC health looks nominal in this window."],
            "rule_assessments": ["All rules bound."],
            "override_notes": ["No overrides."],
        },
    )
    text = "\n".join(p.text for p in Document(io.BytesIO(blob)).paragraphs)
    assert "AI analyst assessment" in text
    assert "HVAC health looks nominal" in text
