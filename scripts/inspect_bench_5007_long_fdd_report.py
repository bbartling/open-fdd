#!/usr/bin/env python3
"""Print Bench 5007 long FDD smoke report quality metrics."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from open_fdd.validation.bench_5007_long_fdd import summarize_report_dict  # noqa: E402


def _print_summary(payload: dict) -> None:
    summary = summarize_report_dict(payload)
    for key, value in summary.items():
        if isinstance(value, list):
            print(f"{key}: {', '.join(str(v) for v in value) if value else '(none)'}")
        else:
            print(f"{key}: {value}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect Bench 5007 long FDD JSON reports")
    parser.add_argument("paths", nargs="+", type=Path, help="bench_5007_long_fdd_*.json report paths")
    parser.add_argument("--json", action="store_true", help="Emit JSON summary")
    args = parser.parse_args()

    exit_code = 0
    for path in args.paths:
        if not path.is_file():
            print(f"MISSING: {path}", file=sys.stderr)
            exit_code = 2
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        print(f"--- {path.name} ---")
        if args.json:
            print(json.dumps(summarize_report_dict(payload), indent=2))
        else:
            _print_summary(payload)
        print()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
