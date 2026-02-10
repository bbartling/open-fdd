#!/usr/bin/env python3
"""
Run Open-Meteo weather fetch: once or on an interval → TimescaleDB.

Fetches hourly weather (temp, RH, dewpoint, wind, gust) from Open-Meteo archive API,
stores in timeseries_readings under a site (points: temp_f, rh_pct, dewpoint_f, wind_mph, gust_mph).

Usage:
  python tools/run_weather_fetch.py
  python tools/run_weather_fetch.py --loop

Config (env or .env): OFDD_OPEN_METEO_ENABLED, OFDD_OPEN_METEO_LATITUDE, OFDD_OPEN_METEO_LONGITUDE,
  OFDD_OPEN_METEO_INTERVAL_HOURS, OFDD_OPEN_METEO_DAYS_BACK, OFDD_OPEN_METEO_TIMEZONE,
  OFDD_OPEN_METEO_SITE_ID, OFDD_DB_DSN.
"""

import argparse
import logging
import sys
import time
import uuid
from pathlib import Path

# Add project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from open_fdd.platform.config import get_platform_settings
from open_fdd.platform.database import get_conn
from open_fdd.platform.drivers.open_meteo import run_open_meteo_fetch


def setup_logging(verbose: bool = False) -> None:
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format=fmt, datefmt="%Y-%m-%d %H:%M:%S")


def resolve_site_uuid(site_id: str) -> uuid.UUID:
    """Resolve site name or UUID string to UUID; create site if missing."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM sites WHERE id::text = %s OR name = %s",
                (site_id, site_id),
            )
            row = cur.fetchone()
            if row:
                return row["id"]
            cur.execute("INSERT INTO sites (name) VALUES (%s) RETURNING id", (site_id,))
            site_uuid = cur.fetchone()["id"]
            conn.commit()
            return site_uuid


def main() -> int:
    parser = argparse.ArgumentParser(description="Open-Meteo weather fetch → TimescaleDB")
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Run fetch every N hours (OFDD_OPEN_METEO_INTERVAL_HOURS)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Debug logging",
    )
    args = parser.parse_args()

    setup_logging(args.verbose)
    log = logging.getLogger("open_fdd.weather")

    settings = get_platform_settings()
    if not settings.open_meteo_enabled:
        log.info("Open-Meteo disabled (OFDD_OPEN_METEO_ENABLED=false); exiting")
        return 0

    lat = settings.open_meteo_latitude
    lon = settings.open_meteo_longitude
    interval_hours = settings.open_meteo_interval_hours
    days_back = settings.open_meteo_days_back
    timezone = settings.open_meteo_timezone
    site_id_str = settings.open_meteo_site_id

    log.info(
        "Open-Meteo fetch: lat=%.4f lon=%.4f site=%s days_back=%s tz=%s",
        lat,
        lon,
        site_id_str,
        days_back,
        timezone,
    )

    try:
        site_uuid = resolve_site_uuid(site_id_str)
    except Exception as e:
        log.error("Resolve site %s: %s", site_id_str, e)
        return 1

    while True:
        try:
            out = run_open_meteo_fetch(
                site_uuid,
                lat,
                lon,
                days_back=days_back,
                timezone=timezone,
            )
            log.info(
                "Open-Meteo fetch OK: rows=%s points=%s",
                out.get("rows_inserted", 0),
                out.get("points_created", 0),
            )
        except Exception as e:
            log.exception("Open-Meteo fetch failed: %s", e)
            if not args.loop:
                return 1

        if not args.loop:
            break
        sleep_sec = interval_hours * 3600
        log.info("Sleeping %s h until next fetch", interval_hours)
        time.sleep(sleep_sec)

    return 0


if __name__ == "__main__":
    sys.exit(main())
