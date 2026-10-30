"""Read-only in-memory probes; exit 1 means verifier gaps were reproduced.

Run with the repository's existing oracle Python environment and --repo PATH.
Does not connect to PostgreSQL, access credentials or modify repository files.
This is diagnostic evidence, not a passing product qualification suite.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from unittest import mock


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", type=Path, required=True)
    args = ap.parse_args()
    sys.path.insert(0, str(args.repo.resolve()))
    from scripts.stress.si_cutover import baseline_io as bio
    from scripts.stress.si_cutover import ci_fixtures_lib as cfl
    from scripts.stress.si_cutover import ci_timescale_sql as cts
    from scripts.stress.si_cutover import parity_chain as pc
    import pandas as pd

    site = "QA_PARITY"
    row = dict(
        building_id=site,
        rule_id="FC1",
        equipment_id="E",
        utc_day="2026-01-01",
        fault_seconds=300,
        covered_seconds=600,
        status="FAULT",
        pair_status="computed",
    )
    count = dict(building_id=site, table="sample", row_count=3)
    baseline = {"sql_fdd_daily": [row], "sample_counts": [count]}
    probes = []
    manifest_ok = ({}, [])
    with mock.patch.object(Path, "is_dir", return_value=True), mock.patch.object(
        pc.bio, "verify_site_manifest", return_value=manifest_ok
    ), mock.patch.object(pc, "load_baseline_site_dir", return_value=baseline):
        for name, rows, counts in [
            ("missing_all_sql", [], [count]),
            ("changed_coverage", [dict(row, covered_seconds=900)], [count]),
            ("changed_status", [dict(row, status="NOT_ASSESSED")], [count]),
            ("extra_sql", [row, dict(row, equipment_id="FOREIGN")], [count]),
            ("duplicate_sql", [row, row], [count]),
            ("missing_sample_counts", [row], []),
        ]:
            result = pc.compare_p3_post_cutover(
                baseline_dir=Path("/unused"),
                building_id=site,
                live_sql_daily=rows,
                live_sample_counts=counts,
            )
            probes.append(
                dict(
                    probe=name,
                    errors=list(result.errors),
                    comparisons=result.comparisons,
                    gap_reproduced=not result.errors,
                )
            )

    result = cts.p2_pair_for_si_row(
        rule_id="QA_UNSHIPPED",
        equipment_id="E",
        utc_day="2026-01-01",
        pandas_si_fault_seconds=300,
        sql_si_fault_seconds=0,
    )
    probes.append(
        dict(
            probe="conditional_availability_self_comparison",
            result=result,
            gap_reproduced=result["sql_si_fault_seconds"] not in (None, 0),
        )
    )

    golden = dict(building_id=site, pandas_fdd_daily=[row], pandas_si_daily=[dict(row)])
    with mock.patch.object(cfl, "load_rule_registry", return_value=[]), mock.patch.object(
        cfl, "expected_pandas_rule_ids", return_value=set()
    ), mock.patch.object(
        pc, "verify_golden_rule_attempted", return_value=pc.StageResult("coverage", 1, ())
    ), mock.patch.object(
        pc, "verify_current_p1_oracle_provenance", return_value=()
    ), mock.patch.object(
        pc, "verify_current_p1_oracle_provenance", return_value=()
    ), mock.patch.object(
        cfl, "recompute_si_daily_for_golden", return_value={pc.fdd_daily_key(row): 300.0}
    ) as recompute:
        result = pc.run_p1_ip_vs_si([golden], scope={"FC1"})
        probes.append(
            dict(
                probe="normal_p1_cached_si",
                oracle_calls=recompute.call_count,
                errors=list(result.errors),
                gap_reproduced=recompute.call_count == 0 and not result.errors,
            )
        )

    class Cursor:
        def __init__(self):
            self.queries = []

        def execute(self, query):
            self.queries.append(query)

        @property
        def description(self):
            class Col:
                name = "equipment_id"

            class Col2:
                name = "fault_hours"

            return [Col(), Col2()]

        def fetchall(self):
            if self.queries[-1] == "OVERLAY":
                return [("E", pd.Timestamp("2026-01-01T00:00:00Z"), True)]
            return [("E", 300.0 / 3600.0)]

    cur = Cursor()
    with mock.patch.object(cts, "render_rule_sql", return_value="ORIGINAL_AGGREGATE"), mock.patch.object(
        cts, "rewrite_fault_series", return_value="OVERLAY"
    ):
        _rows, error = cts.execute_sql_rule_daily(
            cur,
            rule={"rule_id": "FC1", "sql_file": "fixture.sql"},
            building_id=site,
            equipment_id="E",
            poll_seconds=300,
            index=pd.date_range("2026-01-01T00:00:00Z", periods=2, freq="5min"),
        )
        probes.append(
            dict(
                probe="original_aggregate_not_executed",
                executed_queries=cur.queries,
                error=error,
                gap_reproduced="ORIGINAL_AGGREGATE" not in cur.queries and error is None,
            )
        )

    print(json.dumps({"qualification": False, "probes": probes}, indent=2))
    return 1 if any(p["gap_reproduced"] for p in probes) else 0


if __name__ == "__main__":
    raise SystemExit(main())
