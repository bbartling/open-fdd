"""Tests for smoke RCx report builder."""

from __future__ import annotations

import json
from pathlib import Path

from open_fdd.validation.smoke_rcx_report import build_smoke_validation_context


def test_build_smoke_validation_context():
    smoke = {
        "mode": "short",
        "pass": True,
        "issues": [],
        "bench": {
            "snapshots": [
                {
                    "bench_batch": {
                        "flagged": {
                            "smoke-paired-zn-t-bacnet-arrow": 2,
                            "smoke-paired-zn-t-bacnet-sql": 2,
                        }
                    }
                }
            ]
        },
    }
    health = [
        {
            "pass": True,
            "probes": [
                {
                    "name": "bacnet_override_scan",
                    "ok": True,
                    "data": {"status": {"scan_interval_s": 3600, "device_count": 2}},
                }
            ],
        }
    ]
    ctx = build_smoke_validation_context(smoke_json=smoke, health_history=health)
    assert ctx["mode"] == "short"
    assert ctx["override_scan_ok"] is True
    assert "smoke-paired-zn-t-bacnet-arrow" in ctx["last_flagged"]


def test_rcx_docx_smoke_section_renders(tmp_path: Path):
    from open_fdd.reports.rcx_docx import build_rcx_docx

    ctx = build_smoke_validation_context(
        smoke_json={"mode": "short", "pass": True, "issues": [], "bench": {"snapshots": []}},
        health_history=[],
    )
    blob = build_rcx_docx(
        site_id="demo",
        site_name="Bench",
        window={"start": "2026-06-01T00:00:00Z", "end": "2026-06-02T00:00:00Z"},
        fault_rows=[],
        sections=["smoke_validation"],
        report_context={"smoke_validation": ctx},
    )
    assert len(blob) > 5000
