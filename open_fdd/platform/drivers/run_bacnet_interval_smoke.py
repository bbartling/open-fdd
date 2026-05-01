"""
Short-interval BACnet ingest smoke (bridge mode).

For long production-style interval tests, use afdd-stack's
``run_bacnet_scrape_interval_test`` against a full stack DB. This module is a
**quick** loop against the open-fdd bridge ``POST /ingest/bacnet`` to verify
connectivity and timing without waiting hours.

Usage::

    OFDD_BACNET_SITE_ID=<uuid> \\
    OFDD_BRIDGE_URL=http://127.0.0.1:8765 \\
    python -m open_fdd.platform.drivers.run_bacnet_interval_smoke --iterations 3 --sleep 2
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time

from open_fdd.platform.drivers.headless_bacnet import run_bridge_once

_log = logging.getLogger(__name__)


def _safe_int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return int(str(raw).strip(), 10)
    except (TypeError, ValueError):
        _log.warning("Invalid %s=%r; using default %s", name, raw, default)
        return default


def _safe_float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return float(str(raw).strip())
    except (TypeError, ValueError):
        _log.warning("Invalid %s=%r; using default %s", name, raw, default)
        return default


def main(argv: list[str] | None = None) -> None:
    bridge_env = (os.getenv("OFDD_BRIDGE_URL", "") or "").strip()
    bridge_default = (bridge_env or "http://127.0.0.1:8765").rstrip("/")
    p = argparse.ArgumentParser(description="Smoke: repeated bridge BACnet ingest with short sleep.")
    p.add_argument(
        "--iterations",
        type=int,
        default=_safe_int_env("OFDD_BACNET_SMOKE_ITERATIONS", 3),
    )
    p.add_argument(
        "--sleep",
        type=float,
        default=_safe_float_env("OFDD_BACNET_SMOKE_SLEEP_SEC", 2.0),
    )
    p.add_argument("--bridge-url", default=bridge_default)
    p.add_argument("--site-id", default=os.getenv("OFDD_BACNET_SITE_ID", "").strip())
    args = p.parse_args(argv)
    if not args.site_id:
        print("need --site-id or OFDD_BACNET_SITE_ID", file=sys.stderr)
        raise SystemExit(2)
    n = max(1, int(args.iterations))
    delay = max(0.0, float(args.sleep))
    for i in range(1, n + 1):
        out = run_bridge_once(
            bridge=args.bridge_url,
            site_id=args.site_id,
            server_url=None,
            api_key=None,
        )
        print(i, json.dumps(out, default=str), flush=True)
        if i < n and delay:
            time.sleep(delay)


if __name__ == "__main__":
    main()
