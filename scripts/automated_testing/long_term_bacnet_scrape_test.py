#!/usr/bin/env python3
"""
Long-run BACnet scrape interval test: 1h @ 1 min, 1h @ 5 min, 1h @ 10 min, confirm, repeat.

What gets checked
-----------------
Frontend (browser / Selenium):
  - Config: with --config-via-frontend, opens /config, sets BACnet scrape interval (min), clicks Save, asserts "Saved" appears.
  - Faults: with --check-faults-via-frontend, opens /faults, asserts the page shows either the active fault table (rows), the empty state, or the "Fault flags over time" chart/summary.

Backend (Python → API via httpx):
  - Startup: GET /config (API reachable and auth when OFDD_API_KEY is set).
  - After each phase: GET /config to confirm bacnet_scrape_interval_min (whether config was set via frontend or API).
  - Scrape count: GET /download/csv for a date range; count distinct timestamps before vs after the 1h wait; assert "new scrapes this hour" is in the expected range (e.g. 55–65 for 1 min interval). This validates the BACnet scraper is running at the set interval.
  - Faults (optional): with --check-faults, GET /download/faults; assert fault flags (e.g. flatline_flag, bad_sensor_flag) fall in the expected UTC windows from fault_schedule.py.

Usage
-----
  python long_term_bacnet_scrape_test.py --once --config-via-frontend --check-faults-via-frontend --frontend-url http://192.168.204.16 --headed

  python long_term_bacnet_scrape_test.py --once --config-via-frontend --check-faults-via-frontend --frontend-url http://192.168.204.16 --api-url http://192.168.204.16:8000 --headed
  $env:OFDD_API_KEY = "same-as-server-stack-.env"
"""

import csv
import io
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING

try:
    import httpx
except ImportError:
    httpx = None

if TYPE_CHECKING:
    from selenium.webdriver.chrome.webdriver import WebDriver


def _load_env_file(path: str) -> None:
    """Load KEY=VALUE lines from path into os.environ (only if key not already set)."""
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as f:
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


def _load_stack_env() -> None:
    """Load stack/.env (when run from repo) then .env in cwd/script dir so OFDD_API_KEY is set for remote test bench."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(script_dir)
    _load_env_file(os.path.join(repo_root, "stack", ".env"))
    _load_env_file(os.path.join(os.getcwd(), ".env"))
    _load_env_file(os.path.join(script_dir, ".env"))


_load_stack_env()

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000").rstrip("/")
# When running from a remote test bench, pass --api-url so the script talks to the Open FDD API (not localhost).
_API_BASE_OVERRIDE = None
API_KEY = os.environ.get("OFDD_API_KEY", "").strip()
SITE_ID = os.environ.get("OFDD_BACNET_SITE_ID", "default")
FRONTEND_URL_DEFAULT = os.environ.get("FRONTEND_URL", "").strip().rstrip("/")

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
    base = _API_BASE_OVERRIDE if _API_BASE_OVERRIDE is not None else BASE_URL
    url = f"{base}{path}"
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


def _get_selenium_driver(headed: bool = False):
    """Lazy import and create Chrome WebDriver (same fashion as e2e_frontend_selenium)."""
    try:
        from e2e_frontend_selenium import get_driver
        return get_driver(headed=headed)
    except ImportError as e:
        print(
            "For --config-via-frontend / --check-faults-via-frontend install: pip install selenium webdriver-manager",
            file=sys.stderr,
        )
        raise SystemExit(1) from e


def set_bacnet_interval_via_frontend(driver: "WebDriver", frontend_url: str, interval_min: int) -> bool:
    """
    Open Config page, set BACnet scrape interval (min), click Save. Returns True on success.
    Uses data-testid=config-bacnet-scrape-interval and data-testid=config-save-button.
    """
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait
    from e2e_frontend_selenium import ELEMENT_WAIT, safe_send_keys, wait_for_clickable

    base = frontend_url.rstrip("/")
    driver.get(f"{base}/config")
    wait = WebDriverWait(driver, ELEMENT_WAIT)
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "[data-testid=config-bacnet-scrape-interval]")))
    time.sleep(0.3)
    inp = driver.find_element(By.CSS_SELECTOR, "[data-testid=config-bacnet-scrape-interval]")
    safe_send_keys(inp, str(interval_min), clear_first=True)
    btn = wait_for_clickable(driver, By.CSS_SELECTOR, "[data-testid=config-save-button]")
    btn.click()
    wait.until(
        lambda d: "Saved" in (d.page_source or "") or "Save failed" in (d.page_source or "") or "error" in (d.page_source or "").lower()
    )
    if "Saved" in (driver.page_source or ""):
        return True
    return False


def verify_faults_visible_via_frontend(driver: "WebDriver", frontend_url: str, timeout_sec: float = 30) -> tuple[bool, str]:
    """
    Open Faults page and assert fault data is visible (active table with rows, or chart/summary).
    Returns (ok, message). Waits up to timeout_sec for faults to appear (FDD may run after scrape).
    """
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait
    from e2e_frontend_selenium import ELEMENT_WAIT

    base = frontend_url.rstrip("/")
    driver.get(f"{base}/faults")
    wait = WebDriverWait(driver, timeout_sec)
    # Wait for page to load: either fault table with rows or empty state or chart section
    try:
        wait.until(
            lambda d: (
                d.find_elements(By.CSS_SELECTOR, "[data-testid=faults-active-table] tbody tr")
                or d.find_elements(By.CSS_SELECTOR, "[data-testid=faults-empty-state]")
                or "Fault flags over time" in (d.page_source or "")
            )
        )
    except Exception as e:
        return False, f"Faults page did not load or show table/chart within {timeout_sec}s: {e}"
    rows = driver.find_elements(By.CSS_SELECTOR, "[data-testid=faults-active-table] tbody tr")
    if rows:
        return True, f"Faults page shows {len(rows)} active fault row(s) (Open FDD calculated faults)."
    if "Fault flags over time" in (driver.page_source or ""):
        return True, "Faults page loaded; chart/summary visible (fault data may be in range)."
    return False, "Faults page loaded but no fault table rows and no chart section found."


def _parse_frontend_args():
    """Parse --frontend-url, --api-url, and --headed from argv; return (frontend_url, headed, api_url)."""
    url = FRONTEND_URL_DEFAULT
    api_url = None
    headed = False
    args = list(sys.argv[1:])
    i = 0
    while i < len(args):
        if args[i] == "--frontend-url" and i + 1 < len(args):
            url = (args[i + 1] or "").strip().rstrip("/")
            i += 2
            continue
        if args[i] == "--api-url" and i + 1 < len(args):
            api_url = (args[i + 1] or "").strip().rstrip("/")
            i += 2
            continue
        if args[i] == "--headed":
            headed = True
            i += 1
            continue
        i += 1
    return url, headed, api_url


def main() -> int:
    once = "--once" in sys.argv or os.environ.get("OFDD_INTERVAL_TEST_ONCE") == "1"
    check_faults = "--check-faults" in sys.argv or os.environ.get("OFDD_CHECK_FAULTS") == "1"
    config_via_frontend = "--config-via-frontend" in sys.argv or os.environ.get("OFDD_CONFIG_VIA_FRONTEND") == "1"
    check_faults_via_frontend = "--check-faults-via-frontend" in sys.argv or os.environ.get("OFDD_CHECK_FAULTS_VIA_FRONTEND") == "1"
    frontend_url, headed, api_url = _parse_frontend_args()
    # When using frontend from a remote test bench, infer API URL from frontend URL if not set (Caddy: :80 = frontend, :8000 = API).
    if (config_via_frontend or check_faults_via_frontend) and frontend_url and not api_url:
        try:
            from urllib.parse import urlparse
            p = urlparse(frontend_url)
            netloc = p.netloc or p.path
            if ":" in netloc:
                host = netloc.rsplit(":", 1)[0]
            else:
                host = netloc
            api_url = f"{p.scheme or 'http'}://{host}:8000"
            print(f"API URL (inferred from --frontend-url): {api_url}")
        except Exception:
            api_url = None
    if api_url:
        global _API_BASE_OVERRIDE
        _API_BASE_OVERRIDE = api_url

    if (config_via_frontend or check_faults_via_frontend) and not frontend_url:
        print(
            "When using --config-via-frontend or --check-faults-via-frontend set --frontend-url or FRONTEND_URL.",
            file=sys.stderr,
        )
        return 1

    if not httpx:
        print("Install httpx for API checks: pip install httpx", file=sys.stderr)
        return 1

    # Optional: create Selenium driver for frontend flows (same fashion as e2e_frontend_selenium)
    driver = None
    if config_via_frontend or check_faults_via_frontend:
        try:
            driver = _get_selenium_driver(headed=headed)
            print(f"Frontend: {frontend_url}  (config via UI={config_via_frontend}, faults via UI={check_faults_via_frontend})")
        except SystemExit:
            raise
        except Exception as e:
            print(f"Selenium driver failed: {e}", file=sys.stderr)
            return 1

    try:
        # Startup: require API reachable and auth if key is set
        api_base = _API_BASE_OVERRIDE if _API_BASE_OVERRIDE is not None else BASE_URL
        try:
            code, body = _request("GET", "/config")
        except Exception as e:
            err = str(e).lower()
            if "refused" in err or "connection" in err or "10061" in err:
                print(
                    "API connection refused. When running from a remote test bench, point to the Open FDD API:",
                    file=sys.stderr,
                )
                print("  --api-url http://OPENFDD_SERVER:8000   (or set BASE_URL)", file=sys.stderr)
                print("  Example: --api-url http://192.168.204.16:8000", file=sys.stderr)
                return 1
            raise
        if code == 401:
            print("API returned 401 (auth required).", file=sys.stderr)
            print("  Set OFDD_API_KEY to the same value as on the Open FDD server (stack/.env):", file=sys.stderr)
            print("    PowerShell:  $env:OFDD_API_KEY = \"paste-key-here\"", file=sys.stderr)
            print("    Or create a .env file in this folder with:  OFDD_API_KEY=paste-key-here", file=sys.stderr)
            return 1
        if code != 200:
            print(f"API not reachable at {api_base} (GET /config -> {code}). Check --api-url or BASE_URL.", file=sys.stderr)
            return 1
        print(f"API OK: {api_base}  site_id={SITE_ID}  (interval test)")
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

                # 1. Update Config (API or frontend)
                if config_via_frontend and driver:
                    print(f"  Config via frontend: bacnet_scrape_interval_min={interval_min}")
                    if not set_bacnet_interval_via_frontend(driver, frontend_url, interval_min):
                        print("  Config via frontend: Save failed or 'Saved' not seen.", file=sys.stderr)
                        continue
                else:
                    print(f"  PUT /config: bacnet_scrape_interval_min={interval_min}")
                    if not put_config_interval(interval_min):
                        print("  PUT /config failed.", file=sys.stderr)
                        continue

                cfg = get_config()
                if cfg is not None:
                    current = cfg.get("bacnet_scrape_interval_min")
                    print(f"  GET /config confirmed value: {current}")

                # 2. Get baseline timestamp count
                start_d = date.today() - timedelta(days=2)
                end_d = date.today() + timedelta(days=1)
                count_before, _ = get_download_csv_distinct_timestamps(start_d, end_d)
                print(f"  Baseline total timestamps before wait: {count_before}")

                # 3. Wait
                print(f"  Waiting {duration_sec // 60} min...")
                time.sleep(duration_sec)

                # 4. Get post-wait timestamp count
                count_after, preview = get_download_csv_distinct_timestamps(start_d, end_d)
                actual_scrapes = count_after - count_before
                ok = min_ts <= actual_scrapes <= max_ts
                status = "OK" if ok else "FAIL"
                print(f"  Total timestamps after wait: {count_after}")
                print(f"  -> NEW scrapes this hour: {actual_scrapes}")
                print(f"  -> Expected between {min_ts} and {max_ts} scrapes")
                print(f"  -> Result: {status}\n")
                if not ok and preview:
                    print(f"  Response preview: {preview[:150]}...")

                # Optional: verify FDD reported faults (API)
                if check_faults:
                    phase_end_utc = datetime.now(timezone.utc)
                    fault_ok, fault_msg = _check_expected_faults_for_phase(phase_end_utc)
                    print(f"  Expected-fault check (API): {'OK' if fault_ok else 'FAIL'} — {fault_msg}")

                # Optional: verify faults visible on frontend (fake devices + FDD → Faults page)
                if check_faults_via_frontend and driver:
                    fault_visible_ok, fault_visible_msg = verify_faults_visible_via_frontend(driver, frontend_url)
                    print(f"  Faults via frontend: {'OK' if fault_visible_ok else 'FAIL'} — {fault_visible_msg}")

            print("--- Confirm: cycle complete ---")
            cfg = get_config()
            if cfg:
                print(f"  GET /config ending value: {cfg.get('bacnet_scrape_interval_min')}")

            if once:
                print("One cycle done (--once). Exiting.")
                return 0
            print("Starting next cycle...\n")
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())