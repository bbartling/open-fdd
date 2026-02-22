"""
Run all rules from my_rules against CSV data using Brick model mapping.

Workflow:
1. Load data model TTL (data_model.ttl) and resolve column_map
2. Load equipment types from Brick (e.g. VAV_AHU)
3. Load all rules from my_rules
4. Filter rules by equipment_type (run only rules that apply to model equipment)
5. Add synthetic columns for missing data (e.g. duct static setpoint if not in CSV)
6. Run RuleRunner with column_map

Prerequisite: Run validate_data_model.py first to ensure mapping is valid.

Usage:
    python run_all_rules_brick.py
    python run_all_rules_brick.py --ttl data_model.ttl --rules my_rules --csv data_ahu7.csv
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

# Add examples to path
_script_dir = Path(__file__).resolve().parent
if str(_script_dir) not in sys.path:
    sys.path.insert(0, str(_script_dir))

from open_fdd.engine.brick_resolver import (
    resolve_from_ttl,
    get_equipment_types_from_ttl,
)
from open_fdd.engine.runner import RuleRunner, load_rules_from_dir


def _filter_rules_by_equipment(
    rules: list[dict], equipment_types: list[str]
) -> list[dict]:
    """Keep rules that apply: no equipment_type, or equipment_type intersects model."""
    if not equipment_types:
        return rules  # No equipment filter in model, run all
    out = []
    for r in rules:
        rule_types = r.get("equipment_type")
        if not rule_types:
            out.append(r)  # Rule applies to all
        elif any(rt in equipment_types for rt in rule_types):
            out.append(r)
    return out


def _add_synthetic_columns(
    df: pd.DataFrame, column_map: dict[str, str]
) -> pd.DataFrame:
    """
    Add synthetic columns for Brick-mapped columns that are missing from CSV.
    E.g. duct static setpoint often not in BMS export — use constant for demo.
    """
    df = df.copy()
    for brick_key, csv_col in column_map.items():
        if csv_col not in df.columns:
            # Add constant column for demo (e.g. duct static setpoint = 0.5 inH2O)
            if "Setpoint" in brick_key or "setpoint" in brick_key.lower():
                df[csv_col] = 0.5  # Default duct static setpoint inH2O
    return df


def main() -> int:
    parser = argparse.ArgumentParser(description="Run all Brick-mapped rules on CSV")
    parser.add_argument("--ttl", default="data_model.ttl", help="Path to data model TTL")
    parser.add_argument("--rules", default="my_rules", help="Path to rules directory")
    parser.add_argument("--csv", default="data_ahu7.csv", help="Path to CSV data")
    parser.add_argument(
        "--validate-first", action="store_true", help="Run validate_data_model.py first"
    )
    args = parser.parse_args()

    ttl_path = _script_dir / args.ttl
    rules_dir = _script_dir / args.rules
    csv_path = _script_dir / args.csv

    if args.validate_first:
        import subprocess

        r = subprocess.run(
            [
                sys.executable,
                str(_script_dir / "validate_data_model.py"),
                "--ttl",
                args.ttl,
                "--rules",
                args.rules,
            ],
            cwd=str(_script_dir),
        )
        if r.returncode != 0:
            print("Validation failed. Fix errors before running.")
            return 1

    if not ttl_path.exists():
        print(f"Brick TTL not found: {ttl_path}")
        return 1
    if not rules_dir.is_dir():
        print(f"Rules dir not found: {rules_dir}")
        return 1
    if not csv_path.exists():
        print(f"CSV not found: {csv_path}")
        return 1

    print("Loading Brick model...")
    column_map = resolve_from_ttl(ttl_path)
    equipment_types = get_equipment_types_from_ttl(ttl_path)
    print(f"  Column map: {len(column_map)} mappings")
    print(f"  Equipment types: {equipment_types or ['(all)']}")

    print("Loading rules...")
    all_rules = load_rules_from_dir(rules_dir)
    rules = _filter_rules_by_equipment(all_rules, equipment_types)
    print(f"  Loaded {len(all_rules)} rules, {len(rules)} apply to this equipment")

    print("Loading CSV...")
    df = pd.read_csv(csv_path)
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = _add_synthetic_columns(df, column_map)

    runner = RuleRunner(rules=rules)
    result = runner.run(
        df,
        timestamp_col="timestamp",
        params={"units": "imperial"},
        skip_missing_columns=True,
        column_map=column_map,
    )

    flag_cols = [c for c in result.columns if c.endswith("_flag")]
    print(f"\nRan {len(rules)} rules. Flag columns: {flag_cols}")
    for col in flag_cols:
        n = int(result[col].sum())
        print(f"  {col}: {n} fault samples")

    out_path = _script_dir / "run_all_rules_output.csv"
    result.to_csv(out_path, index=False)
    print(f"\nOutput saved to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
