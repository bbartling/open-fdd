#!/usr/bin/env python3
"""
Run RuleRunner with a sample DataFrame using one ontology's manifest + rule pair.

From the open-fdd repo root (with open-fdd installed):

    python examples/column_map_resolver_workshop/run_ontology_demo.py brick
    python examples/column_map_resolver_workshop/run_ontology_demo.py haystack
    python examples/column_map_resolver_workshop/run_ontology_demo.py dbo
    python examples/column_map_resolver_workshop/run_ontology_demo.py 223p
    python examples/column_map_resolver_workshop/run_ontology_demo.py minimal

    python examples/column_map_resolver_workshop/run_ontology_demo.py --list
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from open_fdd.engine.column_map_resolver import load_column_map_manifest
from open_fdd.engine.runner import RuleRunner, load_rule

MODES: dict[str, tuple[str, str]] = {
    # manifest_file, rule_file (under this directory)
    "minimal": ("manifest_minimal.yaml", "demo_rule.yaml"),
    "brick": ("manifest_brick.yaml", "demo_rule.yaml"),
    "haystack": ("manifest_haystack.yaml", "demo_rule_haystack.yaml"),
    "dbo": ("manifest_dbo.yaml", "demo_rule_dbo.yaml"),
    "223p": ("manifest_223p_safe.yaml", "demo_rule_223p.yaml"),
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run column_map + RuleRunner demo for Brick, Haystack, DBO, or 223P-style keys."
    )
    parser.add_argument(
        "mode",
        nargs="?",
        choices=sorted(MODES.keys()),
        help="Ontology / naming convention to demo",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Print modes and exit",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parent

    if args.list:
        print("Modes (manifest → rule):")
        for m in sorted(MODES.keys()):
            man, rule = MODES[m]
            print(f"  {m:10}  {man}  +  {rule}")
        print("\nExample: python examples/column_map_resolver_workshop/run_ontology_demo.py haystack")
        return

    if not args.mode:
        parser.print_help()
        print("\nPass a mode or use --list.", file=sys.stderr)
        sys.exit(2)

    manifest_name, rule_name = MODES[args.mode]
    manifest_path = root / manifest_name
    rule_path = root / rule_name

    column_map = load_column_map_manifest(manifest_path)
    if not column_map:
        raise SystemExit(f"No column_map loaded from {manifest_path}")

    rules = [load_rule(rule_path)]
    runner = RuleRunner(rules=rules)

    df = pd.DataFrame(
        {
            "timestamp": pd.date_range("2025-01-01", periods=5, freq="h", tz="UTC"),
            "sat": [72.0, 74.0, 76.0, 105.0, 70.0],
            "oat": [35.0, 36.0, 38.0, 40.0, 34.0],
        }
    )

    result = runner.run(
        df,
        timestamp_col="timestamp",
        column_map=column_map,
        params={"units": "imperial"},
        skip_missing_columns=True,
    )

    print(f"mode={args.mode!r}  manifest={manifest_name}  rule={rule_name}")
    print("column_map:", column_map)
    print(result[["timestamp", "sat", "demo_high_sat_flag"]].to_string(index=False))
    flag_col = "demo_high_sat_flag"
    if flag_col in result.columns:
        print(f"\n{flag_col} any True:", bool(result[flag_col].astype(bool).any()))


if __name__ == "__main__":
    main()
