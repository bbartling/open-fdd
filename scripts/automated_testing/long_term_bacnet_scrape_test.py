#!/usr/bin/env python3
"""
Long-run BACnet scrape interval test: 1h @ 1 min, 1h @ 5 min, 1h @ 10 min, confirm, repeat.

Production-style: only the CRUD API. At each phase we PUT /config to set
bacnet_scrape_interval_min (1, 5, 10); the scraper picks up the new interval from config.
After each 1h wait we validate by comparing the total distinct timestamps BEFORE
and AFTER the wait to see exactly how many scrapes occurred in that window.

Optional: when fake AHU/VAV devices use the deterministic fault schedule (see
scripts/fake_bacnet_devices/fault_schedule.py), pass --check-faults to verify that
Open FDD reported faults in the expected UTC windows (flatline 10–49 past the hour,
bounds 50–54 past the hour). Requires FDD loop to have run (e.g. rule_interval_hours).

Uses stack/.env for OFDD_API_KEY, BASE_URL, OFDD_BACNET_SITE_ID when run from repo root.

Usage:
  cd open-fdd && python scripts/automated_testing/long_term_bacnet_scrape_test.py
  cd open-fdd && python scripts/automated_testing/long_term_bacnet_scrape_test.py --once
  cd open-fdd && python scripts/automated_testing/long_term_bacnet_scrape_test.py --once --check-faults

  With explicit env (e.g. after sourcing stack/.env):
  export OFDD_API_KEY=... BASE_URL=http://localhost:8000
  python scripts/automated_testing/long_term_bacnet_scrape_test.py --once
"""

import csv
import io
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone

try:
    import httpx
except ImportError:
    httpx = None


def _load_stack_env() -> None:
    """Load stack/.env into os.environ so OFDD_API_KEY, BASE_URL, etc. are set."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(script_dir)
    env_path = os.path.join(repo_root, "stack", ".env")
    if not os.path.isfile(env_path):
        return
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip()
            if not key:
                continue
            if value.startswith('"') and value.endswith('"'):
                value = value[1:-1].replace('\\"', '"')
            elif value.startswith("'") and value.endswith("'"):
                value = value[1:-1].replace("\\'", "'")
            if key and os.environ.get(key) is None:
                os.environ[key] = value


_load_stack_env()

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000").rstrip("/")
API_KEY = os.environ.get("OFDD_API_KEY", "").strip()
SITE_ID = os.environ.get("OFDD_BACNET_SITE_ID", "default")

# Phases: (interval_min, duration_sec, min_expected_scrapes, max_expected_scrapes)
# Added max_expected so we catch if the scraper is running TOO fast (e.g. stuck at 1min)
PHASES = [
    (1, 60 * 60, 55, 65),   # Expect ~60 scrapes
    (5, 60 * 60, 10, 15),   # Expect ~12 scrapes
    (10, 60 * 60, 4, 8),    # Expect ~6 scrapes
]


def _headers() -> dict:
    """Headers for CRUD API; include Bearer token when OFDD_API_KEY is set."""
    h = {}
    if API_KEY:
        h["Authorization"] = f"Bearer {API_KEY}"
    return h


def _request(method: str, path: str, json_body: dict | None = None):
    url = f"{BASE_URL}{path}"
    headers = _headers()
    if json_body and "Content-Type" not in headers:
        headers["Content-Type"] = "application/json"

    if httpx:
        with httpx.Client(timeout=60.0) as client:
            r = client.request(method, url, json=json_body, headers=headers)
            try:
                return r.status_code, r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text
            except Exception:
                return r.status_code, r.text
    import urllib.request
    import urllib.error
    import json as _json
    data = _json.dumps(json_body).encode() if json_body else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    if data and "Content-Type" not in headers:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60.0) as res:
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


def get_download_faults(start_d: date, end_d: date) -> tuple[list[dict], str]:
    """GET /download/faults (JSON). Returns (list of fault dicts, error_message or '')."""
    path = f"/download/faults?site_id={SITE_ID}&start_date={start_d}&end_date={end_d}&format=json"
    code, body = _request("GET", path)
    if code != 200:
        return [], f"GET /download/faults -> {code}"
    if not isinstance(body, dict) or "faults" not in body:
        return [], "Response missing faults array"
    return body.get("faults", []), ""


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


def _check_expected_faults_for_phase(phase_end_utc: datetime) -> tuple[bool, str]:
    """
    Check that Open FDD reported faults in the expected UTC windows for the last hour.
    Schedule: flatline 10–49 past the hour, bounds 50–54 (see fault_schedule.py).
    Returns (ok, message).
    """
    # Import schedule from fake_bacnet_devices (same schedule the fake devices use)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    fake_dev_dir = os.path.abspath(os.path.join(script_dir, "..", "fake_bacnet_devices"))
    if fake_dev_dir not in sys.path:
        sys.path.insert(0, fake_dev_dir)
    try:
        from fault_schedule import expected_fault_windows_utc
    except ImportError as e:
        return False, f"Cannot import fault_schedule: {e}"

    start_utc = phase_end_utc - timedelta(hours=1)
    start_d = start_utc.date()
    end_d = phase_end_utc.date()
    if start_d != end_d:
        end_d = end_d + timedelta(days=1)  # span both days for query
    faults, err = get_download_faults(start_d, end_d)
    if err:
        return False, f"Faults fetch failed: {err}"

    windows = expected_fault_windows_utc(start_utc, phase_end_utc)
    # fault_id in API is the rule flag name, e.g. flatline_flag, bad_sensor_flag
    for fault_id, ranges in windows.items():
        if not ranges:
            continue
        # Collect fault timestamps for this fault_id (flag_value=1 only)
        fault_ts = []
        for f in faults:
            if f.get("fault_id") != fault_id or f.get("flag_value") != 1:
                continue
            ts = f.get("ts")
            if ts is None:
                continue
            if isinstance(ts, str):
                try:
                    # Assume UTC if no TZ in string
                    if ts.endswith("Z") or "+" in ts or ts.count("-") > 2:
                        fault_ts.append(datetime.fromisoformat(ts.replace("Z", "+00:00")))
                    else:
                        fault_ts.append(datetime.fromisoformat(ts).replace(tzinfo=timezone.utc))
                except Exception:
                    continue
            else:
                fault_ts.append(ts)
        for (win_start, win_end) in ranges:
            if any(win_start <= t <= win_end for t in fault_ts):
                break
        else:
            return False, f"Expected at least one {fault_id!r} in window {ranges[0]} (UTC); got {len(fault_ts)} in range"
    return True, "Expected fault windows present in FDD results"


def main() -> int:
    once = "--once" in sys.argv or os.environ.get("OFDD_INTERVAL_TEST_ONCE") == "1"
    check_faults = "--check-faults" in sys.argv or os.environ.get("OFDD_CHECK_FAULTS") == "1"

    if not httpx:
        print("Install httpx for API checks: pip install httpx", file=sys.stderr)
        return 1

    # Startup: require API reachable and auth if key is set
    code, body = _request("GET", "/config")
    if code == 401:
        print("API returned 401. Set OFDD_API_KEY (e.g. from stack/.env).", file=sys.stderr)
        return 1
    if code != 200:
        print(f"API not reachable at {BASE_URL} (GET /config -> {code}). Check BASE_URL.", file=sys.stderr)
        return 1
    print(f"API OK: {BASE_URL}  site_id={SITE_ID}  (interval test)")
    if API_KEY:
        print("  Using OFDD_API_KEY from env / stack/.env")
    else:
        print("  No OFDD_API_KEY set (auth disabled on server or local)")

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

            # Optional: verify FDD reported faults in expected schedule windows (fake devices use UTC minute schedule)
            if check_faults:
                phase_end_utc = datetime.now(timezone.utc)
                fault_ok, fault_msg = _check_expected_faults_for_phase(phase_end_utc)
                print(f"  Expected-fault check: {'OK' if fault_ok else 'FAIL'} — {fault_msg}")

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