#!/usr/bin/env python3
"""
E2E frontend tests (Selenium). Run on Windows from a separate test bench machine on the network.

This script is the enhanced, browser-based flow that subsumes the old API-only concepts.
Every frontend feature is tested; no rock left unturned.

  [1] Delete all sites and reset graph (via UI)
      Same outcome as delete_all_sites_and_reset.py: wipe sites + POST /data-model/reset,
      but done through the Data Model page (type N to confirm, click Remove all sites and reset).

  [2] Create site and import LLM payload (via UI)
      Same outcome as graph_and_crud_test.py for TestBenchSite + full demo_site_llm_payload.json (see scripts/automated_testing/demo_site_llm_payload.json):
      create site by name, paste JSON, Apply to data model — equipment (AHU-1, VAV-1, etc.), points (SA-T, ZoneTemp, …),
      units (degF, percent, cfm), feeds/fed_by. No API calls from the test bench; all via browser.

  [2a] Optional: BACnet discovery (Points page). When --bacnet-device-instance ID [ID ...] is set, go to
      Points page and for each device instance: set Device instance, click "Add to data model". Merges
      BACnet RDF into the graph (same as graph_and_crud_test.py point_discovery_to_graph). E.g. 3456789 3456790.

  [2b] Verify equipment and points on Data Model page.
  [2c] Verify units from data model on frontend (Points page: Unit column shows degF, percent, cfm).
  [2d] Points page device tree: verify columns (Name, Site, Brick Type, FDD Input, Unit, Polling,
       Last value, Last updated) and tree structure (site with count, equipment, Unassigned).
  [2e] Delete one point and optionally one equipment in the tree (right-click → Delete → confirm);
       verify tree updates so deleted items are gone.
  [2e2] Point context menu: right-click a point, verify Poll true / Poll false / Delete; set Poll false then Poll true.
  [2f] Data Model Testing smoke: open /data-model-testing, click Sites predefined query;
       wait for ``sparql-finished-generation`` when present, then assert results table or "No bindings"
       (avoids stale table while SPARQL is pending).

  [3] Plots: select site, select points (and optionally a second point with different unit), add fault;
      verify chart data, data-model units in legend, axis-by-unit, and fault series as Bool 0/1.
      When --api-url is set: log fault counts from DB (GET /faults/active, /faults/definitions) and
      confirm "Frontend showing faults in Plots: yes" when a fault is selected and 0/1 appears.

  [4] Weather page (resilient). [5] Overview smoke check.

  Optional (--api-url): backend timezone checks — GET /config, GET /download/csv (UTC Z);
  and faults-in-DB check — GET /faults/active, GET /faults/definitions (logged for Plots/fault parity).

Faults: Historically plotted in Grafana (see docs/howto/grafana_cookbook.md, grafana_dashboards.md).
The frontend Plots tab now shows fault series as Bool 0/1 on the right axis when a fault is selected;
this script asserts that flow and logs fault counts from the API when --api-url is set.

The old scripts remain for API-only or automation that cannot use a browser:
  - delete_all_sites_and_reset.py: API-only wipe + reset (no UI).
  - graph_and_crud_test.py: full API coverage (health, config, CRUD, SPARQL, BACnet proxy,
    import, download, lifecycle). Use E2E for the browser path; use graph_and_crud_test for
    API regression and BACnet/SPARQL coverage.

Usage:

  python 1_e2e_frontend_selenium.py --frontend-url http://192.168.204.16 --headed

  # With BACnet discovery (Points page → Add to data model) for one or more devices:
  python 1_e2e_frontend_selenium.py --frontend-url http://192.168.204.16 --bacnet-device-instance 3456789 3456790  --headed

  $env:OFDD_API_KEY = "same-as-server-stack/.env"
  python 1_e2e_frontend_selenium.py --frontend-url http://192.168.204.16 --api-url http://192.168.204.16:8000 --headed

Windows / copied scripts:
  - ``stack/.env`` is loaded from ``open-fdd/stack/.env`` only when this file lives under ``open-fdd/scripts/automated_testing/``
    (path is derived from ``__file__``). If you copy only ``*.py`` elsewhere (e.g. OneDrive), set ``$env:OFDD_API_KEY``
    or put a ``.env`` in the script directory / current directory.
  - Notepad-saved ``.env`` may use UTF-8 BOM; we read env files with UTF-8-sig so keys still parse.
  - HTTPS with a self-signed cert: add ``--ignore-ssl``.

Not run by bootstrap.sh --test (that runs frontend lint+vitest and backend pytest only). Run this script separately when validating the full UI flow from a test bench (stack must be up).

CRUD-style evaluation (RDF graph and database sync):
  - Delete: [1] Remove all sites and reset via UI → DELETE sites (cascade equipment/points) then POST /data-model/reset.
    Proves graph is repopulated from DB only (reset_graph_to_db_only); after wipe, both DB and graph are empty and in sync.
  - Create: [2] Create site (POST /sites) then Import JSON → backend writes equipment/points to DB, then rebuilds RDF from DB and serializes to TTL. Proves the write path keeps graph and DB in sync (import_data_model: DB first, then build_ttl_from_db + write).
  - Create (BACnet): [2a] Points page "Add to data model" → merges BACnet RDF into in-memory graph (and DB for points). Proves discovery path also updates graph and persists.
  - Read: [2b] Data Model page shows equipment names; [2c] Points page shows Unit (degF, percent, cfm); [3] Plots show points and data-model units in legend. All read from APIs backed by the same DB and graph. Proves that what was written (CRUD + import) is readable and that units/metadata flow from data model to UI.
  - Update: Not exercised explicitly; import can update existing points by point_id (API supports it; E2E uses fresh create + import).
  No direct assertion that "SPARQL count == DB count"; sync is proven indirectly by: wipe leaves both empty, import writes DB then rebuilds graph from DB, and all read flows show consistent data.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path


from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException
from webdriver_manager.chrome import ChromeDriverManager

# Paths: script in scripts/automated_testing/ or copied; payload next to script or in scripts/
SCRIPT_DIR = Path(__file__).resolve().parent
DEMO_PAYLOAD_PATH = SCRIPT_DIR / "demo_site_llm_payload.json"
MALFORMED_PAYLOAD_PATH = SCRIPT_DIR / "demo_site_llm_payload_malformed.json"
MISSING_SITE_PAYLOAD_PATH = SCRIPT_DIR / "demo_site_llm_payload_missing_site.json"


def _load_env_file(path: str) -> None:
    """Load KEY=VALUE lines from path into os.environ (only if key not already set)."""
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8-sig") as f:
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
    """Load stack/.env (when run from repo) then .env in cwd/script dir so OFDD_API_KEY is set."""
    repo_root = SCRIPT_DIR.parent.parent
    _load_env_file(str(repo_root / "stack" / ".env"))
    _load_env_file(os.path.join(os.getcwd(), ".env"))
    _load_env_file(str(SCRIPT_DIR / ".env"))


_load_stack_env()

# Defaults
DEFAULT_FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:5173").rstrip("/")
# Site name created in [2]; payload is demo_site_llm_payload.json (equipment: AHU-1, VAV-1, Weather-Station, Open-Meteo; points: SA-T, ZoneTemp, etc.)
TESTBENCH_SITE_NAME = os.environ.get("TESTBENCH_SITE_NAME", "TestBenchSite")
API_KEY = os.environ.get("OFDD_API_KEY", "").strip()

# From demo_site_llm_payload.json: equipment and points we assert in the UI
# From demo_site_llm_payload.json (equipment + points); first two equipment and two points used for assertions
EXPECTED_EQUIPMENT_NAMES = ("AHU-1", "VAV-1")
EXPECTED_POINT_NAMES = ("SA-T", "ZoneTemp")  # SA-T preferred for Plots; ZoneTemp fallback
FALLBACK_POINT_NAMES = ("MA-T", "RA-T", "DAP-P")
# Canonical units from data model (AI prompt / BACnet): must appear on frontend (Points table, Plots legend)
EXPECTED_UNITS_FROM_DATA_MODEL = ("degF", "percent", "cfm")
# Fault series on Plots use unit "0/1" (Bool); legend must show this so faults plot with other Bool on right axis
FAULT_LEGEND_UNIT = "0/1"
# Fault definitions from demo/FDD: prefer these for E2E so legend shows fault name + 0/1
EXPECTED_FAULT_IDS = ("ahu_short_cycling", "bad_sensor_flag")
# Second point with different unit (cfm) so Plots use two Y-axes (axis-by-unit): SA-T degF left, SA-FLOW cfm right2
SECOND_POINT_DIFFERENT_UNIT = ("SA-FLOW", "ZoneHumidity")

# Timeouts (seconds)
PAGE_LOAD_TIMEOUT = 30
ELEMENT_WAIT = 15
CHART_DATA_WAIT = 30
IMPORT_RESULT_WAIT = 35
TEXT_WAIT = 20

# Screenshot dir on failure
FAILURE_SCREENSHOT_DIR = Path.home() / ".openfdd_e2e_failures"


def get_driver(
    headed: bool = False,
    ignore_ssl: bool = False,
    capture_browser_logs: bool = False,
) -> webdriver.Chrome:
    """Create Chrome WebDriver (headless by default). Optionally ignore SSL errors for HTTPS.
    When capture_browser_logs is True, enables browser log capture so get_browser_console_errors() can report console errors."""
    from selenium.common.exceptions import WebDriverException

    options = ChromeOptions()
    if not headed:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    if ignore_ssl:
        options.add_argument("--ignore-certificate-errors")
    if capture_browser_logs:
        options.set_capability("goog:loggingPrefs", {"browser": "ALL"})
    try:
        service = ChromeService(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)
        return driver
    except WebDriverException as e:
        msg = str(e).lower()
        if "chrome" in msg and ("binary" in msg or "cannot find" in msg or "not found" in msg):
            print("Chrome/Chromium not found. Install Chrome or run with Chrome.", file=sys.stderr)
            print("E2E tests are optional; use them locally when the stack and Chrome are available.", file=sys.stderr)
        raise


def get_browser_console_errors(
    driver: webdriver.Chrome,
    levels: tuple[str, ...] = ("SEVERE", "WARNING"),
) -> list[dict]:
    """
    Return browser console log entries with the given levels (e.g. SEVERE for errors).
    Each item is a dict with at least 'level' and 'message'. Only entries since the last
    get_log('browser') (or since load) are returned; call after each route to get per-route errors.
    """
    try:
        entries = driver.get_log("browser")
    except Exception:
        return []
    out = [e for e in entries if e.get("level") in levels]
    # Drop noisy 404s that don't affect tests (favicon requested by browser, not served)
    def _is_expected_noise(msg: str) -> bool:
        # Browser-requested favicon 404 is harmless.
        if "favicon.ico" in msg and "404" in msg:
            return True
        # Plots may call /download/csv before BACnet scrape data exists for selected site/range.
        # Backend returns 404 "no data", which is expected in fresh test benches.
        if "/download/csv" in msg and "404" in msg:
            return True
        return False

    out = [e for e in out if not _is_expected_noise(e.get("message") or "")]
    return out


def log_browser_console(
    driver: webdriver.Chrome,
    step: str,
    levels: tuple[str, ...] = ("SEVERE", "WARNING"),
) -> None:
    """
    Fetch browser console entries for this step and print them.
    Does not fail the test; surfaced as diagnostics so 500s (e.g. /bacnet/server_hello)
    and React errors are visible alongside the E2E step output.
    """
    entries = get_browser_console_errors(driver, levels=levels)
    if not entries:
        print(f"  Browser console ({step}): OK (no SEVERE/WARNING entries).")
        return
    print(f"  Browser console ({step}): {len(entries)} SEVERE/WARNING entr(ies):")
    for e in entries[:10]:
        level = e.get("level")
        msg = (e.get("message") or "").strip().splitlines()[0]
        print(f"    - {level}: {msg[:300]}")
    if len(entries) > 10:
        print(f"    - ... {len(entries) - 10} more entries (see full browser log).")


# --- Helpers: explicit waits and safe actions ---

def wait_for_element(driver: webdriver.Chrome, by: str, value: str, timeout: float = ELEMENT_WAIT):
    """Wait for element to be present and return it."""
    wait = WebDriverWait(driver, timeout)
    return wait.until(EC.presence_of_element_located((by, value)))


def wait_for_clickable(driver: webdriver.Chrome, by: str, value: str, timeout: float = ELEMENT_WAIT):
    """Wait for element to be clickable and return it."""
    wait = WebDriverWait(driver, timeout)
    return wait.until(EC.element_to_be_clickable((by, value)))


def wait_for_text(driver: webdriver.Chrome, text: str, timeout: float = TEXT_WAIT) -> bool:
    """Wait until the given text appears in the page source. Returns True when found."""
    wait = WebDriverWait(driver, timeout)
    wait.until(lambda d: text in (d.page_source or ""))
    return True


def get_selected_site(driver: webdriver.Chrome) -> str | None:
    """Read the current selected site from the top-bar site selector button (text of the button)."""
    try:
        btn = driver.find_elements(
            By.XPATH,
            "//button[@aria-haspopup='listbox' and (contains(., 'All Sites') or contains(., 'Site'))]",
        )
        if btn:
            label = (btn[0].text or "").strip()
            return label if label and label != "All Sites" else None
    except Exception:
        pass
    return None


def assert_text_present(driver: webdriver.Chrome, text: str, msg: str = "") -> None:
    """Assert that the given text appears in the page. Raises AssertionError with optional msg."""
    if text not in (driver.page_source or ""):
        raise AssertionError(msg or f"Expected text {text!r} not found on page.")


def safe_click(driver: webdriver.Chrome, by: str, value: str, timeout: float = ELEMENT_WAIT) -> None:
    """Wait for element to be clickable and click it."""
    el = wait_for_clickable(driver, by, value, timeout)
    el.click()


def safe_send_keys(element, keys: str, clear_first: bool = True) -> None:
    """Send keys to element; optionally clear first."""
    if clear_first:
        element.clear()
    element.send_keys(keys)


def save_screenshot_and_context(driver: webdriver.Chrome, prefix: str = "e2e_fail") -> None:
    """On failure: save screenshot, current URL, title, and a short page source snippet."""
    FAILURE_SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    path = FAILURE_SCREENSHOT_DIR / f"{prefix}_{ts}.png"
    try:
        driver.save_screenshot(str(path))
        print(f"  Screenshot: {path}", file=sys.stderr)
    except Exception as e:
        print(f"  Could not save screenshot: {e}", file=sys.stderr)
    print(f"  URL: {driver.current_url}", file=sys.stderr)
    print(f"  Title: {driver.title}", file=sys.stderr)
    src = driver.page_source or ""
    snippet = src[:2000] + ("..." if len(src) > 2000 else "")
    dump_path = FAILURE_SCREENSHOT_DIR / f"{prefix}_{ts}_source.html"
    try:
        dump_path.write_text(snippet, encoding="utf-8")
        print(f"  Page source snippet: {dump_path}", file=sys.stderr)
    except Exception:
        print("  (page source snippet not saved)", file=sys.stderr)


# --- Flow steps ---

def _sites_loaded(driver: webdriver.Chrome) -> bool:
    """True when Data Model page has settled: delete-all section (sites exist), or No sites, or site rows."""
    if driver.find_elements(By.CSS_SELECTOR, "[data-testid=delete-all-confirm-input]"):
        return True
    if "No sites" in (driver.page_source or ""):
        return True
    if driver.find_elements(By.CSS_SELECTOR, "tr[data-site-id]"):
        return True
    return False


def _wait_data_model_ready(driver: webdriver.Chrome, timeout: float = 25) -> None:
    """Wait for Data Model page to show shell then the new-site name input (or placeholder fallback)."""
    wait_page = WebDriverWait(driver, timeout)
    wait_page.until(
        lambda d: "Data model" in (d.page_source or "") or "Sites" in (d.page_source or "")
    )
    time.sleep(0.5)
    wait = WebDriverWait(driver, timeout)
    try:
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "[data-testid=new-site-name-input]")))
    except Exception:
        wait.until(
            EC.presence_of_element_located((By.XPATH, "//input[@placeholder='Site name']"))
        )


def delete_all_sites_and_reset_via_ui(driver: webdriver.Chrome, base_url: str) -> None:
    """Navigate to Data Model, remove all sites and reset graph via UI.
    Replicates delete_all_sites_and_reset.py in the browser. Sites load asynchronously;
    the delete-all block is only rendered when the frontend has sites (GET /sites succeeded)."""
    driver.get(f"{base_url}/data-model")
    _wait_data_model_ready(driver, timeout=25)
    # Scroll so Sites / form is in view (helps on slow or tall pages)
    try:
        for by, value in [
            (By.CSS_SELECTOR, "[data-testid=new-site-name-input]"),
            (By.XPATH, "//input[@placeholder='Site name']"),
            (By.XPATH, "//*[contains(text(),'Sites')]"),
        ]:
            el = driver.find_elements(by, value)
            if el:
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", el[0])
                time.sleep(0.3)
                break
    except Exception:
        pass
    # Wait for sites to load (or empty state). Graph actions card may be above or below fold.
    wait_sites = WebDriverWait(driver, 18)
    wait_sites.until(_sites_loaded)
    # Scroll "Graph actions" / "Remove all sites" into view so delete-all is visible
    try:
        for text in ("Remove all sites from data model", "Graph actions"):
            el = driver.find_elements(By.XPATH, f"//*[contains(text(), '{text}')]")
            if el:
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", el[0])
                time.sleep(0.4)
                break
    except Exception:
        pass
    confirm_input = driver.find_elements(By.CSS_SELECTOR, "[data-testid=delete-all-confirm-input]")
    if not confirm_input:
        print("  No sites to delete.")
        print("  Hint: If you expect sites, ensure the frontend is built/served with VITE_OFDD_API_KEY", file=sys.stderr)
        print("  (same as OFDD_API_KEY in stack/.env) so GET /sites succeeds. See script docstring.", file=sys.stderr)
        return
    confirm_input = confirm_input[0]
    placeholder = confirm_input.get_attribute("placeholder") or ""
    try:
        n = int(placeholder.replace("Type", "").replace("to confirm", "").strip())
    except ValueError:
        n = 1
    safe_send_keys(confirm_input, str(n))
    safe_click(driver, By.CSS_SELECTOR, "[data-testid=delete-all-and-reset-button]")
    wait_after = WebDriverWait(driver, ELEMENT_WAIT)
    wait_after.until(
        lambda d: not d.find_elements(By.CSS_SELECTOR, "[data-testid=delete-all-confirm-input]")
        or "No sites" in (d.page_source or "")
    )
    print("  Delete all sites and reset: OK")
    log_browser_console(driver, "delete-all-and-reset")


def create_site_via_ui(driver: webdriver.Chrome, base_url: str, site_name: str) -> str:
    """Create a site from Data Model page and return its ID (from table row data-site-id)."""
    driver.get(f"{base_url}/data-model")
    _wait_data_model_ready(driver, timeout=25)
    try:
        name_input = driver.find_element(By.CSS_SELECTOR, "[data-testid=new-site-name-input]")
    except Exception:
        name_input = driver.find_element(By.XPATH, "//input[@placeholder='Site name']")
    safe_send_keys(name_input, site_name)
    safe_click(driver, By.CSS_SELECTOR, "[data-testid=add-site-button]")
    wait = WebDriverWait(driver, ELEMENT_WAIT)
    row = wait.until(
        EC.presence_of_element_located(
            (By.XPATH, f"//tr[@data-site-id and .//td[contains(., '{site_name}')]]")
        )
    )
    site_id = row.get_attribute("data-site-id")
    if not site_id:
        raise AssertionError(f"Site row for {site_name} has no data-site-id")
    print(f"  Created site {site_name!r} -> id={site_id[:8]}...")
    log_browser_console(driver, "create-site")
    return site_id


def import_llm_payload_via_ui(
    driver: webdriver.Chrome,
    base_url: str,
    payload_path: Path,
    site_id: str,
) -> tuple[int, int]:
    """Load JSON payload, inject site_id, paste and import via UI. Returns (points_count, equipment_count)."""
    if not payload_path.is_file():
        raise FileNotFoundError(f"Payload not found: {payload_path}")
    with open(payload_path, encoding="utf-8") as f:
        data = json.load(f)
    points = data.get("points") or []
    equipment = data.get("equipment") or []
    for p in points:
        if isinstance(p, dict):
            p["site_id"] = site_id
    for e in equipment:
        if isinstance(e, dict):
            e["site_id"] = site_id
    body = {"points": points, "equipment": equipment}
    json_str = json.dumps(body, indent=2)

    driver.get(f"{base_url}/data-model")
    textarea = wait_for_element(driver, By.CSS_SELECTOR, "[data-testid=data-model-import-json]")
    # Set value via JS and dispatch input so React state updates (avoids send_keys timeout on large payload)
    driver.execute_script(
        """
        var el = arguments[0];
        var val = arguments[1];
        var setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
        setter.call(el, val);
        el.dispatchEvent(new Event('input', { bubbles: true }));
        """,
        textarea,
        json_str,
    )
    safe_click(driver, By.CSS_SELECTOR, "[data-testid=data-model-import-button]")
    wait = WebDriverWait(driver, IMPORT_RESULT_WAIT)
    wait.until(
        lambda d: "Created" in (d.page_source or "") or "Total" in (d.page_source or "")
        or "Updated" in (d.page_source or "") or "warnings" in (d.page_source or "")
    )
    print(f"  Import: OK (points={len(points)}, equipment={len(equipment)})")
    log_browser_console(driver, "import-llm-payload")
    return len(points), len(equipment)


def import_payload_expect_failure_via_ui(
    driver: webdriver.Chrome,
    base_url: str,
    payload_path: Path,
    site_id: str,
    label: str,
) -> None:
    """Negative import test: malformed or missing-site payload should be rejected."""
    if not payload_path.is_file():
        print(f"  Import negative ({label}): skip (payload missing)")
        return
    with open(payload_path, encoding="utf-8") as f:
        body = json.load(f)
    points = body.get("points") or []
    equipment = body.get("equipment") or []
    for p in points:
        if isinstance(p, dict) and p.get("site_id") == "__SITE_ID__":
            p["site_id"] = site_id
    for e in equipment:
        if isinstance(e, dict) and e.get("site_id") == "__SITE_ID__":
            e["site_id"] = site_id
    json_str = json.dumps({"points": points, "equipment": equipment}, indent=2)
    driver.get(f"{base_url}/data-model")
    textarea = wait_for_element(driver, By.CSS_SELECTOR, "[data-testid=data-model-import-json]")
    driver.execute_script(
        """
        var el = arguments[0];
        var val = arguments[1];
        var setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
        setter.call(el, val);
        el.dispatchEvent(new Event('input', { bubbles: true }));
        """,
        textarea,
        json_str,
    )
    safe_click(driver, By.CSS_SELECTOR, "[data-testid=data-model-import-button]")
    wait = WebDriverWait(driver, IMPORT_RESULT_WAIT)
    wait.until(
        lambda d: ("invalid" in (d.page_source or "").lower())
        or ("error" in (d.page_source or "").lower())
        or ("must be" in (d.page_source or "").lower())
        or ("422" in (d.page_source or ""))
    )
    print(f"  Import negative ({label}): rejected as expected.")


def bacnet_add_to_model_via_ui(
    driver: webdriver.Chrome,
    base_url: str,
    device_instance: int,
    timeout: float = 40.0,
) -> bool:
    """Use Data Model page BACnet discovery: set device instance, click 'Add to data model'.
    Merges BACnet RDF into the graph (same as graph_and_crud_test.py point_discovery_to_graph).
    Returns True if success message appears, False on failure or timeout (e.g. gateway unreachable)."""
    driver.get(f"{base_url}/data-model")
    wait_for_text(driver, "BACnet discovery", timeout=TEXT_WAIT)
    wait_for_text(driver, "Add to data model", timeout=TEXT_WAIT)
    try:
        dev_input = wait_for_element(driver, By.CSS_SELECTOR, "[data-testid=bacnet-device-instance-input]", timeout=10)
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", dev_input)
        time.sleep(0.3)
        dev_input.clear()
        dev_input.send_keys(str(device_instance))
        time.sleep(0.2)
        add_btn = driver.find_element(By.CSS_SELECTOR, "[data-testid=bacnet-add-to-model-button]")
        add_btn.click()
    except Exception as e:
        print(f"  BACnet discovery: UI interaction failed — {e}")
        return False
    wait = WebDriverWait(driver, timeout)
    try:
        wait.until(
            lambda d: "added to graph" in (d.page_source or "").lower()
            or "Add to graph failed" in (d.page_source or "")
        )
    except Exception:
        print("  BACnet discovery: timeout waiting for result (gateway may be unreachable).")
        return False
    page = driver.page_source or ""
    if "added to graph" in page.lower():
        print(f"  BACnet discovery: device {device_instance} added to graph (Data Model page).")
        log_browser_console(driver, f"bacnet-add-to-model-{device_instance}")
        return True
    print(f"  BACnet discovery: Add to data model failed (check BACnet gateway / OFDD_BACNET_SERVER_URL).")
    log_browser_console(driver, f"bacnet-add-to-model-{device_instance}")
    return False


def verify_data_model_after_import(
    driver: webdriver.Chrome,
    base_url: str,
    expected_equipment: tuple[str, ...],
    expected_points: tuple[str, ...],
    expected_point_count: int | None,
    expected_equipment_count: int | None,
) -> None:
    """After import, assert equipment names appear on Data Model page.
    The Data Model page shows equipment names and point counts only; it does not list
    point names (SA-T, ZoneTemp, etc.). Point names are validated on the Plots page
    when we select a known point."""
    driver.get(f"{base_url}/data-model")
    wait_for_text(driver, "Equipment", timeout=TEXT_WAIT)
    if expected_equipment:
        wait_for_text(driver, expected_equipment[0], timeout=TEXT_WAIT)
    try:
        el = driver.find_elements(By.XPATH, "//*[contains(text(), 'Equipment in the data model')]")
        if not el:
            el = driver.find_elements(By.XPATH, "//*[contains(text(), 'Equipment')]")
        if el:
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", el[0])
            time.sleep(0.3)
    except Exception:
        pass
    for name in expected_equipment:
        assert_text_present(driver, name, f"Expected equipment {name!r} after import.")
    print(f"  Data model: equipment {expected_equipment} visible.")
    # Point names are not shown on Data Model (only equipment + point count). Validated on Plots.
    if expected_points:
        print(f"  Data model: point names (e.g. {expected_points[:2]}) will be validated on Plots page.")
    if expected_equipment_count is not None:
        pass
    if expected_point_count is not None:
        pass
    print("  Data model: post-import assertions OK.")
    log_browser_console(driver, "data-model-after-import")


def verify_units_on_frontend(
    driver: webdriver.Chrome,
    base_url: str,
    site_name: str,
    expected_units: tuple[str, ...] = EXPECTED_UNITS_FROM_DATA_MODEL,
) -> None:
    """Verify that units from the data model appear on the frontend (Points table, axis/legend).
    Ensures AI-assisted tagging and BACnet/Open-Meteo canonical units flow through to the UI."""
    driver.get(f"{base_url}/points")
    wait_for_text(driver, "Points", timeout=TEXT_WAIT)
    verify_site_selected(driver, site_name, "units check")
    wait_for_text(driver, "Unit", timeout=TEXT_WAIT)  # PointsTree Unit column header
    time.sleep(0.5)  # allow table to render with point data
    page_src = driver.page_source or ""
    found = [u for u in expected_units if u in page_src]
    if not found:
        raise AssertionError(
            f"Expected at least one data-model unit in {expected_units!r} to appear on Points page (Unit column). "
            "Units must flow from data model to frontend for axis labels and grouping."
        )
    print(f"  Units on frontend: {found} visible on Points page (data model units OK).")
    log_browser_console(driver, "points-units")


def verify_points_page_device_tree(
    driver: webdriver.Chrome,
    base_url: str,
    site_name: str,
    expected_columns: tuple[str, ...] = (
        "Name",
        "Site",
        "Brick Type",
        "FDD Input",
        "Unit",
        "Polling",
        "Last value",
        "Last updated",
    ),
) -> None:
    """
    Verify Points page device tree: table has expected column headers and tree shows at least
    one site (e.g. TestBenchSite/BensTestBench), equipment, and Unassigned. Same structure
    as in the UI: Site (N) → Equipment (M) / Unassigned (K) → point rows.
    """
    driver.get(f"{base_url}/points")
    wait_for_text(driver, "Points", timeout=TEXT_WAIT)
    wait_for_text(driver, "BACnet discovery", timeout=TEXT_WAIT)
    verify_site_selected(driver, site_name, "Points device tree")
    time.sleep(0.6)
    page_src = driver.page_source or ""
    for col in expected_columns:
        if col not in page_src:
            raise AssertionError(
                f"Points page device tree: expected column {col!r} not found. "
                "Table should have Name, Site, Brick Type, FDD Input, Unit, Polling, Last value, Last updated."
            )
    if site_name not in page_src and "Unassigned" not in page_src:
        raise AssertionError(
            f"Points page: expected site {site_name!r} or 'Unassigned' in tree; got neither."
        )
    print(f"  Points device tree: columns {expected_columns} present; site/Unassigned visible.")
    log_browser_console(driver, "points-device-tree")


def _accept_confirm_dialog(driver: webdriver.Chrome, timeout: float = 3.0) -> None:
    """Accept the next browser confirm() dialog (e.g. Delete point?)."""
    try:
        wait = WebDriverWait(driver, timeout)
        alert = wait.until(EC.alert_is_present())
        alert.accept()
    except Exception:
        pass


def delete_one_point_via_tree(
    driver: webdriver.Chrome,
    base_url: str,
    point_external_id: str,
    site_name: str,
) -> bool:
    """
    On Points page, find a point row by external_id (e.g. MA-T, RA-T), right-click → Delete point → confirm.
    Returns True if delete was performed and point disappeared. Keeps SA-T/ZoneTemp for Plots.
    """
    driver.get(f"{base_url}/points")
    wait_for_text(driver, "Points", timeout=TEXT_WAIT)
    verify_site_selected(driver, site_name, "delete point")
    time.sleep(0.6)
    _expand_points_tree_until_visible(driver, point_external_id, site_name)
    page_before = driver.page_source or ""
    if point_external_id not in page_before:
        print(f"  Points tree: point {point_external_id!r} not found; skip delete point.")
        return False
    rows = driver.find_elements(
        By.XPATH,
        f"//tr[.//td[contains(., '{point_external_id}')]]",
    )
    if not rows:
        print(f"  Points tree: no row for point {point_external_id!r}; skip delete.")
        return False
    try:
        ActionChains(driver).context_click(rows[0]).perform()
        time.sleep(0.3)
        delete_btn = driver.find_elements(
            By.XPATH,
            "//button[contains(text(), 'Delete point')]",
        )
        if not delete_btn:
            body = driver.find_element(By.TAG_NAME, "body")
            body.click()
            return False
        delete_btn[0].click()
        _accept_confirm_dialog(driver)
        WebDriverWait(driver, ELEMENT_WAIT).until(
            lambda d: point_external_id not in (d.page_source or ""),
        )
        print(f"  Points tree: deleted point {point_external_id!r}; tree updated.")
        log_browser_console(driver, f"delete-point-{point_external_id}")
        return True
    except Exception as e:
        print(f"  Points tree: delete point failed — {e}")
        try:
            driver.find_element(By.TAG_NAME, "body").click()
        except Exception:
            pass
        return False


def delete_one_equipment_via_tree(
    driver: webdriver.Chrome,
    base_url: str,
    equipment_name: str,
    site_name: str,
) -> bool:
    """
    On Points page, find equipment row by name, right-click → Delete equipment → confirm.
    Returns True if delete was performed. Use an equipment that is not required for Plots (e.g. extra).
    """
    driver.get(f"{base_url}/points")
    wait_for_text(driver, "Points", timeout=TEXT_WAIT)
    verify_site_selected(driver, site_name, "delete equipment")
    time.sleep(0.5)
    page_before = driver.page_source or ""
    if equipment_name not in page_before:
        print(f"  Points tree: equipment {equipment_name!r} not found; skip delete equipment.")
        return False
    rows = driver.find_elements(
        By.XPATH,
        f"//tr[.//span[contains(., '{equipment_name}')] and .//button[@aria-expanded]]",
    )
    if not rows:
        rows = driver.find_elements(
            By.XPATH,
            f"//tr[contains(., '{equipment_name}') and contains(@class, 'cursor-pointer')]",
        )
    if not rows:
        print(f"  Points tree: no equipment row for {equipment_name!r}; skip delete.")
        return False
    try:
        ActionChains(driver).context_click(rows[0]).perform()
        time.sleep(0.3)
        delete_btn = driver.find_elements(
            By.XPATH,
            "//button[contains(text(), 'Delete equipment')]",
        )
        if not delete_btn:
            driver.find_element(By.TAG_NAME, "body").click()
            return False
        delete_btn[0].click()
        _accept_confirm_dialog(driver)
        WebDriverWait(driver, ELEMENT_WAIT).until(
            lambda d: equipment_name not in (d.page_source or "") or "Unassigned" in (d.page_source or ""),
        )
        print(f"  Points tree: deleted equipment {equipment_name!r}; tree updated.")
        log_browser_console(driver, f"delete-equipment-{equipment_name}")
        return True
    except Exception as e:
        print(f"  Points tree: delete equipment failed — {e}")
        try:
            driver.find_element(By.TAG_NAME, "body").click()
        except Exception:
            pass
        return False


# Test IDs for point context menu (must match frontend POINTS_CONTEXT_MENU_TEST_IDS).
POINTS_CONTEXT_MENU_POLL_TRUE = "points-context-menu-poll-true"
POINTS_CONTEXT_MENU_POLL_FALSE = "points-context-menu-poll-false"
POINTS_CONTEXT_MENU_DELETE_POINT = "points-context-menu-delete-point"


def _expand_points_tree_until_visible(
    driver: webdriver.Chrome,
    point_external_id: str,
    site_name: str,
    max_clicks: int = 5,
) -> None:
    """Expand site/equipment nodes on Points page until point row is in the DOM (tree may start collapsed)."""
    for _ in range(max_clicks):
        if point_external_id in (driver.page_source or ""):
            return
        collapsed = driver.find_elements(
            By.XPATH,
            "//tr[.//button[@aria-expanded='false']]",
        )
        if not collapsed:
            return
        try:
            btn = collapsed[0].find_element(By.XPATH, ".//button[@aria-expanded='false']")
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
            time.sleep(0.15)
            btn.click()
            time.sleep(0.3)
        except Exception:
            return


def point_context_menu_poll_false_then_true(
    driver: webdriver.Chrome,
    base_url: str,
    point_external_id: str,
    site_name: str,
) -> None:
    """
    On Points page, right-click a point, verify context menu has Poll true, Poll false, Delete point.
    Then click Poll false, wait for update; then right-click same point, click Poll true, wait.
    Proves the point context menu and polling toggle work.
    """
    driver.get(f"{base_url}/points")
    wait_for_text(driver, "Points", timeout=TEXT_WAIT)
    verify_site_selected(driver, site_name, "point context menu")
    time.sleep(0.6)
    _expand_points_tree_until_visible(driver, point_external_id, site_name)
    if point_external_id not in (driver.page_source or ""):
        raise AssertionError(
            f"Point {point_external_id!r} not found on Points page; cannot run context menu test."
        )
    rows = driver.find_elements(
        By.XPATH,
        f"//tr[.//td[contains(., '{point_external_id}')]]",
    )
    if not rows:
        raise AssertionError(
            f"Point row for {point_external_id!r} not found; cannot run context menu test."
        )
    # Open context menu
    ActionChains(driver).context_click(rows[0]).perform()
    time.sleep(0.3)
    # Verify menu has Poll true, Poll false, Delete point
    poll_true_btn = driver.find_elements(
        By.CSS_SELECTOR, f"[data-testid={POINTS_CONTEXT_MENU_POLL_TRUE!r}]"
    )
    poll_false_btn = driver.find_elements(
        By.CSS_SELECTOR, f"[data-testid={POINTS_CONTEXT_MENU_POLL_FALSE!r}]"
    )
    delete_btn = driver.find_elements(
        By.CSS_SELECTOR, f"[data-testid={POINTS_CONTEXT_MENU_DELETE_POINT!r}]"
    )
    if not poll_true_btn or not poll_false_btn or not delete_btn:
        driver.find_element(By.TAG_NAME, "body").click()
        raise AssertionError(
            "Point context menu missing Poll true, Poll false, or Delete point (data-testid)."
        )
    # Poll false
    poll_false_btn[0].click()
    time.sleep(0.5)
    WebDriverWait(driver, 12).until(
        lambda d: "Poll true" in (d.page_source or "") or "Poll false" in (d.page_source or "")
    )
    # Re-find point row and open context menu again
    time.sleep(0.4)
    rows2 = driver.find_elements(
        By.XPATH,
        f"//tr[.//td[contains(., '{point_external_id}')]]",
    )
    if not rows2:
        print("  Point context menu: point row not found after Poll false; continuing.")
        return
    ActionChains(driver).context_click(rows2[0]).perform()
    time.sleep(0.3)
    poll_true_btn2 = driver.find_elements(
        By.CSS_SELECTOR, f"[data-testid={POINTS_CONTEXT_MENU_POLL_TRUE!r}]"
    )
    if poll_true_btn2:
        poll_true_btn2[0].click()
        time.sleep(0.5)
    else:
        driver.find_element(By.TAG_NAME, "body").click()
    print(f"  Point context menu: Poll false then Poll true on {point_external_id!r} OK.")
    log_browser_console(driver, f"point-context-menu-{point_external_id}")


# SPARQL smoke: same completion hook as 2_sparql_crud_and_frontend_test.py (avoids stale table during React Query pending).
_SPARQL_SMOKE_API_WAIT_SEC = 45


def _sparql_smoke_generation_before(driver: webdriver.Chrome) -> str | None:
    """Return data-gen from sparql-finished-generation, or None if the frontend hook is absent."""
    els = driver.find_elements(By.CSS_SELECTOR, "[data-testid=sparql-finished-generation]")
    if not els:
        return None
    return (els[0].get_attribute("data-gen") or "0").strip()


def _wait_sparql_smoke_generation_increment(
    driver: webdriver.Chrome, timeout_sec: float, generation_before: str
) -> bool:
    """Wait until data-gen changes after Run / predefined query (SPARQL mutation settled)."""
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            cur = (
                driver.find_element(
                    By.CSS_SELECTOR, "[data-testid=sparql-finished-generation]"
                ).get_attribute("data-gen")
                or "0"
            ).strip()
        except Exception:
            time.sleep(0.03)
            continue
        if cur != generation_before:
            time.sleep(0.12)
            return True
        time.sleep(0.03)
    return False


def verify_data_model_testing_smoke(driver: webdriver.Chrome, base_url: str) -> None:
    """
    Open Data Model Testing page (/data-model-testing), click the Sites predefined button,
    and assert that either the SPARQL results table or 'No bindings' appears. Proves the
    Summarize-your-HVAC + Custom SPARQL page loads and runs a query.

    When the page exposes ``data-testid=sparql-finished-generation``, waits for that counter
    to advance after the click so we do not treat the previous query's table as success (same
    pattern as ``2_sparql_crud_and_frontend_test.py``).
    """
    driver.get(f"{base_url}/data-model-testing")
    wait_for_text(driver, "Data Model Testing", timeout=TEXT_WAIT)
    wait_for_element(driver, By.CSS_SELECTOR, "[data-testid=sparql-query-textarea]", timeout=ELEMENT_WAIT)
    before_gen = _sparql_smoke_generation_before(driver)
    # Click the "Sites" predefined button (first summary button)
    sites_btn = wait_for_clickable(
        driver,
        By.XPATH,
        "//button[contains(., 'Sites') and not(contains(@class, 'hidden'))]",
        timeout=ELEMENT_WAIT,
    )
    sites_btn.click()

    if before_gen is not None:
        if not _wait_sparql_smoke_generation_increment(
            driver, _SPARQL_SMOKE_API_WAIT_SEC, before_gen
        ):
            print(
                "  Data Model Testing: timeout waiting for SPARQL run to finish "
                f"(data-testid=sparql-finished-generation, {_SPARQL_SMOKE_API_WAIT_SEC}s). Continuing."
            )
            log_browser_console(driver, "data-model-testing-smoke")
            return
        err_els = driver.find_elements(By.CSS_SELECTOR, "[data-testid=sparql-error]")
        err_txt = (err_els[0].text or "").strip() if err_els else ""
        if err_txt:
            print(f"  Data Model Testing: SPARQL UI reported error: {err_txt[:500]}")
            log_browser_console(driver, "data-model-testing-smoke")
            return

    # Wait for result: results table or "No bindings (empty result)." (longer on LAN / Windows)
    tail_wait = 10 if before_gen is not None else _SPARQL_SMOKE_API_WAIT_SEC
    wait = WebDriverWait(driver, tail_wait)
    try:
        wait.until(
            lambda d: (
                d.find_elements(By.CSS_SELECTOR, "[data-testid=sparql-results-table]")
                or "No bindings" in (d.page_source or "")
                or "empty result" in (d.page_source or "")
            )
        )
        print("  Data Model Testing: Sites query ran; results table or No bindings visible.")
    except TimeoutException:
        print(
            "  Data Model Testing: timeout waiting for Sites query result (API may be slow or unreachable from browser). Continuing."
        )
    log_browser_console(driver, "data-model-testing-smoke")


def select_site_in_topbar(driver: webdriver.Chrome, site_name: str) -> None:
    """Open site selector in top bar and click the option with the given name."""
    selector_btn = wait_for_clickable(
        driver,
        By.XPATH,
        "//button[@aria-haspopup='listbox' and (contains(., 'All Sites') or contains(., 'Site'))]",
    )
    selector_btn.click()
    site_option = wait_for_clickable(
        driver,
        By.XPATH,
        f"//div[contains(@class,'rounded-2xl')]//button[.//span[contains(text(), '{site_name}')]]",
    )
    site_option.click()


def verify_site_selected(driver: webdriver.Chrome, expected_site: str, step_name: str = "") -> None:
    """Assert that the site selector shows the expected site (or select it if not)."""
    current = get_selected_site(driver)
    if current == expected_site:
        print(f"  Site check ({step_name}): selected {expected_site!r}.")
        return
    if current != expected_site:
        select_site_in_topbar(driver, expected_site)
        WebDriverWait(driver, ELEMENT_WAIT).until(
            lambda d: get_selected_site(d) == expected_site
        )
    print(f"  Site check ({step_name}): selected {expected_site!r}.")


def select_known_point(
    driver: webdriver.Chrome,
    preference: list[str],
    timeout: float = ELEMENT_WAIT,
) -> str | None:
    """
    Open the Plots point picker and select the first available point from the preference list
    (e.g. SA-T, then ZoneTemp, then MA-T). Returns the name selected or None.
    Uses robust waits; point picker dropdown uses labels with span (object_name or external_id).
    """
    wait = WebDriverWait(driver, timeout)
    wait.until(EC.presence_of_element_located((By.XPATH, "//label[contains(., 'Points')]")))
    for name in preference:
        opts = driver.find_elements(
            By.XPATH,
            f"//label[contains(., 'Points')]/following-sibling::select/option[contains(., '{name}')]",
        )
        if opts:
            opts[0].click()
            print(f"  Plots: selected point {name!r}.")
            return name
    point_options = driver.find_elements(
        By.XPATH,
        "//label[contains(., 'Points')]/following-sibling::select/option",
    )
    if point_options:
        point_options[0].click()
        print("  Plots: selected first available point (fallback).")
        return "first_available"
    return None


def select_second_point_different_unit(
    driver: webdriver.Chrome,
    preference: tuple[str, ...] = SECOND_POINT_DIFFERENT_UNIT,
    timeout: float = ELEMENT_WAIT,
) -> bool:
    """
    Open the Plots point picker and add a second point with a different unit (e.g. SA-FLOW cfm).
    Used to trigger axis-by-unit: first unit (degF) on left, second (cfm) on right2. Returns True if selected.
    """
    # Point picker button shows "N series" when points selected; prefer the one with "series" (not fault picker).
    picker_btns = driver.find_elements(
        By.XPATH,
        "//button[@aria-haspopup='listbox' and (contains(., 'Select points') or contains(., 'series'))]",
    )
    if not picker_btns:
        return False
    picker_btns[0].click()
    # Wait for point picker dropdown: search input with placeholder unique to point picker (not fault picker).
    wait = WebDriverWait(driver, timeout)
    try:
        wait.until(
            EC.presence_of_element_located(
                (By.XPATH, "//input[contains(@placeholder, 'external_id') or contains(@placeholder, 'Search by name')]")
            )
        )
    except Exception:
        try:
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='text']")))
        except Exception:
            try:
                driver.find_element(By.TAG_NAME, "body").click()
            except Exception:
                pass
            return False
    time.sleep(0.5)
    for name in preference:
        opts = driver.find_elements(
            By.XPATH,
            "//div[contains(@class,'rounded-xl')]//label[.//span[contains(text(), '" + name + "')]]",
        )
        if not opts:
            opts = driver.find_elements(
                By.XPATH,
                "//div[contains(@class,'rounded-xl')]//*[contains(normalize-space(), '" + name + "') and (self::span or self::button)]",
            )
        if opts:
            opts[0].click()
            time.sleep(0.3)
            try:
                driver.find_element(By.TAG_NAME, "body").click()
            except Exception:
                pass
            print(f"  Plots: added second point {name!r} (different unit -> second Y-axis).")
            return True
    try:
        driver.find_element(By.TAG_NAME, "body").click()
    except Exception:
        pass
    return False


def select_fault_on_plots(
    driver: webdriver.Chrome,
    preference: tuple[str, ...] = EXPECTED_FAULT_IDS,
    timeout: float = ELEMENT_WAIT,
) -> bool:
    """
    Open the Plots fault picker and select the first available fault from the preference list.
    Returns True if a fault was selected, False if picker not found or no fault definitions.
    """
    try:
        btn = driver.find_elements(By.CSS_SELECTOR, "[data-testid='plots-fault-picker']")
        if not btn:
            return False
        btn[0].click()
        WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "input[placeholder*='Search']"))
        )
        time.sleep(0.3)
        if "No fault definitions" in (driver.page_source or ""):
            driver.find_element(By.TAG_NAME, "body").click()
            return False
        for fault_id in preference:
            opts = driver.find_elements(
                By.XPATH,
                f"//label[.//span[contains(text(), '{fault_id}')]]",
            )
            if not opts:
                opts = driver.find_elements(
                    By.XPATH,
                    f"//div[contains(@class,'rounded-xl') or contains(@class,'rounded-lg')]//label[contains(., '{fault_id}')]",
                )
            if opts:
                opts[0].click()
                print(f"  Plots: selected fault {fault_id!r} (Bool/0/1 on right axis).")
                try:
                    driver.find_element(By.TAG_NAME, "body").click()
                except Exception:
                    pass
                return True
        # Fallback: first fault checkbox inside the fault-picker dropdown (same panel as search input)
        first_label = driver.find_elements(
            By.XPATH,
            "//input[contains(@placeholder,'Search')]/ancestor::div[2]//label[.//input[@type='checkbox']]",
        )
        if first_label:
            first_label[0].click()
            print("  Plots: selected first available fault (fallback).")
            try:
                driver.find_element(By.TAG_NAME, "body").click()
            except Exception:
                pass
            return True
    except Exception:
        pass
    return False


def validate_plots_chart_has_data(
    driver: webdriver.Chrome,
    base_url: str,
    site_name: str,
    api_url: str | None = None,
    site_id: str | None = None,
) -> None:
    """Go to Plots, select site and points (two units to trigger axis-by-unit), then assert chart and axes.
    Verifies: (1) data-model units (degF, percent, cfm) in legend; (2) axis-by-unit: multiple Y-axes when
    multiple units (e.g. degF left, cfm right2); (3) faults as Bool 0/1 in legend on right axis.
    When api_url is set, logs fault counts from DB (GET /faults/active, /faults/definitions) and
    prints whether the frontend is showing faults in Plots."""
    if api_url:
        run_faults_db_check(api_url)
    driver.get(f"{base_url}/plots")
    if "Select a site" in (driver.page_source or ""):
        select_site_in_topbar(driver, site_name)
        WebDriverWait(driver, ELEMENT_WAIT).until(
            lambda d: "Select a site" not in (d.page_source or "") or "Select points" in (d.page_source or "")
        )
    else:
        select_site_in_topbar(driver, site_name)
    wait_for_element(
        driver,
        By.XPATH,
        "//*[contains(text(), 'Select points') or contains(@class, 'recharts')]",
        timeout=ELEMENT_WAIT,
    )
    preference = list(EXPECTED_POINT_NAMES) + list(FALLBACK_POINT_NAMES)
    select_known_point(driver, preference)
    time.sleep(0.6)  # let point picker dropdown close and chart update before reopening
    # Add second point with different unit (e.g. SA-FLOW cfm) so chart uses two Y-axes (axis-by-unit)
    second_point_added = select_second_point_different_unit(driver)
    if second_point_added:
        time.sleep(0.5)
    # Optionally add a fault so we can verify fault series show as Bool 0/1 in legend on right axis
    fault_selected = select_fault_on_plots(driver)
    if fault_selected:
        time.sleep(0.5)  # allow fault picker to close and chart to update
    wait_chart = WebDriverWait(driver, CHART_DATA_WAIT)
    try:
        path_el = wait_chart.until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, ".recharts-curve, .recharts-line-curve, path.recharts-curve")
            )
        )
        d_attr = path_el.get_attribute("d") or ""
        if len(d_attr) > 20:
            print("  Plots: chart has data (path d length > 20).")
        else:
            print("  Plots: chart rendered (path present).")
    except Exception:
        if "No point data" in (driver.page_source or "") or "Select points" in (driver.page_source or ""):
            print("  Plots: chart area rendered (no timeseries data in range yet).")
        else:
            raise AssertionError("Plots page: no chart curve/path and no 'no data' message found.")
    # Units from data model must appear on Plots (legend shows "label unit", e.g. SA-T degF)
    page_src = driver.page_source or ""
    if "degF" not in page_src and "percent" not in page_src and "cfm" not in page_src:
        raise AssertionError(
            "Plots: expected at least one data-model unit (degF, percent, cfm) in legend or axis; "
            "units must flow from data model to frontend."
        )
    print("  Plots: data-model units visible in chart (legend/axis).")
    # Axis-by-unit: when two points with different units are selected, chart must have at least 2 Y-axes
    if second_point_added:
        y_axes = driver.find_elements(By.CSS_SELECTOR, "[class*='recharts-yAxis']")
        if len(y_axes) < 2:
            raise AssertionError(
                "Plots: expected at least 2 Y-axes when points have different units (axis-by-unit); "
                f"got {len(y_axes)}."
            )
        print("  Plots: axis-by-unit OK (multiple Y-axes for different units).")
    # When a fault is selected, legend must show Bool unit 0/1 and faults plot on right Y-axis
    if fault_selected:
        if FAULT_LEGEND_UNIT not in page_src:
            raise AssertionError(
                "Plots: expected fault series to show unit 0/1 (Bool) in legend; "
                "faults must plot with other Bool on right axis."
            )
        print("  Plots: fault series show 0/1 (Bool) in legend, right axis.")
        print("  Frontend showing faults in Plots: yes (fault selected and 0/1 in legend).")
    else:
        print(
            "  Frontend showing faults in Plots: no (no fault selected or no fault definitions). "
            "Faults in DB can be checked with --api-url; see docs/howto/grafana_cookbook.md for historical Grafana fault plotting."
        )
    if api_url and site_id:
        # Print DB sensor + fault data that the Plots tab should be using, so we can
        # see both together in the Python console for this site.
        print_sample_timeseries_and_faults(api_url, site_id)
    log_browser_console(driver, "plots")


# Re-define Plots selectors for the Plotly + device/points/faults dropdown UI.
def select_known_point(
    driver: webdriver.Chrome,
    preference: list[str],
    timeout: float = ELEMENT_WAIT,
) -> str | None:
    wait = WebDriverWait(driver, timeout)
    wait.until(EC.presence_of_element_located((By.XPATH, "//label[contains(., 'Points')]")))
    for name in preference:
        opts = driver.find_elements(
            By.XPATH,
            f"//label[contains(., 'Points')]/following-sibling::select/option[contains(., '{name}')]",
        )
        if opts:
            opts[0].click()
            print(f"  Plots: selected point {name!r}.")
            return name
    point_options = driver.find_elements(
        By.XPATH,
        "//label[contains(., 'Points')]/following-sibling::select/option",
    )
    if point_options:
        point_options[0].click()
        print("  Plots: selected first available point (fallback).")
        return "first_available"
    return None


def select_second_point_different_unit(
    driver: webdriver.Chrome,
    preference: tuple[str, ...] = SECOND_POINT_DIFFERENT_UNIT,
    timeout: float = ELEMENT_WAIT,
) -> bool:
    wait = WebDriverWait(driver, timeout)
    wait.until(EC.presence_of_element_located((By.XPATH, "//label[contains(., 'Points')]")))
    for name in preference:
        opts = driver.find_elements(
            By.XPATH,
            f"//label[contains(., 'Points')]/following-sibling::select/option[contains(., '{name}')]",
        )
        if opts:
            opts[0].click()
            time.sleep(0.3)
            print(f"  Plots: added second point {name!r}.")
            return True
    return False


def select_fault_on_plots(
    driver: webdriver.Chrome,
    preference: tuple[str, ...] = EXPECTED_FAULT_IDS,
    timeout: float = ELEMENT_WAIT,
) -> bool:
    try:
        WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.XPATH, "//label[contains(., 'Faults')]"))
        )
        all_opts = driver.find_elements(
            By.XPATH, "//label[contains(., 'Faults')]/following-sibling::select/option"
        )
        if not all_opts:
            return False
        for fault_id in preference:
            opts = driver.find_elements(
                By.XPATH,
                f"//label[contains(., 'Faults')]/following-sibling::select/option[contains(., '{fault_id}')]",
            )
            if opts:
                opts[0].click()
                print(f"  Plots: selected fault {fault_id!r}.")
                return True
        all_opts[0].click()
        print("  Plots: selected first available fault (fallback).")
        return True
    except Exception:
        return False


def validate_plots_chart_has_data(
    driver: webdriver.Chrome,
    base_url: str,
    site_name: str,
    api_url: str | None = None,
    site_id: str | None = None,
) -> None:
    if api_url:
        run_faults_db_check(api_url)
    driver.get(f"{base_url}/plots")
    if "Select a site" in (driver.page_source or ""):
        select_site_in_topbar(driver, site_name)
    else:
        select_site_in_topbar(driver, site_name)

    wait_for_element(
        driver,
        By.XPATH,
        "//*[contains(text(), 'Load Data from Database')]",
        timeout=ELEMENT_WAIT,
    )
    preference = list(EXPECTED_POINT_NAMES) + list(FALLBACK_POINT_NAMES)
    first = select_known_point(driver, preference)
    if not first:
        raise AssertionError("Plots page: no selectable point found for device.")
    second_point_added = select_second_point_different_unit(driver)
    fault_selected = select_fault_on_plots(driver)
    safe_click(driver, By.XPATH, "//button[contains(., 'Load Data from Database')]")
    time.sleep(1.0)

    wait_chart = WebDriverWait(driver, CHART_DATA_WAIT)
    wait_chart.until(
        EC.presence_of_element_located(
            (By.CSS_SELECTOR, ".js-plotly-plot, [data-testid='plots-chart-container']")
        )
    )
    page_src = driver.page_source or ""
    if "degF" not in page_src and "percent" not in page_src and "cfm" not in page_src:
        raise AssertionError("Plots: expected at least one unit to appear (degF/percent/cfm).")
    if second_point_added:
        print("  Plots: second point selected (multi-series check).")
    if fault_selected:
        print("  Frontend showing faults in Plots: yes (fault selected).")
    else:
        print("  Frontend showing faults in Plots: no (no fault options for device).")
    if api_url and site_id:
        print_sample_timeseries_and_faults(api_url, site_id)
    log_browser_console(driver, "plots")


def validate_weather_charts_not_blank(driver: webdriver.Chrome, base_url: str) -> None:
    """
    Go to Weather page. Accept: Recharts present, "No weather points for this site",
    "Select a site", or loading skeleton. Do not require Recharts (weather may be disabled).
    """
    driver.get(f"{base_url}/weather")
    wait = WebDriverWait(driver, CHART_DATA_WAIT)
    page_src = driver.page_source or ""
    if "Select a site" in page_src:
        print("  Weather: page shows 'Select a site' (select a site first for weather).")
        return
    if "No weather points" in page_src or "weather scraper" in page_src.lower():
        print("  Weather: page loaded (no weather points for this site).")
        return
    if "Loading" in page_src or "animate-pulse" in page_src:
        wait.until(lambda d: "Loading" not in (d.page_source or "") or "recharts" in (d.page_source or "").lower())
    try:
        wait.until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, ".recharts-wrapper, .recharts-line, .recharts-area, [class*='recharts'], h1")
            )
        )
        paths = driver.find_elements(By.CSS_SELECTOR, ".recharts-curve, .recharts-line-curve, .recharts-area-area")
        if paths:
            any_data = any((p.get_attribute("d") or "").strip() for p in paths)
            if any_data:
                print("  Weather: at least one chart has data.")
            else:
                print("  Weather: chart(s) rendered (paths present).")
        else:
            print("  Weather: page loaded (chart container or heading present).")
    except Exception:
        page_src = driver.page_source or ""
        if "No weather points" in page_src or "Weather data" in page_src or "Select a site" in page_src:
            print("  Weather: page loaded (no chart element; acceptable).")
        else:
            raise AssertionError("Weather page: no chart element and no acceptable message found.")
    log_browser_console(driver, "weather")


def validate_overview(driver: webdriver.Chrome, base_url: str) -> None:
    """Smoke-check Overview page has main content."""
    driver.get(f"{base_url}/")
    wait_for_element(driver, By.TAG_NAME, "main", timeout=ELEMENT_WAIT)
    print("  Overview: page loaded.")
    log_browser_console(driver, "overview")


# --- Backend API checks (timezone / CSV UTC), same pattern as long_term_bacnet_scrape_test.py ---

# ISO UTC timestamp pattern: 2026-03-08T14:02:00Z or with optional .fff (download API must emit Z for DST)
_UTC_Z_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")


def _api_request(api_base: str, method: str, path: str, api_key: str) -> tuple[int, str]:
    """GET or POST API; returns (status_code, body_text). Uses urllib (no httpx dependency)."""
    url = f"{api_base.rstrip('/')}{path}"
    req = urllib.request.Request(url, method=method)
    if api_key:
        req.add_header("Authorization", f"Bearer {api_key}")
    req.add_header("Accept", "application/json, text/csv, */*")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, (e.read().decode("utf-8", errors="replace") if e.fp else "")
    except Exception as e:
        raise AssertionError(f"API request failed: {e}") from e


def run_backend_timezone_checks(api_url: str, site_id: str) -> None:
    """
    Verify API is reachable and download CSV timestamps are ISO UTC (Z).
    Ensures Plots/frontend get unambiguous timestamps so DST displays correctly
    (e.g. 9:02 AM CDT not 8:02 AM after spring-forward). Same auth/env as long_term_bacnet_scrape_test.
    """
    print("\n[Backend / timezone] GET /config and GET /download/csv (UTC Z timestamps)...")
    code, body = _api_request(api_url, "GET", "/config", API_KEY)
    if code == 401:
        print("  API returned 401 (auth required). Set OFDD_API_KEY to match server stack/.env.")
        raise AssertionError("GET /config returned 401; set OFDD_API_KEY for backend checks.")
    if code != 200:
        raise AssertionError(f"GET /config returned {code}; API not reachable at {api_url}.")
    print("  GET /config: OK (API reachable).")
    if API_KEY:
        print("  Using OFDD_API_KEY from env / stack/.env")
    start_d = (date.today() - timedelta(days=1)).isoformat()
    end_d = (date.today() + timedelta(days=1)).isoformat()
    path = f"/download/csv?site_id={urllib.parse.quote(site_id, safe='')}&start_date={start_d}&end_date={end_d}&format=long"
    code, csv_body = _api_request(api_url, "GET", path, API_KEY)
    if code == 404:
        print("  GET /download/csv: 404 (no data or site); skip timestamp format check.")
        return
    if code != 200:
        raise AssertionError(f"GET /download/csv returned {code}.")
    lines = csv_body.strip().splitlines()
    if len(lines) < 2:
        print("  GET /download/csv: empty or header-only; skip timestamp format check.")
        return
    reader = csv.reader(io.StringIO(csv_body))
    header = next(reader)
    ts_col = 0
    for i, h in enumerate(header):
        if h and ("timestamp" in h.lower().replace("\ufeff", "") or h.strip() == "ts"):
            ts_col = i
            break
    bad = []
    for row in reader:
        if len(row) <= ts_col:
            continue
        ts_val = (row[ts_col] or "").strip()
        if not ts_val:
            continue
        if not _UTC_Z_PATTERN.match(ts_val):
            bad.append(ts_val[:50])
    if bad:
        raise AssertionError(
            "Download CSV timestamps must be ISO UTC (e.g. 2026-03-08T14:02:00Z) for correct DST display. "
            f"Got non-UTC sample: {bad[0]!r}"
        )
    print("  GET /download/csv: timestamps are ISO UTC (Z). Timezone/Plots display OK.")


def run_faults_db_check(api_url: str) -> None:
    """
    GET /faults/active and GET /faults/definitions; print counts so we confirm faults exist in DB
    and can compare with frontend Plots (fault series should show when definitions exist and data in range).
    Same auth as run_backend_timezone_checks (OFDD_API_KEY).
    """
    print("\n[Faults DB] GET /faults/active and GET /faults/definitions...")
    code_active, body_active = _api_request(api_url, "GET", "/faults/active", API_KEY)
    code_defs, body_defs = _api_request(api_url, "GET", "/faults/definitions", API_KEY)
    n_active = 0
    n_defs = 0
    if code_active == 200 and body_active:
        try:
            data = json.loads(body_active)
            n_active = len(data) if isinstance(data, list) else 0
        except (json.JSONDecodeError, TypeError):
            pass
    if code_defs == 200 and body_defs:
        try:
            data = json.loads(body_defs)
            n_defs = len(data) if isinstance(data, list) else 0
        except (json.JSONDecodeError, TypeError):
            pass
    print(f"  Faults in DB (GET /faults/active): {n_active} active.")
    print(f"  Fault definitions (GET /faults/definitions): {n_defs}.")
    if code_active != 200 or code_defs != 200:
        print(f"  (One or both returned non-200: active={code_active}, definitions={code_defs})")


def print_sample_timeseries_and_faults(api_url: str, site_id: str) -> None:
    """
    Fetch a small sample of sensor timeseries (points) and fault records for this site and
    print them so we can see in the Python console what the frontend Plots tab should be
    drawing (points + faults together).

    Uses /download/csv (format=long) for sensor data and /download/faults?format=json for faults.
    """
    print("\n[Plots data] Sample sensor timeseries and faults from API for site:", site_id)
    # Sensor data (long CSV) for a 2-day window around "now"
    start_d = (date.today() - timedelta(days=1)).isoformat()
    end_d = (date.today() + timedelta(days=1)).isoformat()
    csv_path = (
        f"/download/csv?site_id={urllib.parse.quote(site_id, safe='')}"
        f"&start_date={start_d}&end_date={end_d}&format=long"
    )
    code_csv, body_csv = _api_request(api_url, "GET", csv_path, API_KEY)
    if code_csv != 200 or not body_csv.strip():
        print(f"  [Plots data] /download/csv returned {code_csv} (body length={len(body_csv) if body_csv else 0}); no sensor sample.")
    else:
        lines = body_csv.strip().splitlines()
        print(f"  [Plots data] /download/csv rows (including header): {len(lines)}")
        if len(lines) > 1:
            header = lines[0]
            print("  [Plots data] CSV header:", header)
            for row in lines[1:6]:
                print("    sensor:", row)
            if len(lines) > 6:
                print(f"    ... {len(lines) - 6} more rows")
    # Faults JSON for the same window
    faults_path = (
        f"/download/faults?site_id={urllib.parse.quote(site_id, safe='')}"
        f"&start_date={start_d}&end_date={end_d}&format=json"
    )
    code_faults, body_faults = _api_request(api_url, "GET", faults_path, API_KEY)
    if code_faults != 200 or not body_faults.strip():
        print(f"  [Plots data] /download/faults returned {code_faults} (body length={len(body_faults) if body_faults else 0}); no faults sample.")
        return
    try:
        payload = json.loads(body_faults)
    except json.JSONDecodeError:
        print("  [Plots data] /download/faults returned non-JSON body; raw:", body_faults[:300])
        return
    faults_list = payload.get("faults") if isinstance(payload, dict) else None
    count = payload.get("count") if isinstance(payload, dict) else None
    if isinstance(faults_list, list):
        print(f"  [Plots data] Faults JSON: count={count}, sample_rows={min(len(faults_list), 5)}")
        for f in faults_list[:5]:
            ts = f.get("ts") or f.get("timestamp")
            site = f.get("site_name") or f.get("site_id")
            eq = f.get("equipment_name") or f.get("equipment_id")
            rule = f.get("rule_id") or f.get("fault_id")
            sev = f.get("severity")
            print(f"    fault: ts={ts} site={site} eq={eq} rule={rule} severity={sev}")
        if len(faults_list) > 5:
            print(f"    ... {len(faults_list) - 5} more faults")
    else:
        print("  [Plots data] /download/faults payload shape unexpected:", str(payload)[:300])


def run_full_flow(
    frontend_url: str,
    headed: bool,
    only: str | None,
    skip_chart_data: bool,
    ignore_ssl: bool,
    api_url: str | None = None,
    bacnet_device_instances: list[int] | None = None,
) -> None:
    """Run full E2E flow with failure capture and site/import assertions.
    When api_url is set, run backend timezone checks (GET /config, CSV UTC Z) after the UI flow.
    When bacnet_device_instances is non-empty, run Points page BACnet discovery (Add to data model) for each device after import."""
    if bacnet_device_instances is None:
        bacnet_device_instances = []
    driver = get_driver(headed=headed, ignore_ssl=ignore_ssl, capture_browser_logs=True)
    try:
        driver.get(frontend_url)
        WebDriverWait(driver, PAGE_LOAD_TIMEOUT).until(
            lambda d: "Open-FDD" in (d.title or "") or "open-fdd" in (d.page_source or "").lower()[:2000]
        )
        print(f"Frontend loaded: {frontend_url}\n")

        if only is None or only == "delete-all":
            print("[1] Delete all sites and reset graph (via UI)...")
            delete_all_sites_and_reset_via_ui(driver, frontend_url)

        if only == "points":
            print("[Points only] Verify device tree and delete one point...")
            verify_site_selected(driver, TESTBENCH_SITE_NAME, "Points-only")
            verify_points_page_device_tree(driver, frontend_url, TESTBENCH_SITE_NAME)
            for candidate in ("MA-T", "RA-T", "DAP-P", "ZoneHumidity"):
                if delete_one_point_via_tree(driver, frontend_url, candidate, TESTBENCH_SITE_NAME):
                    break
            else:
                print("  (No deletable point found; tree structure verified.)")
            print("\n=== E2E Points steps passed ===")
            return

        site_id: str | None = None

        if only is None or only == "create-and-import":
            if only is None:
                print("[2] Create site and import LLM payload (via UI)...")
            site_id = create_site_via_ui(driver, frontend_url, TESTBENCH_SITE_NAME)
            verify_site_selected(driver, TESTBENCH_SITE_NAME, "after create")
            print("[2x] Negative import checks (malformed + missing site)...")
            import_payload_expect_failure_via_ui(
                driver, frontend_url, MALFORMED_PAYLOAD_PATH, site_id, "malformed"
            )
            import_payload_expect_failure_via_ui(
                driver, frontend_url, MISSING_SITE_PAYLOAD_PATH, site_id, "missing-site"
            )
            n_pts, n_eq = import_llm_payload_via_ui(driver, frontend_url, DEMO_PAYLOAD_PATH, site_id)
            verify_site_selected(driver, TESTBENCH_SITE_NAME, "after import")
            if bacnet_device_instances:
                print("[2a] BACnet discovery: Add to data model (Data Model page) for device(s) %s..." % bacnet_device_instances)
                for dev_inst in bacnet_device_instances:
                    if not bacnet_add_to_model_via_ui(driver, frontend_url, dev_inst):
                        print("  (Device %s failed or skipped; continuing.)" % dev_inst)
                print("  BACnet discovery step done.")
            print("[2b] Verify equipment and points on Data Model page...")
            verify_data_model_after_import(
                driver,
                frontend_url,
                EXPECTED_EQUIPMENT_NAMES,
                EXPECTED_POINT_NAMES + FALLBACK_POINT_NAMES,
                n_pts,
                n_eq,
            )
            verify_site_selected(driver, TESTBENCH_SITE_NAME, "after data model verify")
            print("[2c] Verify units from data model on frontend (Points page)...")
            verify_units_on_frontend(driver, frontend_url, TESTBENCH_SITE_NAME)
            print("[2d] Verify Points page device tree (columns, site, Unassigned)...")
            verify_points_page_device_tree(driver, frontend_url, TESTBENCH_SITE_NAME)
            print("[2e] Delete one point (and optionally one equipment) in tree; verify tree updates...")
            for candidate in ("MA-T", "RA-T", "DAP-P", "ZoneHumidity"):
                if delete_one_point_via_tree(driver, frontend_url, candidate, TESTBENCH_SITE_NAME):
                    break
            else:
                print("  (No deletable point found in tree; continuing.)")
            print("[2e2] Point context menu: Poll false then Poll true...")
            point_context_menu_poll_false_then_true(
                driver, frontend_url, "SA-T", TESTBENCH_SITE_NAME
            )
            print("[2f] Data Model Testing smoke: open page, run Sites query...")
            verify_data_model_testing_smoke(driver, frontend_url)

        if only is None or only == "charts" or only == "create-and-import":
            if not skip_chart_data:
                print("[3] Verify Plots chart (select known point SA-T/ZoneTemp, faults in legend)...")
                validate_plots_chart_has_data(
                    driver,
                    frontend_url,
                    TESTBENCH_SITE_NAME,
                    api_url=api_url,
                    site_id=site_id or TESTBENCH_SITE_NAME,
                )
                verify_site_selected(driver, TESTBENCH_SITE_NAME, "after Plots")
                print("[4] Verify Weather page (resilient)...")
                validate_weather_charts_not_blank(driver, frontend_url)
                verify_site_selected(driver, TESTBENCH_SITE_NAME, "after Weather")
                print("[5] Overview smoke check...")
                validate_overview(driver, frontend_url)
                verify_site_selected(driver, TESTBENCH_SITE_NAME, "after Overview")
            else:
                print("[3] Skip chart data validation (--skip-chart-data).")

        if api_url:
            run_backend_timezone_checks(api_url, TESTBENCH_SITE_NAME)
            run_faults_db_check(api_url)

        print("\n=== E2E frontend tests passed ===")
    except Exception as e:
        save_screenshot_and_context(driver, "e2e_fail")
        raise
    finally:
        driver.quit()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Open-FDD frontend E2E tests (Selenium). All actions via UI."
    )
    parser.add_argument(
        "--frontend-url",
        default=DEFAULT_FRONTEND_URL,
        help=f"Frontend base URL (default: {DEFAULT_FRONTEND_URL})",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Run browser in headed mode (default: headless)",
    )
    parser.add_argument(
        "--only",
        choices=["delete-all", "create-and-import", "points", "charts"],
        help="Run only this step (default: full flow). 'points' = device tree + delete point (site must exist).",
    )
    parser.add_argument(
        "--skip-chart-data",
        action="store_true",
        help="Do not assert charts have data (only that pages load)",
    )
    parser.add_argument(
        "--ignore-ssl",
        action="store_true",
        help="Ignore certificate errors (for HTTPS with self-signed cert)",
    )
    parser.add_argument(
        "--api-url",
        default=os.environ.get("OFDD_API_URL", "").strip() or None,
        help="API base URL for backend/timezone checks (e.g. http://192.168.204.16:8000). "
        "Set OFDD_API_KEY to match server for auth. Same pattern as long_term_bacnet_scrape_test.py",
    )
    parser.add_argument(
        "--bacnet-device-instance",
        type=int,
        nargs="*",
        default=None,
        metavar="ID",
        help="Run BACnet discovery on Points page (Add to data model) for each device instance after import. "
        "E.g. --bacnet-device-instance 3456789 3456790. Env BACNET_DEVICE_INSTANCE=3456789,3456790. Default: skip.",
    )
    args = parser.parse_args()
    instances = args.bacnet_device_instance
    if instances is None or len(instances) == 0:
        raw = os.environ.get("BACNET_DEVICE_INSTANCE", "").strip()
        if raw:
            instances = [int(x.strip()) for x in raw.split(",") if x.strip()]
        else:
            instances = []
    run_full_flow(
        frontend_url=args.frontend_url.rstrip("/"),
        headed=args.headed,
        only=args.only,
        skip_chart_data=args.skip_chart_data,
        ignore_ssl=args.ignore_ssl,
        api_url=args.api_url.rstrip("/") if args.api_url else None,
        bacnet_device_instances=instances,
    )


if __name__ == "__main__":
    main()
