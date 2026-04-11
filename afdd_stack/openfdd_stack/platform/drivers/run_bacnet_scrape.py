#!/usr/bin/env python3
"""
Run BACnet scrape: RPC via diy-bacnet-server → TimescaleDB.

Addresses and object ids come only from the knowledge graph (points table populated
from TTL/import). Each scrape cycle loads polling points with BACnet metadata and
reads present-value via JSON-RPC.

Single gateway:
  OFDD_BACNET_SERVER_URL=http://localhost:8080 python -m openfdd_stack.platform.drivers.run_bacnet_scrape
  OFDD_BACNET_SITE_ID=building-a OFDD_DB_DSN=... python -m openfdd_stack.platform.drivers.run_bacnet_scrape --loop

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
from typing import Optional, TypedDict
import urllib.error
import urllib.request


class _PlatformConfigCache(TypedDict):
    """In-process cache for GET /config; values match _fetch_platform_config_cached."""

    ts: float
    cfg: Optional[dict]

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


_CONFIG_CACHE: _PlatformConfigCache = {"ts": 0.0, "cfg": None}


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


def _resolve_bacnet_gateways_json(log: logging.Logger) -> str | None:
    """
    Multi-gateway JSON: prefer GET /config (RDF/UI) so PUT /config applies without
    scraper restart; fall back to OFDD_BACNET_GATEWAYS / overlay env.
    """
    cfg = _fetch_platform_config(log)
    if cfg:
        raw = cfg.get("bacnet_gateways")
        if raw is not None:
            s = str(raw).strip()
            if s and s.lower() not in ("null", "string", "{}"):
                return s
    from openfdd_stack.platform.config import get_platform_settings

    g = (get_platform_settings().bacnet_gateways or "").strip()
    return g or None


def _current_interval_min(log: logging.Logger) -> int:
    from openfdd_stack.platform.config import get_platform_settings

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
    parser.add_argument(
        "--exit-nonzero-on-empty",
        action="store_true",
        help="In one-shot multi-gateway mode, return 1 when total rows and points are both zero",
    )
    args = parser.parse_args()

    setup_logging(args.verbose)
    log = logging.getLogger("open_fdd.bacnet")

    from openfdd_stack.platform.config import get_platform_settings
    from openfdd_stack.platform.drivers.bacnet import run_bacnet_scrape_data_model
    from openfdd_stack.platform.drivers.modbus_tcp import run_modbus_scrape_data_model

    settings = get_platform_settings()

    gateways_json = _resolve_bacnet_gateways_json(log)
    if gateways_json:
        try:
            gateways = json.loads(gateways_json)
        except (json.JSONDecodeError, TypeError) as e:
            log.error("bacnet_gateways invalid JSON: %s", e)
            return 1
        if not isinstance(gateways, list) or not gateways:
            log.error("bacnet_gateways must be a non-empty JSON array")
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

            # Re-read gateways each cycle so PUT /config can add/remove gateways.
            fresh_json = _resolve_bacnet_gateways_json(log)
            if fresh_json:
                try:
                    fresh_gateways = json.loads(fresh_json)
                    if isinstance(fresh_gateways, list) and fresh_gateways:
                        if fresh_gateways != gateways:
                            log.info(
                                "bacnet_gateways changed: %d -> %d entries",
                                len(gateways),
                                len(fresh_gateways),
                            )
                        gateways = fresh_gateways
                    else:
                        log.warning(
                            "bacnet_gateways JSON resolved to empty/non-list this cycle; keeping prior list"
                        )
                except (json.JSONDecodeError, TypeError):
                    log.warning("bacnet_gateways JSON invalid this cycle; keeping prior list")

            total_rows, total_points, total_errors = 0, 0, 0
            for gw in gateways:
                if not isinstance(gw, dict):
                    log.warning("Gateway entry must be an object: %s", gw)
                    continue
                url = (gw.get("url") or gw.get("server_url") or "").strip()
                raw_site = (gw.get("site_id") or "").strip()
                site_label = raw_site or "unscoped"
                data_model_site = (
                    None if not raw_site or raw_site.lower() == "default" else raw_site
                )
                if not url:
                    log.warning('Gateway missing "url" or "server_url": %s', gw)
                    continue

                try:
                    result = run_bacnet_scrape_data_model(
                        site_id=data_model_site, server_url=url
                    )
                except Exception:
                    log.exception("Gateway %s failed", site_label)
                    continue

                total_rows += result.get("rows_inserted", 0)
                total_points += result.get("points_created", 0)
                total_errors += len(result.get("errors", []))
                log.info(
                    "Gateway %s (%s): %d rows, %d points",
                    site_label,
                    url,
                    result.get("rows_inserted", 0),
                    result.get("points_created", 0),
                )

                try:
                    mres = run_modbus_scrape_data_model(
                        site_id=data_model_site, server_url=url
                    )
                    mr = mres.get("rows_inserted", 0)
                    total_rows += mr
                    me = mres.get("errors") or []
                    total_errors += len(me)
                    if mr or me:
                        log.info(
                            "Gateway %s Modbus: %d readings, %d errors",
                            site_label,
                            mr,
                            len(me),
                        )
                except Exception:
                    log.exception("Gateway %s Modbus scrape failed", site_label)

            if not args.loop:
                if (
                    args.exit_nonzero_on_empty
                    and total_rows == 0
                    and total_points == 0
                ):
                    return 1
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
        b = run_bacnet_scrape_data_model(
            site_id=data_model_site, server_url=settings.bacnet_server_url
        )
        m = run_modbus_scrape_data_model(
            site_id=data_model_site, server_url=settings.bacnet_server_url
        )
        errs = list(b.get("errors") or []) + list(m.get("errors") or [])
        return {
            "rows_inserted": int(b.get("rows_inserted", 0))
            + int(m.get("rows_inserted", 0)),
            "points_created": b.get("points_created", 0),
            "errors": errs,
        }

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
