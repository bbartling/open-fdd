#!/usr/bin/env python3
"""
One-shot demo: JSON/YAML manifest → column_map → RuleRunner on a pandas DataFrame.

Run from repo root (or anywhere with open-fdd on PYTHONPATH):

    python examples/column_map_resolver_workshop/demo_one_shot.py

Requires: pip install open-fdd (pandas + PyYAML included).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from open_fdd.engine.column_map_resolver import load_column_map_manifest
from open_fdd.engine.runner import RuleRunner, load_rule


def main() -> None:
    root = Path(__file__).resolve().parent
    manifest = root / "manifest_minimal.yaml"
    column_map = load_column_map_manifest(manifest)
    if not column_map:
        raise SystemExit(f"No column_map loaded from {manifest}")

    rule_path = root / "demo_rule.yaml"
    rules = [load_rule(rule_path)]
    runner = RuleRunner(rules=rules)

    df = pd.DataFrame(
        {
            "timestamp": pd.date_range("2025-01-01", periods=5, freq="h", tz="UTC"),
            "sat": [72.0, 74.0, 76.0, 105.0, 70.0],
        }
    )

    result = runner.run(
        df,
        timestamp_col="timestamp",
        column_map=column_map,
        params={"units": "imperial"},
        skip_missing_columns=True,
    )
    print("column_map keys:", list(column_map.keys()))
    print(result.head())
    flag_col = "demo_high_sat_flag"
    if flag_col in result.columns:
        print(f"\n{flag_col} any True:", bool(result[flag_col].any()))


if __name__ == "__main__":
    main()
