#!/usr/bin/env python3
"""Run C3c SQL-QUAL-11 + 12A disposable Postgres qualification and emit a matrix JSON."""

from __future__ import annotations

import argparse
import json
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.qualification.c3c_sqlqual_11 import run_sql_qual_11  # noqa: E402
from scripts.qualification.c3c_sqlqual_12a import run_sql_qual_12a  # noqa: E402
from scripts.qualification.c3c_sqlqual_matrix import CheckCell, new_matrix, sha256_paths  # noqa: E402

C3C_OFFLINE_TESTS = (
    "tests.qualification.test_c3c_sqlqual_11_12a.C3cMatrixTests.test_matrix_schema_and_pending_rows",
    "tests.qualification.test_c3c_sqlqual_11_12a.C3cMatrixTests.test_ip_golden_baseline_readonly",
    "tests.qualification.test_c3c_libpq.C3cLibpqTests.test_blocked_receipt_shape",
    "tests.qualification.test_c3c_libpq.C3cLibpqTests.test_libpq_env_never_puts_password_in_argv",
)

C3C_FIXTURE_PATHS = [
    ROOT / "tests/fixtures/si_cutover/ip_goldens/COOKBOOK_FC1.json",
    ROOT / "sql/fdd/postgres/rules/oat_meteo_fault.sql",
    ROOT / "sql/contract/metric_units.json",
]


def runner_roster(*, executed: list[str], skipped: list[str]) -> dict[str, object]:
    return {
        "executed_tests": executed,
        "skipped_tests": skipped,
        "fixture_sha256": sha256_paths([p for p in C3C_FIXTURE_PATHS if p.is_file()]),
    }


def discover_c3c_offline_tests() -> tuple[list[str], list[str]]:
    loader = unittest.TestLoader()
    executed: list[str] = []
    skipped: list[str] = []
    for name in C3C_OFFLINE_TESTS:
        try:
            loader.loadTestsFromName(name)
            executed.append(name)
        except Exception as exc:  # noqa: BLE001
            skipped.append(f"{name}: {exc}")
    return executed, skipped


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
        "--checkpoint-out",
        default="",
        help="Optional SQL-QUAL-11 checkpoint path (defaults beside --json-out)",
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


def write_matrix_checkpoint(matrix, path: Path) -> None:
    matrix.write_json_atomic(path)
    receipt = path.with_suffix(path.suffix + ".receipt.json")
    matrix.write_json_atomic(receipt)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.database_url:
        print("FAIL: OPENFDD_TEST_DATABASE_URL or --database-url required", file=sys.stderr)
        return 2

    executed_tests, skipped_tests = discover_c3c_offline_tests()
    roster = runner_roster(executed=executed_tests, skipped=skipped_tests)

    identities = {
        "candidate_git_sha": __import__(
            "scripts.qualification.c3c_sqlqual_matrix", fromlist=["git_head"]
        ).git_head(),
        "rule_sql_sha256": sha256_paths([ROOT / "sql/fdd/postgres/rules/oat_meteo_fault.sql"]),
        "metric_units_sha256": sha256_paths([ROOT / "sql/contract/metric_units.json"]),
        "database_url_host": args.database_url.split("@")[-1],
        "runner_roster": roster,
    }
    matrix = new_matrix(identities=identities)

    print("C3C SQL-QUAL DB bench: hydrating disposable Postgres checks", flush=True)
    print(json.dumps({"runner_roster": roster}, indent=2), flush=True)

    cells_11, ev11 = run_sql_qual_11(
        database_url=args.database_url,
        ci_quick=args.ci_quick,
        multi_equipment=args.multi_equipment,
    )
    for raw in cells_11:
        matrix.add(CheckCell(**raw))
    matrix.identities["sql_qual_11"] = ev11

    out = args.json_out.strip()
    if not out:
        sha = matrix.candidate_git_sha[:7]
        out = str(ROOT / "reports" / "c3c" / f"sqlqual-matrix-{sha}.json")
    out_path = Path(out)
    checkpoint = args.checkpoint_out.strip() or str(out_path.with_suffix(".sql11-checkpoint.json"))
    write_matrix_checkpoint(matrix, Path(checkpoint))
    print(f"C3C SQL-QUAL-11 checkpoint saved: {checkpoint}", flush=True)

    cells_12, ev12 = run_sql_qual_12a(
        database_url=args.database_url,
        run_rust_cutover=args.run_rust_cutover,
    )
    for raw in cells_12:
        matrix.add(CheckCell(**raw))
    matrix.identities["sql_qual_12a"] = ev12

    write_matrix_checkpoint(matrix, out_path)
    print(json.dumps({"matrix_path": str(out_path), "summary_by_qual_id": matrix.counts_by_qual()}, indent=2))
    print(f"C3C SQL-QUAL DB bench completed: {out_path}", flush=True)
    return matrix.exit_code()


if __name__ == "__main__":
    raise SystemExit(main())
