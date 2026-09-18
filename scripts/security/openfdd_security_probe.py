#!/usr/bin/env python3
"""Open-FDD security probe CLI.

Default is dry-run (no network, no credential reads). Explicit --execute
is required for traffic against an allowlisted origin.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# Allow `python3 scripts/security/openfdd_security_probe.py` without install.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from openfdd_security.config import ConfigError  # noqa: E402
from openfdd_security.runner import list_suites, run_probe  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", type=Path, help="nonsecret fixtures JSON")
    p.add_argument("--base-url", help="exact origin (must be in config allowlist)")
    p.add_argument(
        "--profile",
        choices=("live_readonly", "isolated_full", "local_open"),
        help="security profile",
    )
    p.add_argument(
        "--suite",
        action="append",
        dest="suites",
        help="suite subset (X/Y/Z/mqtt_acl); repeatable. Subset ≠ full profile.",
    )
    p.add_argument("--list-suites", action="store_true")
    p.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="plan only (default when --execute omitted)",
    )
    p.add_argument(
        "--execute",
        action="store_true",
        help="send traffic (conflicts with --dry-run)",
    )
    p.add_argument("--max-requests", type=int)
    p.add_argument("--timeout", type=float, help="per-request timeout seconds")
    p.add_argument("--deadline", type=float, help="run deadline seconds")
    p.add_argument("--rate", type=float, help="requests per second")
    p.add_argument("--output-dir", type=Path)
    p.add_argument(
        "--allow-fixture-writes",
        action="store_true",
        help="permit allowlisted fixture mutations (isolated_full only)",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.list_suites:
        print(json.dumps(list_suites(), indent=2))
        return 0

    if not args.config or not args.base_url or not args.profile:
        print(
            "ERROR: --config --base-url --profile required "
            "(or use --list-suites)",
            file=sys.stderr,
        )
        return 2

    execute = bool(args.execute)
    dry_run = bool(args.dry_run) or not execute
    if args.execute and args.dry_run:
        print("ERROR: --execute conflicts with --dry-run", file=sys.stderr)
        return 2

    try:
        report, meta = run_probe(
            config_path=args.config,
            base_url=args.base_url,
            profile=args.profile,
            suites=args.suites,
            execute=execute,
            dry_run=dry_run,
            max_requests=args.max_requests,
            timeout=args.timeout,
            deadline=args.deadline,
            rate=args.rate,
            output_dir=args.output_dir,
            allow_fixture_writes=bool(args.allow_fixture_writes),
        )
    except ConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    summary = {
        "run_id": report.run_id,
        "profile": report.profile,
        "executed": report.executed,
        "dry_run": report.dry_run,
        "full_profile": report.full_profile,
        "overall_status": report.overall_status,
        "fully_qualified": report.fully_qualified,
        "reason": report.reason,
        "counts": report.counts,
        "inventory": report.inventory,
        "output": meta,
    }
    print(json.dumps(summary, indent=2))

    # Exit: 0 complete PASS or successful dry-run plan; 1 FAIL; 2 incomplete
    if dry_run:
        return 0
    if report.fully_qualified:
        return 0
    if report.overall_status == "FAIL":
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
