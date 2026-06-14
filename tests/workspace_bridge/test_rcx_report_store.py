"""Tests for RCx report persistence on edge."""

from __future__ import annotations

from openfdd_bridge.rcx.report_store import list_reports, resolve_report, save_report


def test_report_store_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("OFDD_DESKTOP_DATA_DIR", str(tmp_path))
    path = save_report("openfdd-rcx-test.docx", b"PK\x03\x04demo")
    assert path.is_file()
    rows = list_reports()
    assert rows[0]["filename"] == "openfdd-rcx-test.docx"
    loaded = resolve_report("openfdd-rcx-test.docx")
    assert loaded.read_bytes() == b"PK\x03\x04demo"
