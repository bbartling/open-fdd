#!/usr/bin/env python3
"""
Run BACnet scrape: RPC via diy-bacnet-server → TimescaleDB.

Addresses and object ids come only from the knowledge graph (points table populated
from TTL/import). Each scrape cycle loads polling points with BACnet metadata and
reads present-value via JSON-RPC.

Single gateway:
  OFDD_BACNET_SERVER_URL=http://localhost:8080 python -m open_fdd.platform.drivers.run_bacnet_scrape
  OFDD_BACNET_SITE_ID=building-a OFDD_DB_DSN=... python -m open_fdd.platform.drivers.run_bacnet_scrape --loop

Multiple gateways (central aggregator). OFDD_BACNET_GATEWAYS = JSON array of objects
with at least "url" and "site_id" (same data model / DB; each gateway URL may differ):
  OFDD_BACNET_GATEWAYS='[{"url":"http://10.1.1.1:8080","site_id":"building-a"}]' python -m ...

Config precedence (loop interval):
  1) API GET {OFDD_API_URL}/config (dynamic, RDF-backed)
  2) env OFDD_BACNET_SCRAPE_INTERVAL_MIN
  3) platform defaults (get_platform_settings)
"""

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _get_api_url() -> str:
    return os.getenv("OFDD_API_URL", "http://localhost:8000").rstrip("/")


def _fetch_platform_config(log: logging.Logger) -> dict | None:
    """Best-effort GET /config."""
    url = f"{_get_api_url()}/config"
    req = urllib.request.Request(url)
    api_key = os.environ.get("OFDD_API_KEY", "").strip()
    if api_key:
        req.add_header("Authorization", f"Bearer {api_key}")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 401:
            log.warning(
                "GET /config returned 401. Set OFDD_API_KEY in the scraper env (same as stack/.env).",
            )
        else:
            log.warning("GET /config failed: %s %s. Using env/defaults.", e.code, url)
        return None
    except Exception as e:
        log.warning(
            "Could not fetch platform config from %s (%s). Using env/defaults.",
            url,
            e,
        )
        return None


_CONFIG_CACHE: dict[str, object] = {"ts": 0.0, "cfg": None}


def _fetch_platform_config_cached(
    log: logging.Logger, ttl_sec: int = 30
) -> dict | None:
    now = time.time()
    ts = float(_CONFIG_CACHE["ts"])
    if now - ts < ttl_sec:
        return _CONFIG_CACHE["cfg"]
    cfg = _fetch_platform_config(log)
    _CONFIG_CACHE["ts"] = now
    _CONFIG_CACHE["cfg"] = cfg
    return cfg


def setup_logging(verbose: bool = False) -> None:
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format=fmt, datefmt="%Y-%m-%d %H:%M:%S")


def _current_interval_min(log: logging.Logger) -> int:
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

    try:
        v = os.environ.get("OFDD_BACNET_SCRAPE_INTERVAL_MIN")
        if v is not None and str(v).strip():
            return int(v.strip())
    except (ValueError, TypeError):
        pass

    return get_platform_settings().bacnet_scrape_interval_min


def main() -> int:
    parser = argparse.ArgumentParser(
        description="BACnet scrape (knowledge graph) → TimescaleDB",
    )
    parser.add_argument(
        "--site",
        default="default",
        help="Site ID for single-gateway mode (overridden by OFDD_BACNET_SITE_ID when default)",
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Run scrape every N min (OFDD_BACNET_SCRAPE_INTERVAL_MIN or API config)",
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

    from open_fdd.platform.config import get_platform_settings
    from open_fdd.platform.drivers.bacnet import run_bacnet_scrape_data_model

    settings = get_platform_settings()

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
                if not isinstance(gw, dict):
                    log.warning("Gateway entry must be an object: %s", gw)
                    continue
                url = (gw.get("url") or gw.get("server_url") or "").strip()
                site_id = (gw.get("site_id") or "default").strip()
                if not url:
                    log.warning('Gateway missing "url" or "server_url": %s', gw)
                    continue

                try:
                    result = run_bacnet_scrape_data_model(
                        site_id=site_id, server_url=url
                    )
                except Exception:
                    log.exception("Gateway %s failed", site_id)
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

    site_id = args.site if args.site != "default" else settings.bacnet_site_id

    if not settings.bacnet_scrape_enabled:
        log.warning(
            "BACnet scrape disabled. Set OFDD_BACNET_SCRAPE_ENABLED=true to enable."
        )
        return 0

    def _run_single() -> dict:
        data_model_site = None if site_id == "default" else site_id
        return run_bacnet_scrape_data_model(
            site_id=data_model_site, server_url=settings.bacnet_server_url
        )

    if args.loop:
        interval_min = _current_interval_min(log)
        log.info(
            "BACnet scrape loop (data model): site=%s interval=%d min (API/env/default precedence)",
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
            except Exception:
                log.exception("Scrape failed")

            time.sleep(interval_sec)

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
