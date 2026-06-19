#!/usr/bin/env python3
"""Generate RCx DOCX from completed half-hour bench 5007 smoke artifacts."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "workspace" / "api"))

from open_fdd.validation.smoke_rcx_report import generate_smoke_rcx_docx  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reports-dir", type=Path, default=REPO / "workspace" / "reports" / "artifacts")
    parser.add_argument("--site-id", default="demo")
    parser.add_argument("--site-name", default="Bench Demo Site")
    parser.add_argument("--hours", type=int, default=24)
    args = parser.parse_args()

    blob, out = generate_smoke_rcx_docx(
        reports_dir=args.reports_dir,
        site_id=args.site_id,
        site_name=args.site_name,
        hours=args.hours,
    )
    out.write_bytes(blob)
    if len(blob) < 10_000:
        print(f"WARN: DOCX small ({len(blob)} bytes)", file=sys.stderr)
    print(f"OK — {out} ({len(blob)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
