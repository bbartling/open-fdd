"""Tests for RCx report persistence on edge."""

from __future__ import annotations

from openfdd_bridge.rcx.report_store import delete_report, list_reports, resolve_report, save_report


def test_report_store_roundtrip(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    ws.mkdir(exist_ok=True)
    monkeypatch.setenv("OPENFDD_WORKSPACE_DIR", str(ws))
    path = save_report("openfdd-rcx-test.docx", b"PK\x03\x04demo")
    assert path.is_file()
    assert "reports" in str(path)
    assert path.parent.name == "rcx"
    rows = list_reports()
    assert rows[0]["filename"] == "openfdd-rcx-test.docx"
    assert rows[0]["download_path"].endswith("openfdd-rcx-test.docx")
    loaded = resolve_report("openfdd-rcx-test.docx")
    assert loaded.read_bytes() == b"PK\x03\x04demo"


def test_delete_report(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    ws.mkdir(exist_ok=True)
    monkeypatch.setenv("OPENFDD_WORKSPACE_DIR", str(ws))
    save_report("to-delete.docx", b"PK")
    delete_report("to-delete.docx")
    assert list_reports() == []
