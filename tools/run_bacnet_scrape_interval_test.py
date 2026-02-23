#!/usr/bin/env python3
"""
Long-run BACnet scrape interval test: 1h @ 1 min, 1h @ 5 min, 1h @ 10 min, confirm, repeat.

Production-style: only the CRUD API. At each phase we PUT /config to set
bacnet_scrape_interval_min (1, 5, 10); the data model (config/data_model.ttl) is updated.
After each 1h wait we validate via GET /config and GET /download/csv (distinct scrape
timestamps). The running bacnet-scraper (Docker openfdd_bacnet_scraper) must pick up
the new interval (e.g. from TTL or by restarting so env is applied).

Usage:
  BASE_URL=http://192.168.204.16:8000 python tools/run_bacnet_scrape_interval_test.py
  BASE_URL=http://192.168.204.16:8000 python tools/run_bacnet_scrape_interval_test.py --once
"""

import csv
import io
import os
import sys
import time
from datetime import date, timedelta

try:
    import httpx
except ImportError:
    httpx = None

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000").rstrip("/")
SITE_ID = os.environ.get("OFDD_BACNET_SITE_ID", "default")

# Phases: (interval_min, duration_sec, min_distinct_timestamps_for_pass)
PHASES = [
    (1, 60 * 60, 55),
    (5, 60 * 60, 11),
    (10, 60 * 60, 5),
]


def _request(method: str, path: str, json_body: dict | None = None):
    url = f"{BASE_URL}{path}"
    if httpx:
        with httpx.Client(timeout=30.0) as client:
            r = client.request(method, url, json=json_body)
            try:
                return r.status_code, r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text
            except Exception:
                return r.status_code, r.text
    import urllib.request
    import urllib.error
    import json as _json
    data = _json.dumps(json_body).encode() if json_body else None
    req = urllib.request.Request(url, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30.0) as res:
            body = res.read().decode()
            return res.status, _json.loads(body) if "application/json" in res.headers.get("Content-Type", "") else body
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode() if e.fp else ""


def put_config_interval(interval_min: int) -> bool:
    """PUT /config with bacnet_scrape_interval_min. Returns True if 200."""
    code, body = _request("PUT", "/config", json_body={"bacnet_scrape_interval_min": interval_min})
    return code == 200


def get_config() -> dict | None:
    """GET /config. Returns dict or None."""
    code, body = _request("GET", "/config")
    if code != 200 or not isinstance(body, dict):
        return None
    return body


def get_download_csv_distinct_timestamps(start_d: date, end_d: date) -> tuple[int, str]:
    """GET /download/csv and count distinct timestamp values. Returns (count, raw_body_preview)."""
    path = f"/download/csv?site_id={SITE_ID}&start_date={start_d}&end_date={end_d}&format=wide"
    code, body = _request("GET", path)
    if code != 200 or not body or not isinstance(body, str):
        return 0, (str(body)[:200] if body else "")
    lines = body.strip().splitlines()
    if len(lines) < 2:
        return 0, body[:200]
    reader = csv.reader(io.StringIO(body))
    header = next(reader)
    ts_col = 0
    for i, h in enumerate(header):
        if "timestamp" in (h or "").lower().replace("\ufeff", ""):
            ts_col = i
            break
    seen = set()
    for row in reader:
        if len(row) > ts_col and row[ts_col]:
            seen.add(row[ts_col].strip())
    return len(seen), body[:200]


def main() -> int:
    once = "--once" in sys.argv or os.environ.get("OFDD_INTERVAL_TEST_ONCE") == "1"

    if not httpx:
        print("Install httpx for API checks: pip install httpx", file=sys.stderr)
        return 1

    cycle = 0
    while True:
        cycle += 1
        print(f"\n=== Cycle {cycle} ===\n")
        for interval_min, duration_sec, min_ts in PHASES:
            print(f"--- Phase: {interval_min} min interval ---")
            print(f"  PUT /config: bacnet_scrape_interval_min={interval_min} (API/data model)")
            if not put_config_interval(interval_min):
                print(f"  PUT /config failed.", file=sys.stderr)
                continue
            cfg = get_config()
            if cfg is not None:
                current = cfg.get("bacnet_scrape_interval_min")
                print(f"  GET /config: bacnet_scrape_interval_min={current} (match scraper log 'interval=N min' or OFDD_BACNET_SCRAPE_INTERVAL_MIN)")
            print(f"  Waiting {duration_sec // 60} min...")
            time.sleep(duration_sec)

            end_d = date.today()
            start_d = end_d - timedelta(days=1)
            count, preview = get_download_csv_distinct_timestamps(start_d, end_d)
            ok = count >= min_ts
            status = "OK" if ok else "FAIL"
            print(f"  GET /download/csv distinct timestamps (last 24h): {count} (min {min_ts} for pass) — {status}")
            if not ok and preview:
                print(f"  Response preview: {preview[:150]}...")

        print("\n--- Confirm: cycle complete ---")
        cfg = get_config()
        if cfg:
            current = cfg.get("bacnet_scrape_interval_min")
            print(f"  GET /config: bacnet_scrape_interval_min={current} (same value scraper logs each cycle)")
        if once:
            print("One cycle done (--once). Exiting.")
            return 0
        print("Starting next cycle...\n")


if __name__ == "__main__":
    sys.exit(main())
