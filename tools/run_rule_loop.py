#!/usr/bin/env python3
"""
Run FDD rule loop on a schedule (default: every 3 hours, 3-day lookback).

Each run: loads rules from YAML (analyst/rules or open_fdd/rules), pulls last N days
of site data into pandas, runs all rules (sensor + weather), writes fault_results.
Analyst edits to YAML take effect on the next run; no restart required.

Usage:
  python tools/run_rule_loop.py           # one-shot
  python tools/run_rule_loop.py --loop    # every OFDD_RULE_INTERVAL_HOURS
  OFDD_RULE_INTERVAL_HOURS=6 OFDD_LOOKBACK_DAYS=1 python tools/run_rule_loop.py --loop

Config (env or .env): OFDD_RULE_INTERVAL_HOURS, OFDD_LOOKBACK_DAYS, OFDD_DATALAKE_RULES_DIR,
  OFDD_RULES_YAML_DIR, OFDD_BRICK_TTL_PATH, OFDD_DB_DSN.
"""

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from open_fdd.platform.config import get_platform_settings
from open_fdd.platform.loop import run_fdd_loop


def setup_logging(verbose: bool = False) -> None:
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format=fmt, datefmt="%Y-%m-%d %H:%M:%S")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="FDD rule loop: periodic runs with hot-reload (default 3h interval, 3-day lookback)"
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Run every N hours (OFDD_RULE_INTERVAL_HOURS)",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Debug logging",
    )
    args = parser.parse_args()

    setup_logging(args.verbose)
    log = logging.getLogger("open_fdd.fdd_loop")

    settings = get_platform_settings()
    interval_hours = settings.rule_interval_hours
    lookback_days = settings.lookback_days

    def _run() -> int:
        log.info(
            "FDD run: lookback=%d days, rules reload from YAML",
            lookback_days,
        )
        try:
            results = run_fdd_loop(lookback_days=lookback_days)
            log.info("FDD run OK: %d fault samples written", len(results))
            return 0
        except Exception as e:
            log.exception("FDD run failed: %s", e)
            return 1

    if args.loop:
        log.info("FDD loop started: every %d hours, lookback %d days", interval_hours, lookback_days)
        while True:
            _run()
            sleep_sec = interval_hours * 3600
            log.info("Sleeping %d s until next run", sleep_sec)
            time.sleep(sleep_sec)
    else:
        return _run()


if __name__ == "__main__":
    sys.exit(main())
