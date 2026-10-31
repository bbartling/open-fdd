#!/usr/bin/env python3
"""Run C3c SQL-QUAL-11 + 12A disposable Postgres qualification and emit a matrix JSON."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.qualification.c3c_sqlqual_11 import run_sql_qual_11  # noqa: E402
from scripts.qualification.c3c_sqlqual_12a import run_sql_qual_12a  # noqa: E402
from scripts.qualification.c3c_sqlqual_matrix import CheckCell, new_matrix, sha256_paths  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=os.environ.get("OPENFDD_TEST_DATABASE_URL", "").strip()
        or os.environ.get("OPENFDD_DATABASE_URL", "").strip(),
    )
    parser.add_argument(
        "--json-out",
        default="",
        help="Matrix output path (default: reports/c3c/sqlqual-matrix-<sha>.json)",
    )
    parser.add_argument(
        "--ci-quick",
        action="store_true",
        help="Smaller OAT-METEO size grid for CI time budget",
    )
    parser.add_argument(
        "--multi-equipment",
        type=int,
        default=2,
        help="Bounded multi-equipment concurrency case (SQL-QUAL-11)",
    )
    parser.add_argument(
        "--run-rust-cutover",
        action="store_true",
        help="Also run cargo test -p openfdd-central t1284_3 (token/dry-run/idempotency)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.database_url:
        print("FAIL: OPENFDD_TEST_DATABASE_URL or --database-url required", file=sys.stderr)
        return 2

    identities = {
        "candidate_git_sha": __import__(
            "scripts.qualification.c3c_sqlqual_matrix", fromlist=["git_head"]
        ).git_head(),
        "rule_sql_sha256": sha256_paths([ROOT / "sql/fdd/postgres/rules/oat_meteo_fault.sql"]),
        "metric_units_sha256": sha256_paths([ROOT / "sql/contract/metric_units.json"]),
        "database_url_host": args.database_url.split("@")[-1],
    }
    matrix = new_matrix(identities=identities)

    print("C3C SQL-QUAL DB bench: hydrating disposable Postgres checks", flush=True)

    cells_11, ev11 = run_sql_qual_11(
        database_url=args.database_url,
        ci_quick=args.ci_quick,
        multi_equipment=args.multi_equipment,
    )
    for raw in cells_11:
        matrix.add(CheckCell(**raw))
    matrix.identities["sql_qual_11"] = ev11

    cells_12, ev12 = run_sql_qual_12a(
        database_url=args.database_url,
        run_rust_cutover=args.run_rust_cutover,
    )
    for raw in cells_12:
        matrix.add(CheckCell(**raw))
    matrix.identities["sql_qual_12a"] = ev12

    out = args.json_out.strip()
    if not out:
        sha = matrix.candidate_git_sha[:7]
        out = str(ROOT / "reports" / "c3c" / f"sqlqual-matrix-{sha}.json")
    matrix.write_json(Path(out))
    print(json.dumps({"matrix_path": out, "summary_by_qual_id": matrix.counts_by_qual()}, indent=2))
    print(f"C3C SQL-QUAL DB bench completed: {out}", flush=True)
    return matrix.exit_code()


if __name__ == "__main__":
    raise SystemExit(main())
