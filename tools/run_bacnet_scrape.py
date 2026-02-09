#!/usr/bin/env python3
"""
Run BACnet scrape: RPC-driven via diy-bacnet-server → TimescaleDB.

Reads points from CSV config via diy-bacnet-server JSON-RPC (client_read_property,
client_read_multiple), writes to timeseries_readings.

Usage:
  OFDD_BACNET_SERVER_URL=http://localhost:8080 python tools/run_bacnet_scrape.py
  OFDD_BACNET_SERVER_URL=http://localhost:8080 python tools/run_bacnet_scrape.py --loop

Required: OFDD_BACNET_SERVER_URL (diy-bacnet-server)
Optional: OFDD_BACNET_SCRAPE_ENABLED, OFDD_BACNET_SCRAPE_INTERVAL_MIN, OFDD_DB_DSN
"""

import argparse
import logging
import sys
import time
from pathlib import Path

# Add project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from open_fdd.platform.drivers.bacnet_validate import validate_bacnet_csv


def setup_logging(verbose: bool = False) -> None:
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format=fmt, datefmt="%Y-%m-%d %H:%M:%S")


def main() -> int:
    parser = argparse.ArgumentParser(description="BACnet scrape → TimescaleDB")
    parser.add_argument(
        "csv",
        nargs="?",
        default="config/bacnet_discovered.csv",
        help="Path to BACnet CSV config",
    )
    parser.add_argument(
        "--site",
        default="default",
        help="Site ID for timeseries",
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Run scrape every N min (OFDD_BACNET_SCRAPE_INTERVAL_MIN)",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate CSV and exit",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Debug logging",
    )
    args = parser.parse_args()

    setup_logging(args.verbose)
    log = logging.getLogger("open_fdd.bacnet")

    csv_path = Path(args.csv)
    if not csv_path.is_absolute():
        csv_path = Path.cwd() / csv_path

    if args.validate_only:
        errors = validate_bacnet_csv(csv_path)
        if not errors:
            log.info("CSV valid: %s", csv_path)
            return 0
        for line_num, msg in errors:
            print(f"ERROR line {line_num}: {msg}", file=sys.stderr)
        return 1

    from open_fdd.platform.config import get_platform_settings
    from open_fdd.platform.drivers.bacnet import run_bacnet_scrape

    settings = get_platform_settings()
    if not settings.bacnet_scrape_enabled:
        log.warning(
            "BACnet scrape disabled. Set OFDD_BACNET_SCRAPE_ENABLED=true to enable."
        )
        return 0

    if args.loop:
        interval_sec = settings.bacnet_scrape_interval_min * 60
        log.info(
            "BACnet scrape loop: csv=%s interval=%d min",
            csv_path,
            settings.bacnet_scrape_interval_min,
        )
        while True:
            try:
                result = run_bacnet_scrape(csv_path, args.site)
                log.info(
                    "Scrape cycle: %d rows, %d points, %d errors",
                    result["rows_inserted"],
                    result["points_created"],
                    len(result["errors"]),
                )
            except Exception as e:
                log.exception("Scrape failed: %s", e)
            time.sleep(interval_sec)
    else:
        result = run_bacnet_scrape(csv_path, args.site)
        if result["errors"] and result["rows_inserted"] == 0:
            for e in result["errors"]:
                log.error("%s", e)
            return 1
        log.info(
            "Scrape done: %d rows written, %d points",
            result["rows_inserted"],
            result["points_created"],
        )
        return 0


if __name__ == "__main__":
    sys.exit(main())
