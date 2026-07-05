#!/usr/bin/env python3
"""Offline Pandas parity checks for Open-FDD cookbook fixtures."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "docs" / "rules" / "cookbook" / "fixtures"


def norm_cmd(s: pd.Series) -> pd.Series:
    import numpy as np

    s = pd.to_numeric(s, errors="coerce")
    return pd.Series(np.where(s > 1.0, s / 100.0, s), index=s.index)


def load_fixture(name: str) -> pd.DataFrame:
    path = FIXTURES / name
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    df = pd.DataFrame(rows)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df.sort_values("timestamp")


def rule_reset1(df: pd.DataFrame) -> pd.Series:
    err = 3.0
    expected = 52.0 + 0.25 * (df["oat"] - 65.0)
    return (
        df["sat_sp"].notna()
        & df["oat"].notna()
        & df["fan_status"].astype(bool)
        & (df["sat_sp"].sub(expected).abs() > err)
    )


def rule_sched1(df: pd.DataFrame) -> pd.Series:
    return df["occ_mode"].eq("unoccupied") & df["fan_status"].astype(bool)


def rule_fc1(df: pd.DataFrame) -> pd.Series:
    fan = norm_cmd(df["fan_cmd"])
    return (
        df["duct_static"].notna()
        & df["duct_static_sp"].notna()
        & (df["duct_static"] < df["duct_static_sp"] - 0.12)
        & (fan >= 0.87)
    )


def rule_vav6(df: pd.DataFrame) -> pd.Series:
    reheat = norm_cmd(df["reheat_valve_pct"])
    return (
        df.get("clg_available", False).astype(bool)
        & (df["oa_t"] < 65.0)
        & (reheat > 0.25)
    )


def rule_vav7(df: pd.DataFrame) -> pd.Series:
    return df["zone_flow"].notna() & df["min_flow_sp"].notna() & (
        df["zone_flow"] < df["min_flow_sp"]
    )


CHECKS = {
    "reset1_obvious_fault.jsonl": (rule_reset1, True),
    "reset1_normal.jsonl": (rule_reset1, False),
    "sched1_obvious_fault.jsonl": (rule_sched1, True),
    "fc1_obvious_fault.jsonl": (rule_fc1, True),
    "vav6_obvious_fault.jsonl": (rule_vav6, True),
    "vav7_obvious_fault.jsonl": (rule_vav7, True),
}


def run_check(fixture: str, fn, expect_any: bool) -> None:
    df = load_fixture(fixture)
    raw = fn(df)
    got = bool(raw.fillna(False).any())
    if got != expect_any:
        raise AssertionError(f"{fixture}: expected any={expect_any}, got {got}")
    print(f"PASS {fixture}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Cookbook Pandas parity fixtures")
    parser.add_argument("--all", action="store_true", help="Run all fixture checks")
    parser.add_argument("--fixture", help="Single fixture filename")
    args = parser.parse_args()

    try:
        import pandas  # noqa: F401
    except ImportError:
        print("SKIP: pandas not installed", file=sys.stderr)
        return 0

    targets = CHECKS.items() if args.all else []
    if args.fixture:
        if args.fixture not in CHECKS:
            print(f"Unknown fixture: {args.fixture}", file=sys.stderr)
            return 1
        fn, exp = CHECKS[args.fixture]
        run_check(args.fixture, fn, exp)
        return 0

    if not targets:
        parser.print_help()
        return 1

    for fixture, (fn, exp) in targets:
        run_check(fixture, fn, exp)
    print(f"All {len(CHECKS)} fixture checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
