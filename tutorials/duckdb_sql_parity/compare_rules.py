"""Validate borrowed Open-FDD rule SQL against its pandas twin in DuckDB.

Run from the repository root:
    uv run --with duckdb --with pandas --with numpy --with pyyaml --with openpyxl \
      python tutorials/duckdb_sql_parity/compare_rules.py
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import duckdb
import pandas as pd
from open_fdd.parity import generate, reference

ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / "nf-app" / "rules" / "pack-postgres.json"
DEFAULT_RULES = ("FC1", "FC2", "CMD-1")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rules", nargs="+", default=list(DEFAULT_RULES),
                        help="SQL rule IDs from the generated PostgreSQL pack")
    parser.add_argument("--tolerance-hours", type=float, default=1e-6)
    args = parser.parse_args()
    if not math.isfinite(args.tolerance_hours) or args.tolerance_hours < 0:
        parser.error("--tolerance-hours must be nonnegative and finite")

    ds = generate(seed=0, equips=2, days=3, profile="basic")
    pack = json.loads(PACK.read_text(encoding="utf-8"))
    history = pd.DataFrame(ds.to_engine_input()["history"])
    history["timestamp_utc"] = pd.to_datetime(history.pop("ts"), unit="ms", utc=True)

    # Register the dataframe explicitly: no implicit variable lookup in DuckDB.
    with duckdb.connect(":memory:") as conn:
        conn.execute("SET TimeZone = 'UTC'")
        conn.register("history_dataframe", history)
        conn.execute("CREATE TABLE history AS SELECT * FROM history_dataframe")

        failures = []
        for rule_id in args.rules:
            if rule_id not in pack["rules"]:
                raise SystemExit(f"Unknown rule ID: {rule_id}")
            try:
                result = conn.execute(pack["rules"][rule_id]["sql"])
                columns = [item[0] for item in result.description]
                sql_rows = [dict(zip(columns, row)) for row in result.fetchall()]
            except duckdb.Error as exc:
                raise SystemExit(
                    f"{rule_id} is not directly compatible with DuckDB. "
                    "Some PostgreSQL rules use fdd.* helper functions or other "
                    f"PostgreSQL-only SQL. Details: {exc}"
                ) from exc
            if not {"equipment_id", "fault_hours"} <= set(columns):
                raise SystemExit(f"{rule_id}: missing equipment_id/fault_hours")
            sql_by_eq = {str(row["equipment_id"]): row["fault_hours"]
                         for row in sql_rows}
            pandas_by_eq = {str(equip): record["pandas"]
                            for equip, record in reference(ds, rules=[rule_id])[rule_id].items()}
            print(f"\n{rule_id} (fault hours):")
            for equip in sorted(set(sql_by_eq) | set(pandas_by_eq)):
                sql_value = sql_by_eq.get(equip)
                pandas_value = pandas_by_eq.get(equip)
                valid = (
                    sql_value is not None and pandas_value is not None
                    and math.isfinite(float(sql_value))
                    and math.isfinite(float(pandas_value))
                    and abs(float(sql_value) - float(pandas_value)) <= args.tolerance_hours
                )
                print(f"  {equip}: pandas={pandas_value!s:>10} | "
                      f"duckdb={sql_value!s:>10} | {'PASS' if valid else 'FAIL'}")
                if not valid:
                    failures.append((rule_id, equip, pandas_value, sql_value))
        if failures:
            raise SystemExit(f"FAIL: {len(failures)} pandas/SQL mismatch(es): {failures}")
        print("\nPASS: all selected SQL results match pandas.")


if __name__ == "__main__":
    main()
