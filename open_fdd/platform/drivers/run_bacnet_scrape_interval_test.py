#!/usr/bin/env python3
"""
Long-run BACnet scrape interval test: 1h @ 1 min, 1h @ 5 min, 1h @ 10 min, confirm, repeat.

Production-style: only the CRUD API. At each phase we PUT /config to set
bacnet_scrape_interval_min (1, 5, 10); the data model (config/data_model.ttl) is updated.
After each 1h wait we validate by comparing the total distinct timestamps BEFORE 
and AFTER the wait to see exactly how many scrapes occurred in that specific window.

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

# Phases: (interval_min, duration_sec, min_expected_scrapes, max_expected_scrapes)
# Added max_expected so we catch if the scraper is running TOO fast (e.g. stuck at 1min)
PHASES = [
    (1, 60 * 60, 55, 65),   # Expect ~60 scrapes
    (5, 60 * 60, 10, 15),   # Expect ~12 scrapes
    (10, 60 * 60, 4, 8),    # Expect ~6 scrapes
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
        print(f"\n=======================")
        print(f"=== Cycle {cycle} ===")
        print(f"=======================\n")
        
        for interval_min, duration_sec, min_ts, max_ts in PHASES:
            print(f"--- Phase: {interval_min} min interval ---")
            
            # 1. Update Config
            print(f"  PUT /config: bacnet_scrape_interval_min={interval_min}")
            if not put_config_interval(interval_min):
                print(f"  PUT /config failed.", file=sys.stderr)
                continue
                
            cfg = get_config()
            if cfg is not None:
                current = cfg.get("bacnet_scrape_interval_min")
                print(f"  GET /config confirmed value: {current}")

            # 2. Get baseline timestamp count
            # Use a wide date range to ensure we don't miss anything if crossing midnight
            start_d = date.today() - timedelta(days=2)
            end_d = date.today() + timedelta(days=1)
            
            count_before, _ = get_download_csv_distinct_timestamps(start_d, end_d)
            print(f"  Baseline total timestamps before wait: {count_before}")

            # 3. Wait
            print(f"  Waiting {duration_sec // 60} min...")
            time.sleep(duration_sec)

            # 4. Get post-wait timestamp count
            count_after, preview = get_download_csv_distinct_timestamps(start_d, end_d)
            
            # 5. Calculate exactly how many scrapes happened
            actual_scrapes = count_after - count_before
            
            # 6. Validate
            ok = min_ts <= actual_scrapes <= max_ts
            status = "OK" if ok else "FAIL"
            
            print(f"  Total timestamps after wait: {count_after}")
            print(f"  -> NEW scrapes this hour: {actual_scrapes}")
            print(f"  -> Expected between {min_ts} and {max_ts} scrapes")
            print(f"  -> Result: {status}\n")
            
            if not ok and preview:
                print(f"  Response preview: {preview[:150]}...")

        print("--- Confirm: cycle complete ---")
        cfg = get_config()
        if cfg:
            current = cfg.get("bacnet_scrape_interval_min")
            print(f"  GET /config ending value: {current}")
            
        if once:
            print("One cycle done (--once). Exiting.")
            return 0
            
        print("Starting next cycle...\n")


if __name__ == "__main__":
    sys.exit(main())