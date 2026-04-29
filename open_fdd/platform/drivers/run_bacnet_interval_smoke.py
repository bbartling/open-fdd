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
import os
import sys
import time

from open_fdd.platform.drivers.headless_bacnet import _run_bridge_once


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Smoke: repeated bridge BACnet ingest with short sleep.")
    p.add_argument("--iterations", type=int, default=int(os.getenv("OFDD_BACNET_SMOKE_ITERATIONS", "3")))
    p.add_argument("--sleep", type=float, default=float(os.getenv("OFDD_BACNET_SMOKE_SLEEP_SEC", "2")))
    p.add_argument("--bridge-url", default=os.getenv("OFDD_BRIDGE_URL", "http://127.0.0.1:8765").rstrip("/"))
    p.add_argument("--site-id", default=os.getenv("OFDD_BACNET_SITE_ID", "").strip())
    args = p.parse_args(argv)
    if not args.site_id:
        print("need --site-id or OFDD_BACNET_SITE_ID", file=sys.stderr)
        raise SystemExit(2)
    n = max(1, int(args.iterations))
    delay = max(0.0, float(args.sleep))
    for i in range(1, n + 1):
        out = _run_bridge_once(
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
