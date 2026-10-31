#!/usr/bin/env python3
"""Emit SQL-QUAL C3a machine-readable matrix (SQL-QUAL-01..06)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.qualification.c3a.sql_qual_harness import build_matrix, write_matrix  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--matrix-out",
        type=Path,
        default=Path("reports/sql_qual_c3a_matrix.json"),
        help="Write machine-readable matrix JSON",
    )
    args = ap.parse_args()
    doc = write_matrix(args.matrix_out.resolve(), REPO)
    hydrated = doc.get("db_hydrated")
    print(f"SQL-QUAL C3a matrix written to {args.matrix_out}")
    print(f"SQL-QUAL C3a DB hydrated={hydrated}")
    for check_id, row in sorted(doc.get("summary", {}).items()):
        print(
            f"{check_id} status={row.get('status')} checks={row.get('checks')} "
            f"comparisons={row.get('comparisons')} errors={len(row.get('errors') or [])}"
        )
    failing = [k for k, v in doc.get("summary", {}).items() if v.get("status") == "FAIL"]
    blocked = [k for k, v in doc.get("summary", {}).items() if v.get("status") == "BLOCKED"]
    if failing:
        return 1
    if blocked and not hydrated:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
