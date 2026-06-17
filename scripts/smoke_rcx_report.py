#!/usr/bin/env python3
"""Smoke RCx report generation from fixture data (no live site required)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

FIXTURE_DIR = REPO / "tests" / "fixtures" / "rcx"
OUT_DIR = REPO / "reports"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site-id", default="acme")
    parser.add_argument("--site-name", default="Acme Lab Building")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    from open_fdd.reports.rcx_docx import DEFAULT_SECTIONS, build_rcx_docx

    fault_rows = json.loads((FIXTURE_DIR / "fault_rows.json").read_text(encoding="utf-8"))
    report_context = json.loads((FIXTURE_DIR / "report_context.json").read_text(encoding="utf-8"))
    blob = build_rcx_docx(
        site_id=args.site_id,
        site_name=args.site_name,
        window={"start": "2026-01-01T00:00:00Z", "end": "2026-01-02T00:00:00Z"},
        fault_rows=fault_rows,
        sections=DEFAULT_SECTIONS,
        report_context=report_context,
        overview={"active_faults": len(fault_rows), "total_fault_hours": 4.5},
        charts=["ahu_sat_vs_setpoint"],
        available_charts=json.loads((FIXTURE_DIR / "chart_catalog.json").read_text(encoding="utf-8"))["available_charts"],
        equipment_charts=json.loads((FIXTURE_DIR / "chart_catalog.json").read_text(encoding="utf-8"))["equipment_charts"],
    )
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = args.out or OUT_DIR / f"rcx_smoke_{args.site_id}.docx"
    out.write_bytes(blob)
    if len(blob) < 10_000:
        raise SystemError(f"DOCX unexpectedly small ({len(blob)} bytes)")
    print(f"OK — wrote {out} ({len(blob)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
