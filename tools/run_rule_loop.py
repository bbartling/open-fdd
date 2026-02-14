#!/usr/bin/env python3
"""
Run FDD rule loop on a schedule (default: every 3 hours, 3-day lookback).

Each run: loads rules from YAML (analyst/rules or open_fdd/rules), pulls last N days
of site data into pandas, runs all rules (sensor + weather), writes fault_results.
Analyst edits to YAML take effect on the next run; no restart required.

Usage:
  python tools/run_rule_loop.py           # one-shot (run now, exit)
  python tools/run_rule_loop.py --loop   # scheduled loop (checks trigger file every 60s)
  python tools/trigger_fdd_run.py        # touch trigger file → loop runs now + resets timer

When --loop: touch config/.run_fdd_now (or OFDD_FDD_TRIGGER_FILE) to run immediately
and restart the interval. Useful after rule edits.
"""

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from open_fdd.platform.config import get_platform_settings
from open_fdd.platform.loop import run_fdd_loop

TRIGGER_POLL_SEC = 60  # check for trigger file every N seconds


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
        "-v",
        "--verbose",
        action="store_true",
        help="Debug logging",
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
            # Hint when DB is unavailable
            try:
                import psycopg2

                if isinstance(e, psycopg2.OperationalError):
                    log.info(
                        "Tip: rule loop needs TimescaleDB. Start platform: ./scripts/bootstrap.sh or docker compose -f platform/docker-compose.yml up -d"
                    )
            except ImportError:
                pass
            return 1

    if args.loop:
        log.info(
            "FDD loop started: every %d hours, lookback %d days (touch %s to run now)",
            interval_hours,
            lookback_days,
            getattr(settings, "fdd_trigger_file", "config/.run_fdd_now")
            or "config/.run_fdd_now",
        )
        sleep_sec = interval_hours * 3600
        trigger_path = getattr(settings, "fdd_trigger_file", None)

        while True:
            _run()
            elapsed = 0
            while elapsed < sleep_sec:
                nap = min(TRIGGER_POLL_SEC, sleep_sec - elapsed)
                time.sleep(nap)
                elapsed += nap
                if trigger_path:
                    p = Path(trigger_path)
                    if not p.is_absolute():
                        p = Path.cwd() / p
                    if p.exists():
                        try:
                            p.unlink()
                        except OSError as e:
                            log.warning(
                                "Trigger file detected but could not remove %s (%s). "
                                "Loop will re-trigger every 60s until file is gone. "
                                "If running in Docker, ensure config volume is writable.",
                                p,
                                e,
                            )
                        log.info("Trigger file detected → running now, timer reset")
                        _run()
                        elapsed = 0  # reset timer
            log.info("Next run in %d h", interval_hours)
    else:
        return _run()


if __name__ == "__main__":
    sys.exit(main())
