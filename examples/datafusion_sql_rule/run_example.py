#!/usr/bin/env python3
"""Minimal DataFusion SQL rule against synthetic HVAC telemetry."""

from __future__ import annotations

from open_fdd.arrow_runtime.datafusion_backend import datafusion_available, run_datafusion_sql_rule
from open_fdd.arrow_runtime.testing import sample_hvac_table

SQL = """SELECT
  *,
  zone_temp > 75.0 AS fault
FROM telemetry"""


def main() -> None:
    if not datafusion_available():
        raise SystemExit("Install optional extra: pip install 'open-fdd[datafusion]'")
    table = sample_hvac_table(100, seed=7)
    result = run_datafusion_sql_rule(SQL, table, rule_id="sat_high_sql")
    print(f"rows={result.row_count} true={result.true_count} backend={result.backend}")
    if result.errors:
        raise SystemExit(result.errors[0])


if __name__ == "__main__":
    main()
