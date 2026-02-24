#!/usr/bin/env python3
"""
Run BACnet scrape: RPC-driven via diy-bacnet-server → TimescaleDB.

Reads points from CSV config via diy-bacnet-server JSON-RPC (client_read_property,
client_read_multiple), writes to timeseries_readings.

Single gateway (local or remote):
  OFDD_BACNET_SERVER_URL=http://localhost:8080 python tools/run_bacnet_scrape.py
  OFDD_BACNET_SITE_ID=building-a OFDD_DB_DSN=... python tools/run_bacnet_scrape.py --loop

Multiple gateways (central aggregator; OFDD_BACNET_GATEWAYS = JSON array):
  OFDD_BACNET_GATEWAYS='[{"url":"http://10.1.1.1:8080","site_id":"building-a","config_csv":"config/bacnet_a.csv"}]' python tools/run_bacnet_scrape.py --loop

Required (single): OFDD_BACNET_SERVER_URL
Optional: OFDD_BACNET_SITE_ID, OFDD_BACNET_SCRAPE_ENABLED, OFDD_BACNET_SCRAPE_INTERVAL_MIN, OFDD_DB_DSN

Config precedence (loop interval):
  1) API GET {OFDD_API_URL}/config (dynamic, RDF-backed)
  2) env OFDD_BACNET_SCRAPE_INTERVAL_MIN (boot default / fallback)
  3) platform defaults (get_platform_settings)
"""

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
import urllib.request


# Add project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Keep existing validation “test logic”
from open_fdd.platform.drivers.bacnet_validate import validate_bacnet_csv


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


def _resolve_csv_path(csv_str: str, cwd: Path) -> Path:
    p = Path(csv_str)
    return (cwd / p) if not p.is_absolute() else p


def _current_interval_min(log: logging.Logger) -> int:
    """
    Runtime precedence:
      1) API /config (RDF-backed, dynamic)
      2) env OFDD_BACNET_SCRAPE_INTERVAL_MIN (boot default / fallback)
      3) pydantic defaults (get_platform_settings)
    """
    # Lazy import to avoid import-time config loading
    from open_fdd.platform.config import get_platform_settings

    cfg = _fetch_platform_config_cached(log)
    if cfg and cfg.get("bacnet_scrape_interval_min") is not None:
        try:
            return int(cfg["bacnet_scrape_interval_min"])
        except (ValueError, TypeError):
            log.warning(
                "Invalid bacnet_scrape_interval_min from API: %r",
                cfg.get("bacnet_scrape_interval_min"),
            )

    # fallback to env
    try:
        v = os.environ.get("OFDD_BACNET_SCRAPE_INTERVAL_MIN")
        if v is not None and str(v).strip():
            return int(v.strip())
    except (ValueError, TypeError):
        pass

    return get_platform_settings().bacnet_scrape_interval_min


def main() -> int:
    parser = argparse.ArgumentParser(description="BACnet scrape → TimescaleDB")
    parser.add_argument(
        "csv",
        nargs="?",
        default="config/bacnet_discovered.csv",
        help="Path to BACnet CSV config (ignored when OFDD_BACNET_GATEWAYS is set)",
    )
    parser.add_argument(
        "--site",
        default="default",
        help="Site ID for timeseries (overridden by OFDD_BACNET_SITE_ID when default)",
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Run scrape every N min (OFDD_BACNET_SCRAPE_INTERVAL_MIN or API config)",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate CSV and exit",
    )
    parser.add_argument(
        "--data-model",
        action="store_true",
        help="Use only data-model scrape (no CSV fallback)",
    )
    parser.add_argument(
        "--csv-only",
        action="store_true",
        help="Use only CSV config (skip data-model)",
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
    cwd = Path.cwd()

    from open_fdd.platform.config import get_platform_settings
    from open_fdd.platform.drivers.bacnet import (
        run_bacnet_scrape,
        run_bacnet_scrape_data_model,
    )

    settings = get_platform_settings()

    # Multi-gateway mode (central aggregator)
    if settings.bacnet_gateways:
        try:
            gateways = json.loads(settings.bacnet_gateways)
        except (json.JSONDecodeError, TypeError) as e:
            log.error("OFDD_BACNET_GATEWAYS invalid JSON: %s", e)
            return 1
        if not isinstance(gateways, list) or not gateways:
            log.error("OFDD_BACNET_GATEWAYS must be a non-empty JSON array")
            return 1
        if not settings.bacnet_scrape_enabled:
            log.warning("BACnet scrape disabled.")
            return 0

        prev_interval_min: int | None = None
        while True:
            interval_min = _current_interval_min(log)
            interval_sec = interval_min * 60
            if prev_interval_min is not None and interval_min != prev_interval_min:
                log.info(
                    "BACnet scrape interval changed: %d min -> %d min",
                    prev_interval_min,
                    interval_min,
                )
            prev_interval_min = interval_min

            total_rows, total_points, total_errors = 0, 0, 0
            for gw in gateways:
                url = gw.get("url") or gw.get("server_url")
                site_id = gw.get("site_id", "default")
                config_csv = gw.get("config_csv") or gw.get("csv")
                if not url or not config_csv:
                    log.warning("Gateway missing url or config_csv: %s", gw)
                    continue

                csv_path = _resolve_csv_path(str(config_csv), cwd)
                if not csv_path.exists():
                    log.warning("Gateway CSV not found: %s", csv_path)
                    continue

                try:
                    result = run_bacnet_scrape(csv_path, site_id, "bacnet", server_url=url)
                except Exception as e:
                    log.exception("Gateway %s failed: %s", site_id, e)
                    continue

                total_rows += result.get("rows_inserted", 0)
                total_points += result.get("points_created", 0)
                total_errors += len(result.get("errors", []))
                log.info(
                    "Gateway %s (%s): %d rows, %d points",
                    site_id,
                    url,
                    result.get("rows_inserted", 0),
                    result.get("points_created", 0),
                )

            if not args.loop:
                return 0

            log.info(
                "Multi-gateway cycle done: %d rows, %d points; sleeping %d s (interval=%d min)",
                total_rows,
                total_points,
                interval_sec,
                interval_min,
            )
            time.sleep(interval_sec)

    # Single-gateway mode
    csv_path = _resolve_csv_path(args.csv, cwd)
    use_data_model = args.data_model or (settings.bacnet_use_data_model and not args.csv_only)
    site_id = args.site if args.site != "default" else settings.bacnet_site_id

    if args.validate_only:
        # retain test/validation logic
        errors = validate_bacnet_csv(csv_path)
        if not errors:
            log.info("CSV valid: %s", csv_path)
            return 0
        for line_num, msg in errors:
            print(f"ERROR line {line_num}: {msg}", file=sys.stderr)
        return 1

    if not settings.bacnet_scrape_enabled:
        log.warning("BACnet scrape disabled. Set OFDD_BACNET_SCRAPE_ENABLED=true to enable.")
        return 0

    def _run_single() -> dict:
        if use_data_model:
            # When site_id is "default", load points from all sites (data model has per-point site_id).
            data_model_site = None if site_id == "default" else site_id
            result = run_bacnet_scrape_data_model(
                site_id=data_model_site, server_url=settings.bacnet_server_url
            )
            if (
                result.get("rows_inserted", 0) > 0
                or result.get("points_created", 0) > 0
                or result.get("errors")
            ):
                return result

            # fallback to CSV only when not forced data-model and CSV exists
            if not args.data_model and csv_path.exists():
                log.info("No BACnet points in data model; falling back to CSV %s", csv_path)
                return run_bacnet_scrape(csv_path, site_id, "bacnet", server_url=settings.bacnet_server_url)

            return result

        return run_bacnet_scrape(csv_path, site_id, "bacnet", server_url=settings.bacnet_server_url)

    if args.loop:
        interval_min = _current_interval_min(log)
        log.info(
            "BACnet scrape loop: data_model=%s csv=%s site=%s interval=%d min (API/env/default precedence)",
            use_data_model,
            csv_path,
            site_id,
            interval_min,
        )

        prev_interval_min: int | None = None
        while True:
            interval_min = _current_interval_min(log)
            interval_sec = interval_min * 60
            if prev_interval_min is not None and interval_min != prev_interval_min:
                log.info(
                    "BACnet scrape interval changed: %d min -> %d min",
                    prev_interval_min,
                    interval_min,
                )
            prev_interval_min = interval_min

            try:
                result = _run_single()
                log.info(
                    "Scrape cycle: %d rows, %d points, %d errors (interval=%d min)",
                    result.get("rows_inserted", 0),
                    result.get("points_created", 0),
                    len(result.get("errors", [])),
                    interval_min,
                )
            except Exception as e:
                log.exception("Scrape failed: %s", e)

            time.sleep(interval_sec)

    # One-shot
    result = _run_single()
    if result.get("errors") and result.get("rows_inserted", 0) == 0:
        for e in result.get("errors", []):
            log.error("%s", e)
        return 1

    log.info(
        "Scrape done: %d rows written, %d points",
        result.get("rows_inserted", 0),
        result.get("points_created", 0),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())