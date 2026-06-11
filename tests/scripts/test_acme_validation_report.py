"""Offline tests for Acme validation report schema."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET

from scripts.acme_validation_report import (
    ValidationCheck,
    ValidationReport,
    redact_report,
    redact_text,
    write_junit_report,
    write_json_report,
)


def test_report_summary_ok_when_no_failures(tmp_path):
    report = ValidationReport(target={"site_id": "acme"}, started_at="2026-01-01T00:00:00Z")
    report.add(ValidationCheck(id="a", category="api", status="pass", message="ok"))
    report.add(ValidationCheck(id="b", category="api", status="warn", message="slow"))
    report.finalize()
    assert report.summary["ok"] is True
    assert report.summary["passed"] == 1
    assert report.summary["warnings"] == 1


def test_report_fails_when_check_fails():
    report = ValidationReport(target={}, started_at="t")
    report.add(ValidationCheck(id="dup", category="model", status="fail", message="duplicate devices"))
    report.finalize()
    assert report.summary["ok"] is False
    assert report.summary["failed"] == 1


def test_redact_token_and_tailscale():
    text = redact_text('Bearer abc.def-123 at http://100.122.106.124/api')
    assert "REDACTED" in text
    assert "100.122" not in text
    data = redact_report({"token": "secret", "base_url": "http://100.1.2.3", "nested": {"password": "x"}})
    assert data["token"] == "[REDACTED]"
    assert data["base_url"] == "redacted"


def test_json_and_junit_output(tmp_path):
    report = ValidationReport(target={"site_id": "acme"}, started_at="t", duration_seconds=1.5)
    report.add(ValidationCheck(id="health", category="api", status="pass", message="OK", duration_ms=10))
    report.add(ValidationCheck(id="dup", category="model", status="fail", message="duplicate", duration_ms=5))
    report.finalize()
    jp = tmp_path / "r.json"
    write_json_report(report, str(jp))
    loaded = json.loads(jp.read_text(encoding="utf-8"))
    assert loaded["summary"]["failed"] == 1
    assert loaded["checks"][0]["id"] == "health"
    junit = tmp_path / "r.xml"
    write_junit_report(report, str(junit))
    root = ET.parse(junit).getroot()
    assert root.tag == "testsuite"
    assert int(root.attrib["failures"]) == 1
