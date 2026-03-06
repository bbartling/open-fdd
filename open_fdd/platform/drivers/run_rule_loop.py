#!/usr/bin/env python3
"""
Run FDD rule loop on a schedule (default: every 3 hours, 3-day lookback).

Each run: if Open-Meteo is enabled (graph/config), fetches weather for the same
lookback window so rules have fresh data; then loads rules from YAML, pulls last N days
of site data into pandas, runs all rules (sensor + weather), writes fault_results.
Analyst edits to YAML take effect on the next run; no restart required.

Weather: Fetched at each FDD run (same interval as rule_interval_hours). To avoid
redundant fetches, do not run the standalone weather scraper (run_weather_fetch.py --loop)
when using this loop; use one or the other.

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
from open_fdd.platform.site_resolver import resolve_site_uuid

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
    interval_hours = float(settings.rule_interval_hours)
    lookback_days = settings.lookback_days

    def _run() -> int:
        settings = get_platform_settings()
        # Run Open-Meteo fetch when FDD runs so weather is fresh for rules (same interval, graph-driven).
        if getattr(settings, "open_meteo_enabled", True):
            try:
                from open_fdd.platform.drivers.open_meteo import run_open_meteo_fetch

                site_uuid = resolve_site_uuid(
                    getattr(settings, "open_meteo_site_id", "default") or "default"
                )
                if site_uuid:
                    run_open_meteo_fetch(
                        site_uuid,
                        getattr(settings, "open_meteo_latitude", 41.88),
                        getattr(settings, "open_meteo_longitude", -87.63),
                        days_back=lookback_days,
                        timezone=getattr(
                            settings, "open_meteo_timezone", "America/Chicago"
                        ),
                    )
                    log.info("Open-Meteo fetch OK before FDD run")
            except Exception as we:
                log.warning("Open-Meteo fetch before FDD run failed (continuing): %s", we)

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
        sleep_sec = max(60, int(interval_hours * 3600))  # min 60s to avoid tight loop
        log.info(
            "FDD loop started: every %.2f h (%d s), lookback %d days (touch %s to run now)",
            interval_hours,
            sleep_sec,
            lookback_days,
            getattr(settings, "fdd_trigger_file", "config/.run_fdd_now")
            or "config/.run_fdd_now",
        )
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
            log.info("Next run in %.2f h", interval_hours)
    else:
        return _run()


if __name__ == "__main__":
    sys.exit(main())
