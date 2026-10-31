"""Run C3b SQL-QUAL-07..10 + 19 analytics matrix and write JSON evidence."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.qualification.c3b_sqlqual import (  # noqa: E402
    qual_07_units,
    qual_08_timelines,
    qual_09_mode_delay,
    qual_10_duration_buckets,
    qual_19_analytics_fresh,
)
from scripts.qualification.c3b_sqlqual.matrix import (  # noqa: E402
    SCHEMA,
    QualCell,
    QualMatrix,
    component_from_cells,
)


def _git_head() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()


def run_matrix(*, db_url: str | None, matrix_path: Path) -> QualMatrix:
    db_hydrated = bool(db_url and db_url.strip())
    conn = None
    if db_hydrated:
        from scripts.stress.si_cutover import ci_timescale_sql as cts

        parity = cts._load_parity_module()
        conn = parity.connect_with_retry(db_url.strip())
        cts.apply_fdd_postgres_helpers(conn)

    components = []
    errors: list[str] = []

    try:
        c07 = qual_07_units.run_offline()
        if conn is not None:
            c07.extend(qual_07_units.run_postgres(conn))
        components.append(
            component_from_cells(
                "SQL-QUAL-07",
                phase="C3",
                cells=c07,
                c5_pending=("writer/API SI readback on owner stack after cutover",),
            )
        )

        c08 = qual_08_timelines.run_offline()
        if conn is not None:
            c08.extend(qual_08_timelines.run_postgres(conn))
        components.append(
            component_from_cells(
                "SQL-QUAL-08",
                phase="C3",
                cells=c08,
                c5_pending=("async web/local cadence REST parity",),
            )
        )

        c09 = qual_09_mode_delay.run_offline()
        if conn is not None:
            c09.extend(qual_09_mode_delay.run_postgres(conn))
        components.append(
            component_from_cells(
                "SQL-QUAL-09",
                phase="C3",
                cells=c09,
                c5_pending=("catalog/render/API parameter mapping on owner stack",),
            )
        )

        c10 = qual_10_duration_buckets.run_offline()
        if conn is not None:
            c10.extend(qual_10_duration_buckets.run_postgres(conn))
        components.append(
            component_from_cells(
                "SQL-QUAL-10",
                phase="C3",
                cells=c10,
                c5_pending=("REST/session/tuner/cache-generation contracts",),
            )
        )

        c19 = qual_19_analytics_fresh.run_offline()
        if conn is not None:
            c19.extend(qual_19_analytics_fresh.run_postgres(conn))
        else:
            c19.append(
                QualCell(
                    "19_pg_fresh_sql_vs_oracle_all_bodies",
                    "BLOCKED",
                    0,
                    "OPENFDD_DATABASE_URL not set",
                )
            )
        components.append(
            component_from_cells(
                "analytics-19-fresh-pg-oracle",
                phase="C3",
                cells=c19,
                c5_pending=("API/UI analytics binding",),
            )
        )
    finally:
        if conn is not None:
            conn.close()

    for comp in components:
        if comp.status == "FAIL":
            errors.append(f"{comp.id} failed")
        for cell in comp.cells:
            if cell.status == "FAIL":
                errors.append(f"{cell.check_id}: {cell.detail[:200]}")

    matrix = QualMatrix(
        schema=SCHEMA,
        candidate_rev=_git_head(),
        db_hydrated=db_hydrated,
        components=components,
        errors=tuple(errors),
    )
    matrix.write_json(matrix_path)
    return matrix


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--matrix-out",
        type=Path,
        default=Path(os.environ.get("C3B_SQLQUAL_MATRIX_PATH", "reports/c3b_sqlqual_matrix.json")),
        help="Machine-readable matrix JSON path",
    )
    parser.add_argument(
        "--require-db",
        action="store_true",
        help="Fail when OPENFDD_DATABASE_URL is unset (CI)",
    )
    args = parser.parse_args(argv)
    db_url = os.environ.get("OPENFDD_DATABASE_URL", "").strip() or os.environ.get(
        "OPENFDD_TEST_DATABASE_URL", ""
    ).strip()
    if args.require_db and not db_url:
        print("OPENFDD_DATABASE_URL required for C3b DB-backed checks", file=sys.stderr)
        return 2
    matrix = run_matrix(db_url=db_url or None, matrix_path=args.matrix_out)
    db_comparisons = sum(
        c.comparisons
        for comp in matrix.components
        for c in comp.cells
        if c.check_id.startswith(("07_pg", "08_pg", "09_pg", "10_pg", "19_pg"))
    )
    print(
        f"C3b DB-backed checks: hydrated={matrix.db_hydrated} "
        f"db_comparisons={db_comparisons} matrix={args.matrix_out}"
    )
    failed = [comp.id for comp in matrix.components if comp.status == "FAIL"]
    if failed:
        print(f"C3b matrix FAIL components: {', '.join(failed)}", file=sys.stderr)
        return 1
    if args.require_db and not matrix.db_hydrated:
        print("C3b require-db but matrix not hydrated", file=sys.stderr)
        return 2
    if args.require_db and db_comparisons <= 0:
        print("C3b require-db but zero db comparisons", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
