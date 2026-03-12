#!/usr/bin/env python3
"""
Long-run BACnet scrape interval test: 1h @ 1 min, 1h @ 5 min, 1h @ 10 min, confirm, repeat.

What gets checked
-----------------
Frontend (browser / Selenium):
  - Config: with --config-via-frontend, opens /config, sets BACnet scrape interval (min), clicks Save, asserts "Saved" appears.
  - Faults: with --check-faults-via-frontend, opens /faults, asserts the page shows either the active fault table (rows), the empty state, or the "Fault flags over time" chart/summary.
  - Plots fault overlay: with --check-faults-via-frontend, opens /plots, selects site (from URL or selector), opens Add faults dropdown, selects a fault if any, and asserts the chart updates (fault swim lane / overlay parity with Grafana "BACnet Plus Fault Data").

Backend (Python → API via httpx):
  - Startup: GET /config (API reachable and auth when OFDD_API_KEY is set).
  - After each phase: GET /config to confirm bacnet_scrape_interval_min (whether config was set via frontend or API).
  - Scrape count: GET /download/csv for a date range; count distinct timestamps before vs after the 1h wait; assert "new scrapes this hour" is in the expected range (e.g. 55–65 for 1 min interval). This validates the BACnet scraper is running at the set interval.
  - Faults (optional): with --check-faults, GET /download/faults; assert fault flags (e.g. flatline_flag, bad_sensor_flag) fall in the expected UTC windows from fault_schedule.py.

Usage
-----

    $env:OFDD_API_KEY = "same-as-server-stack/.env"
  python 3_long_term_bacnet_scrape_test.py --once --config-via-frontend --check-faults-via-frontend --frontend-url http://192.168.204.16 --headed

  python 3_long_term_bacnet_scrape_test.py --once --config-via-frontend --check-faults-via-frontend --frontend-url http://192.168.204.16 --api-url http://192.168.204.16:8000 --headed
  

  python 3_long_term_bacnet_scrape_test.py --config-via-frontend --check-faults-via-frontend --frontend-url http://192.168.204.16 --api-url http://192.168.204.16:8000 --headed

Not run by bootstrap.sh --test (that runs frontend lint+vitest and backend pytest only). Run this script separately when validating scrape intervals or frontend config/faults from a test bench.
"""

import csv
import io
import os
import sys
import time
import importlib.util
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

try:
    import httpx
except ImportError:
    httpx = None

if TYPE_CHECKING:
    from selenium.webdriver.chrome.webdriver import WebDriver

# E2E Selenium module: normal import or load from 1_e2e_frontend_selenium.py when that file exists
# (Python can't import module names that start with a digit, so we load by path when needed)
_E2E_MOD = None


def _ensure_e2e_module():
    """Load e2e_frontend_selenium (or 1_e2e_frontend_selenium.py by path) for driver and helpers."""
    global _E2E_MOD
    if _E2E_MOD is not None:
        return _E2E_MOD
    try:
        import e2e_frontend_selenium as _E2E_MOD
    except ImportError:
        pass
    if _E2E_MOD is None:
        script_dir = Path(__file__).resolve().parent
        for candidate in ("1_e2e_frontend_selenium.py", "e2e_frontend_selenium.py"):
            path = script_dir / candidate
            if path.is_file():
                spec = importlib.util.spec_from_file_location("_e2e_selenium", path)
                if spec and spec.loader:
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    globals()["_E2E_MOD"] = mod
                    _E2E_MOD = mod
                    break
    if _E2E_MOD is None:
        print(
            "For --config-via-frontend / --check-faults-via-frontend install: pip install selenium webdriver-manager",
            file=sys.stderr,
        )
        print(
            "If already installed, ensure e2e_frontend_selenium.py or 1_e2e_frontend_selenium.py is in the same directory as this script.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    return _E2E_MOD


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


def get_first_site_id() -> str:
    """GET /sites; return first site id for Plots/context, or 'default' if none."""
    code, body = _request("GET", "/sites")
    if code != 200 or not isinstance(body, list) or len(body) == 0:
        return "default"
    first = body[0]
    if isinstance(first, dict) and first.get("id"):
        return str(first["id"])
    return "default"


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


def _get_selenium_driver(headed: bool = False, capture_browser_logs: bool = False):
    """Lazy import and create Chrome WebDriver (same fashion as e2e_frontend_selenium)."""
    mod = _ensure_e2e_module()
    return mod.get_driver(headed=headed, capture_browser_logs=capture_browser_logs)


def _report_console_errors(driver: "WebDriver", route_name: str) -> None:
    """If the driver has browser log capture enabled, fetch console errors/warnings and print them."""
    try:
        mod = _ensure_e2e_module()
        entries = mod.get_browser_console_errors(driver)
        if entries:
            print(f"  Browser console on {route_name}: {len(entries)} error(s)/warning(s)")
            for e in entries:
                level = e.get("level", "?")
                msg = (e.get("message") or "").strip()
                if msg:
                    print(f"    [{level}] {msg[:200]}{'...' if len(msg) > 200 else ''}")
    except Exception as ex:
        print(f"  Browser console on {route_name}: could not read logs ({ex})", file=sys.stderr)


def _ensure_driver_alive(
    driver: "WebDriver | None", headed: bool, capture_browser_logs: bool = False
) -> "WebDriver | None":
    """
    Return a valid driver for frontend checks. After a long wait (e.g. 60 min) the browser
    may have closed; if the session is dead, create a new driver and quit the old one.
    """
    if driver is None:
        return None
    try:
        _ = driver.current_url
        return driver
    except Exception:
        try:
            new_driver = _get_selenium_driver(headed=headed, capture_browser_logs=capture_browser_logs)
            try:
                driver.quit()
            except Exception:
                pass
            print("  Browser session lost during wait; reconnected with new driver for frontend checks.")
            return new_driver
        except Exception as e:
            print(f"  Could not reconnect browser for frontend checks: {e}", file=sys.stderr)
            return None


def set_bacnet_interval_via_frontend(driver: "WebDriver", frontend_url: str, interval_min: int) -> bool:
    """
    Open Config page, set BACnet scrape interval (min), click Save. Returns True on success.
    Uses data-testid=config-bacnet-scrape-interval and data-testid=config-save-button.
    """
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait
    mod = _ensure_e2e_module()
    ELEMENT_WAIT = mod.ELEMENT_WAIT
    safe_send_keys = mod.safe_send_keys
    wait_for_clickable = mod.wait_for_clickable

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
    mod = _ensure_e2e_module()
    ELEMENT_WAIT = mod.ELEMENT_WAIT

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


def verify_plots_fault_plot_via_frontend(
    driver: "WebDriver", frontend_url: str, timeout_sec: float = 25
) -> tuple[bool, str]:
    """
    Open Plots page, select site (via URL or selector), open Add faults dropdown, select a fault
    if any exist, and verify the chart updates (fault overlay path works — swim lane parity with Grafana).
    Returns (ok, message). If no fault definitions exist, still passes (picker works).
    """
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait
    mod = _ensure_e2e_module()
    ELEMENT_WAIT = mod.ELEMENT_WAIT
    wait_for_clickable = mod.wait_for_clickable

    base = frontend_url.rstrip("/")
    site_id = get_first_site_id()
    driver.get(f"{base}/plots?site={site_id}")
    wait = WebDriverWait(driver, timeout_sec)
    time.sleep(0.5)

    # If we landed on "Select a site to view plots", try opening site selector and picking first site
    if "Select a site to view plots" in (driver.page_source or ""):
        try:
            site_btn = driver.find_elements(
                By.XPATH,
                "//button[@aria-haspopup='listbox' and (contains(., 'Sites') or contains(., 'All Sites'))]",
            )
            if site_btn:
                site_btn[0].click()
                time.sleep(0.5)
                first_site = driver.find_elements(
                    By.XPATH,
                    "//div[contains(@class,'rounded-2xl')]//button[.//span[contains(@class,'truncate')]]",
                )
                for el in first_site:
                    if el.text and "All Sites" not in (el.text or ""):
                        el.click()
                        break
                time.sleep(0.8)
        except Exception:
            pass

    # Wait for Plots content: fault picker or chart container (site selected)
    try:
        wait.until(
            lambda d: (
                d.find_elements(By.CSS_SELECTOR, "[data-testid=plots-fault-picker]")
                or d.find_elements(By.CSS_SELECTOR, "[data-testid=plots-chart-container]")
            )
        )
    except Exception as e:
        return False, f"Plots page did not show fault picker or chart within {timeout_sec}s: {e}"

    # Still on "Select a site" means we have no site in context
    if "Select a site to view plots" in (driver.page_source or ""):
        return False, "Plots page requires a site; site selector did not apply."

    # Open Add faults dropdown
    try:
        fault_btn = wait_for_clickable(driver, By.CSS_SELECTOR, "[data-testid=plots-fault-picker]", timeout_sec)
        fault_btn.click()
        time.sleep(0.6)
    except Exception as e:
        return False, f"Could not open Add faults dropdown: {e}"

    page_src = driver.page_source or ""
    if "No fault definitions" in page_src:
        driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
        return True, "Plots fault picker OK; no fault definitions to plot (add rules and run FDD)."

    # Select first fault option (label with checkbox)
    try:
        first_label = driver.find_elements(
            By.XPATH,
            "//div[contains(@class,'absolute') and contains(@class,'z-50')]//label[.//input[@type='checkbox']]",
        )
        if not first_label:
            first_label = driver.find_elements(By.XPATH, "//label[.//input[@type='checkbox']]")
        if first_label:
            first_label[0].click()
            time.sleep(0.5)
    except Exception:
        pass
    driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
    time.sleep(1.2)

    # Chart should update: either "No fault activity in this range" or chart with bands / zoom hint
    container = driver.find_elements(By.CSS_SELECTOR, "[data-testid=plots-chart-container]")
    if not container:
        return False, "Plots chart container not found after selecting fault."
    text = (container[0].text or "") + " " + (driver.page_source or "")
    if "No fault activity in this range" in text or "Zoom: drag the handles" in text:
        return True, "Plots fault overlay path OK (fault selected; chart shows fault state or zoom)."
    if "No point data in this range" in text:
        return True, "Plots fault overlay path OK (fault selected; no point data in range)."
    if "Select points and/or faults" not in text:
        return True, "Plots fault overlay path OK (chart updated after selecting fault)."
    return False, "Plots fault selection did not update chart (swim lane / fault overlay may be broken)."


def verify_plots_axis_by_unit_via_frontend(
    driver: "WebDriver", frontend_url: str, timeout_sec: float = 25
) -> tuple[bool, str]:
    """
    On Plots, select two points with different units (e.g. SA-T degF, SA-FLOW cfm) and assert
    the chart has at least 2 Y-axes (axis-by-unit: data populates on different axes by unit).
    Returns (ok, message). Uses e2e_frontend_selenium helpers.
    """
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait

    mod = _ensure_e2e_module()
    ELEMENT_WAIT = mod.ELEMENT_WAIT
    EXPECTED_POINT_NAMES = mod.EXPECTED_POINT_NAMES
    FALLBACK_POINT_NAMES = mod.FALLBACK_POINT_NAMES
    SECOND_POINT_DIFFERENT_UNIT = mod.SECOND_POINT_DIFFERENT_UNIT
    select_known_point = mod.select_known_point
    select_second_point_different_unit = mod.select_second_point_different_unit

    base = frontend_url.rstrip("/")
    site_id = get_first_site_id()
    driver.get(f"{base}/plots?site={site_id}")
    time.sleep(0.8)
    # If URL param didn't apply, try site selector (same as fault overlay)
    if "Select a site to view plots" in (driver.page_source or ""):
        try:
            site_btn = driver.find_elements(
                By.XPATH,
                "//button[@aria-haspopup='listbox' and (contains(., 'Sites') or contains(., 'All Sites'))]",
            )
            if site_btn:
                site_btn[0].click()
                time.sleep(0.5)
                first_site = driver.find_elements(
                    By.XPATH,
                    "//div[contains(@class,'rounded-2xl')]//button[.//span[contains(@class,'truncate')]]",
                )
                for el in first_site:
                    if el.text and "All Sites" not in (el.text or ""):
                        el.click()
                        break
                time.sleep(0.8)
        except Exception:
            pass
    if "Select a site to view plots" in (driver.page_source or ""):
        return False, "Plots axis-by-unit: select a site first (no site in context)."
    wait = WebDriverWait(driver, timeout_sec)
    wait.until(
        lambda d: "Select points" in (d.page_source or "") or d.find_elements(By.CSS_SELECTOR, "[class*='recharts-yAxis']")
    )
    preference = list(EXPECTED_POINT_NAMES) + list(FALLBACK_POINT_NAMES)
    first = select_known_point(driver, preference, timeout=ELEMENT_WAIT)
    if not first:
        return False, "Plots axis-by-unit: could not select first point (point picker)."
    time.sleep(0.4)
    second = select_second_point_different_unit(driver, preference=SECOND_POINT_DIFFERENT_UNIT, timeout=ELEMENT_WAIT)
    if not second:
        return True, "Plots axis-by-unit: only one unit available (single point type); skip multi-axis check."
    time.sleep(1.0)
    y_axes = driver.find_elements(By.CSS_SELECTOR, "[class*='recharts-yAxis']")
    if len(y_axes) >= 2:
        return True, f"Plots axis-by-unit OK ({len(y_axes)} Y-axes for different units)."
    return False, f"Plots axis-by-unit: expected >= 2 Y-axes when two units selected; got {len(y_axes)}."


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
            driver = _get_selenium_driver(
                headed=headed,
                capture_browser_logs=True,
            )
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
                    _report_console_errors(driver, "Config")
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
                # After a long wait the browser may have closed; reconnect if session is dead.
                if check_faults_via_frontend and driver:
                    driver = _ensure_driver_alive(
                        driver, headed, capture_browser_logs=True
                    )
                    if driver:
                        fault_visible_ok, fault_visible_msg = verify_faults_visible_via_frontend(driver, frontend_url)
                        print(f"  Faults via frontend: {'OK' if fault_visible_ok else 'FAIL'} — {fault_visible_msg}")
                        _report_console_errors(driver, "Faults")
                        # Plots tab: site selector + Add faults dropdown → fault overlay on chart (Grafana swim lane parity)
                        plots_ok, plots_msg = verify_plots_fault_plot_via_frontend(driver, frontend_url)
                        print(f"  Plots fault plot: {'OK' if plots_ok else 'FAIL'} — {plots_msg}")
                        _report_console_errors(driver, "Plots (fault overlay)")
                        # Plots: axis-by-unit — two points with different units → multiple Y-axes
                        axis_ok, axis_msg = verify_plots_axis_by_unit_via_frontend(driver, frontend_url)
                        print(f"  Plots axis-by-unit: {'OK' if axis_ok else 'FAIL'} — {axis_msg}")
                        _report_console_errors(driver, "Plots (axis-by-unit)")
                    else:
                        print("  Faults via frontend: SKIP — browser session lost and could not reconnect.")

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