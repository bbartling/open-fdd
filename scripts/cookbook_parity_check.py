#!/usr/bin/env python3
"""Offline Pandas parity checks + cookbook docs integrity for Open-FDD."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COOKBOOK = ROOT / "docs" / "rules" / "cookbook"
FIXTURES = COOKBOOK / "fixtures"

REQUIRED_PAGES = [
    "index.md",
    "datafusion-sql-cookbook.md",
    "pandas-cookbook.md",
    "taxonomy.md",
    "rule-schema.md",
    "gap-matrix.md",
    "parity-matrix.md",
    "roadmap.md",
    "prerequisite-macros.md",
    "benchmark-strategy.md",
    "doc-template.md",
    "p0-rule-catalog.md",
]

# Guard against accidental gut-outs of the public cookbook.
MIN_RULE_HEADINGS = 55
RULE_HEADING_RE = re.compile(r"^### [A-Z][A-Z0-9-]* —", re.MULTILINE)


def norm_cmd(s):
    import numpy as np
    import pandas as pd

    s = pd.to_numeric(s, errors="coerce")
    return pd.Series(np.where(s > 1.0, s / 100.0, s), index=s.index)


def load_fixture(name: str):
    import pandas as pd

    path = FIXTURES / name
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    df = pd.DataFrame(rows)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df.sort_values("timestamp")


def rule_reset1(df):
    err = 3.0
    expected = 52.0 + 0.25 * (df["oat"] - 65.0)
    return (
        df["sat_sp"].notna()
        & df["oat"].notna()
        & df["fan_status"].astype(bool)
        & (df["sat_sp"].sub(expected).abs() > err)
    )


def rule_sched1(df):
    return df["occ_mode"].eq("unoccupied") & df["fan_status"].astype(bool)


def rule_fc1(df):
    fan = norm_cmd(df["fan_cmd"])
    return (
        df["duct_static"].notna()
        & df["duct_static_sp"].notna()
        & (df["duct_static"] < df["duct_static_sp"] - 0.12)
        & (fan >= 0.87)
    )


def rule_vav6(df):
    reheat = norm_cmd(df["reheat_valve_pct"])
    return (
        df.get("clg_available", False).astype(bool)
        & (df["oa_t"] < 65.0)
        & (reheat > 0.25)
    )


def rule_vav7(df):
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


def run_docs_integrity() -> None:
    missing = [p for p in REQUIRED_PAGES if not (COOKBOOK / p).is_file()]
    if missing:
        raise AssertionError(f"missing cookbook pages: {missing}")

    for name in ("pandas-cookbook.md", "datafusion-sql-cookbook.md"):
        text = (COOKBOOK / name).read_text(encoding="utf-8")
        n = len(RULE_HEADING_RE.findall(text))
        if n < MIN_RULE_HEADINGS:
            raise AssertionError(
                f"{name}: expected >= {MIN_RULE_HEADINGS} rule headings, found {n}"
            )
        print(f"PASS docs {name} ({n} rule headings)")

    # Validated-catalog markers must remain (guard against vibe-coded gut-outs).
    pandas_text = (COOKBOOK / "pandas-cookbook.md").read_text(encoding="utf-8")
    for marker in ("SV-RANGE", "PID-HUNT-1", "FC1", "SCHED-247", "OAT-METEO"):
        if marker not in pandas_text:
            raise AssertionError(f"pandas-cookbook.md missing validated marker {marker}")
    print(f"PASS docs integrity ({len(REQUIRED_PAGES)} pages)")


def run_check(fixture: str, fn, expect_any: bool) -> None:
    df = load_fixture(fixture)
    raw = fn(df)
    got = bool(raw.fillna(False).any())
    if got != expect_any:
        raise AssertionError(f"{fixture}: expected any={expect_any}, got {got}")
    print(f"PASS {fixture}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Cookbook docs integrity + Pandas fixtures")
    parser.add_argument("--all", action="store_true", help="Run docs integrity + all fixtures")
    parser.add_argument("--docs-only", action="store_true", help="Only docs integrity checks")
    parser.add_argument("--fixture", help="Single fixture filename")
    args = parser.parse_args()

    try:
        run_docs_integrity()
    except AssertionError as exc:
        print(f"FAIL docs integrity: {exc}", file=sys.stderr)
        return 1

    if args.docs_only:
        return 0

    try:
        import pandas  # noqa: F401
    except ImportError:
        print("SKIP fixtures: pandas not installed", file=sys.stderr)
        return 0 if (args.all or args.fixture) else 0

    if args.fixture:
        if args.fixture not in CHECKS:
            print(f"Unknown fixture: {args.fixture}", file=sys.stderr)
            return 1
        fn, exp = CHECKS[args.fixture]
        run_check(args.fixture, fn, exp)
        return 0

    if not args.all:
        parser.print_help()
        return 1

    for fixture, (fn, exp) in CHECKS.items():
        run_check(fixture, fn, exp)
    print(f"All {len(CHECKS)} fixture checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
