#!/usr/bin/env python3
"""
Run Open-Meteo weather fetch: once or on an interval → TimescaleDB.

Fetches hourly weather from Open-Meteo ERA5 archive API, stores in timeseries_readings.
Points: temp_f, rh_pct, dewpoint_f, wind_mph, gust_mph, wind_dir_deg,
shortwave_wm2, direct_wm2, diffuse_wm2, gti_wm2, cloud_pct.

Usage:
  python tools/run_weather_fetch.py
  python tools/run_weather_fetch.py --loop

Config (env or .env): OFDD_OPEN_METEO_ENABLED, OFDD_OPEN_METEO_LATITUDE, OFDD_OPEN_METEO_LONGITUDE,
  OFDD_OPEN_METEO_INTERVAL_HOURS, OFDD_OPEN_METEO_DAYS_BACK, OFDD_OPEN_METEO_TIMEZONE,
  OFDD_OPEN_METEO_SITE_ID, OFDD_DB_DSN.
"""

import argparse
import json
import logging
import os
import sys
import time
import urllib.request
import uuid
from pathlib import Path

# Add project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from open_fdd.platform.config import get_platform_settings
from open_fdd.platform.database import get_conn
from open_fdd.platform.drivers.open_meteo import run_open_meteo_fetch


def _get_api_url() -> str:
    # Docker: http://openfdd_api:8000
    # Host/bench: http://192.168.204.16:8000
    return os.getenv("OFDD_API_URL", "http://localhost:8000").rstrip("/")


def _fetch_platform_config(log: logging.Logger) -> dict | None:
    """Best-effort GET /config. Returns dict or None if API unreachable."""
    url = f"{_get_api_url()}/config"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        log.warning(
            "Could not fetch platform config from %s (%s). Using env/defaults.",
            url,
            e,
        )
        return None


_CONFIG_CACHE: dict[str, object] = {"ts": 0.0, "cfg": None}


def _fetch_platform_config_cached(log: logging.Logger, ttl_sec: int = 30) -> dict | None:
    """
    Cache GET /config for a short TTL so the scraper doesn’t hammer the API.
    Returns dict or None.
    """
    now = time.time()
    ts = float(_CONFIG_CACHE["ts"])
    if now - ts < ttl_sec:
        return _CONFIG_CACHE["cfg"]  # may be None
    cfg = _fetch_platform_config(log)
    _CONFIG_CACHE["ts"] = now
    _CONFIG_CACHE["cfg"] = cfg
    return cfg


def setup_logging(verbose: bool = False) -> None:
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format=fmt, datefmt="%Y-%m-%d %H:%M:%S")


def resolve_site_uuid(site_id: str) -> uuid.UUID:
    """Resolve site name or UUID to UUID; use existing site if requested one missing (avoid duplicate default)."""
    from open_fdd.platform.site_resolver import resolve_site_uuid as _resolve

    result = _resolve(site_id, create_if_empty=True)
    if result is None:
        raise ValueError("No site available")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Open-Meteo weather fetch → TimescaleDB"
    )
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

    # Load defaults on boot
    settings = get_platform_settings()
    prev_interval_hours: int | None = None

    while True:
        # 1. Fetch dynamic config from API, fallback to pydantic defaults
        cfg = _fetch_platform_config_cached(log) or {}
        
        # Helper to get config prioritizing: API -> Pydantic env/defaults
        def get_cfg(key: str, default_val):
            val = cfg.get(key)
            return val if val is not None else default_val

        enabled = get_cfg("open_meteo_enabled", settings.open_meteo_enabled)
        
        if not enabled:
            log.info("Open-Meteo disabled via config/env; skipping fetch.")
            if not args.loop:
                return 0
            time.sleep(60)  # Sleep briefly before re-checking config
            continue

        lat = get_cfg("open_meteo_latitude", settings.open_meteo_latitude)
        lon = get_cfg("open_meteo_longitude", settings.open_meteo_longitude)
        interval_hours = get_cfg("open_meteo_interval_hours", settings.open_meteo_interval_hours)
        days_back = get_cfg("open_meteo_days_back", settings.open_meteo_days_back)
        timezone = get_cfg("open_meteo_timezone", settings.open_meteo_timezone)
        site_id_str = get_cfg("open_meteo_site_id", settings.open_meteo_site_id)

        if prev_interval_hours is not None and interval_hours != prev_interval_hours:
            log.info(
                "Weather fetch interval changed: %d h -> %d h",
                prev_interval_hours,
                interval_hours,
            )
        prev_interval_hours = interval_hours

        log.info(
            "Open-Meteo fetch: lat=%.4f lon=%.4f site=%s days_back=%s tz=%s",
            lat,
            lon,
            site_id_str,
            days_back,
            timezone,
        )

        # 2. Resolve UUID dynamically inside the loop
        try:
            site_uuid = resolve_site_uuid(site_id_str)
        except Exception as e:
            log.error("Resolve site %s: %s", site_id_str, e)
            if not args.loop:
                return 1
            time.sleep(60)  # If DB isn't ready or site missing, don't spin endlessly
            continue

        # 3. Fetch data
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

        # 4. Sleep logic
        if not args.loop:
            break
            
        sleep_sec = interval_hours * 3600
        log.info("Sleeping %s h until next fetch", interval_hours)
        time.sleep(sleep_sec)

    return 0


if __name__ == "__main__":
    sys.exit(main())