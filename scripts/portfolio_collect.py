#!/usr/bin/env python3
"""Poll all sites in portfolio/sites.json and append CSV analytics history."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from portfolio.collector.collector import collect_all  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Open-FDD portfolio collector")
    parser.add_argument(
        "--sites",
        type=Path,
        default=REPO / "portfolio" / "sites.json",
        help="Path to sites.json registry",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=REPO / "portfolio" / "data",
        help="CSV output directory",
    )
    parser.add_argument("--json", action="store_true", help="Print summary JSON")
    args = parser.parse_args(argv)

    summary = collect_all(sites_path=args.sites, data_dir=args.data_dir)
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(
            f"portfolio collect: {summary.get('sites_ok')}/{summary.get('sites_polled')} sites ok"
        )
        for row in summary.get("results") or []:
            if row.get("ok"):
                print(f"  ok  {row.get('site_id')}")
            else:
                print(f"  ERR {row.get('site_id')}: {row.get('error')}")
    return 0 if summary.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
