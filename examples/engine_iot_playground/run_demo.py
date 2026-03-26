#!/usr/bin/env python3
"""
Run Open-FDD-compatible YAML rules on a CSV — no Docker, no API.

Requires: pip install --upgrade open-fdd
"""

from __future__ import annotations

import argparse
import json
from importlib.metadata import version, PackageNotFoundError
from pathlib import Path

import pandas as pd
import yaml

from open_fdd.engine.runner import RuleRunner

ROOT = Path(__file__).resolve().parent
RTU11_PRESET_MAP = {"RTU_11_DA_T(°F)": "supply_air_temp_f"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Open-FDD YAML rules on a CSV file (engine-only)."
    )
    parser.add_argument(
        "--csv",
        default=str(ROOT / "data" / "RTU11.csv"),
        help="Path to CSV file.",
    )
    parser.add_argument(
        "--rules",
        default=str(ROOT / "rules"),
        help="Path to rules directory containing *.yaml files.",
    )
    parser.add_argument(
        "--timestamp-col",
        default="Timestamp",
        help="Timestamp column name in CSV.",
    )
    parser.add_argument(
        "--timestamp-format",
        default="%d-%b-%y %I:%M:%S %p EST",
        help="Optional explicit datetime format for pandas.to_datetime.",
    )
    parser.add_argument(
        "--preset",
        choices=["none", "rtu11"],
        default="rtu11",
        help="Apply a known source->rule column mapping preset.",
    )
    parser.add_argument(
        "--column-map-json",
        default=None,
        help='Optional JSON object for source->rule mapping, e.g. \'{"RTU_11_DA_T(°F)":"supply_air_temp_f"}\'.',
    )
    return parser.parse_args()


def load_rule_inputs(rules_dir: Path) -> dict[str, list[str]]:
    """Return rule name -> expected input columns from YAML files."""
    mapping: dict[str, list[str]] = {}
    for rule_path in sorted(rules_dir.glob("*.yaml")):
        with rule_path.open("r", encoding="utf-8") as f:
            rule = yaml.safe_load(f) or {}
        name = str(rule.get("name") or rule.get("flag") or rule_path.stem)
        inputs = rule.get("inputs") or []
        cols = [str(item.get("column")) for item in inputs if isinstance(item, dict) and item.get("column")]
        mapping[name] = cols
    return mapping


def build_column_map(args: argparse.Namespace, csv_cols: list[str]) -> dict[str, str]:
    column_map: dict[str, str] = {}
    if args.preset == "rtu11":
        column_map.update(RTU11_PRESET_MAP)
    if args.column_map_json:
        parsed = json.loads(args.column_map_json)
        if not isinstance(parsed, dict):
            raise ValueError("--column-map-json must be a JSON object")
        column_map.update({str(k): str(v) for k, v in parsed.items()})

    # Keep only columns that exist in CSV to avoid noisy mapping mistakes.
    return {src: dst for src, dst in column_map.items() if src in csv_cols}


def main() -> None:
    args = parse_args()
    data_path = Path(args.csv)
    rules_path = Path(args.rules)
    df = pd.read_csv(data_path)
    if args.timestamp_col not in df.columns:
        raise ValueError(
            f"Timestamp column '{args.timestamp_col}' not found. "
            f"Available columns: {list(df.columns)}"
        )
    df[args.timestamp_col] = pd.to_datetime(
        df[args.timestamp_col],
        format=args.timestamp_format,
        errors="coerce",
    )
    df = df.dropna(subset=[args.timestamp_col]).sort_values(args.timestamp_col).reset_index(drop=True)
    column_map = build_column_map(args, list(df.columns))

    print("=== Engine-only rule demo ===")
    try:
        print(f"open-fdd package version: {version('open-fdd')}")
    except PackageNotFoundError:
        print("open-fdd package version: not found (install with: pip install --upgrade open-fdd)")
    print(f"Data source:  {data_path}")
    print(f"Rules folder: {rules_path}")
    print(f"Rows loaded:  {len(df)}")
    print()

    print("Columns in incoming data:")
    print(", ".join(df.columns))
    print()

    print("Rule input mapping (defined in rules/*.yaml -> inputs[].column):")
    for rule_name, cols in load_rule_inputs(rules_path).items():
        needed = ", ".join(cols) if cols else "(no explicit inputs)"
        print(f"- {rule_name}: {needed}")
    print()

    if column_map:
        print("Applying column_map (source -> rule column):")
        for src, dst in column_map.items():
            print(f"- {src} -> {dst}")
    else:
        print("No column_map configured (expects CSV columns already match rule inputs).")
    print()

    runner = RuleRunner(rules_path=rules_path)
    out = runner.run(
        df,
        timestamp_col=args.timestamp_col,
        skip_missing_columns=True,
        params={"units": "imperial"},
        column_map=column_map or None,
    )

    print("Result preview (last 12 rows):")
    print(out.tail(12).to_string(index=False))
    print()
    print("Fault flag counts:")
    for col in out.columns:
        if col.endswith("_flag"):
            print(f"{col}: {int(out[col].sum())} fault samples")


if __name__ == "__main__":
    main()
