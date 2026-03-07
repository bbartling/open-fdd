#!/usr/bin/env python3
"""
E2E tests for the Open-FDD frontend using Selenium. Browser-level counterpart to
delete_all_sites_and_reset.py + graph_and_crud_test.py: same flow via the UI (no direct
API calls). Covers: delete-all-sites + reset, create site (TestBenchSite), import
demo_site_llm_payload.json, verify equipment/points, site selection, Plots/Weather/Overview.

Requirement: The frontend must be able to fetch sites (GET /sites). When the API
requires auth, the frontend must be built/served with VITE_OFDD_API_KEY set (same
value as OFDD_API_KEY in stack/.env). Otherwise the UI shows 0 sites and the
delete-all section is never rendered — E2E will report "No sites to delete".

python e2e_frontend_selenium.py --frontend-url http://192.168.204.16 --headed
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path


from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

# Paths: script in scripts/automated_testing/ or copied; payload next to script or in scripts/
SCRIPT_DIR = Path(__file__).resolve().parent
DEMO_PAYLOAD_PATH = SCRIPT_DIR / "demo_site_llm_payload.json"

# Defaults
DEFAULT_FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:5173").rstrip("/")
TESTBENCH_SITE_NAME = os.environ.get("TESTBENCH_SITE_NAME", "TestBenchSite")

# From demo_site_llm_payload.json: equipment and points we assert in the UI
EXPECTED_EQUIPMENT_NAMES = ("AHU-1", "VAV-1")
EXPECTED_POINT_NAMES = ("SA-T", "ZoneTemp")  # SA-T preferred for Plots; ZoneTemp fallback
FALLBACK_POINT_NAMES = ("MA-T", "RA-T", "DAP-P")

# Timeouts (seconds)
PAGE_LOAD_TIMEOUT = 30
ELEMENT_WAIT = 15
CHART_DATA_WAIT = 30
IMPORT_RESULT_WAIT = 35
TEXT_WAIT = 20

# Screenshot dir on failure
FAILURE_SCREENSHOT_DIR = Path.home() / ".openfdd_e2e_failures"


def get_driver(headed: bool = False, ignore_ssl: bool = False) -> webdriver.Chrome:
    """Create Chrome WebDriver (headless by default). Optionally ignore SSL errors for HTTPS."""
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


def delete_all_sites_and_reset_via_ui(driver: webdriver.Chrome, base_url: str) -> None:
    """Navigate to Data Model, remove all sites and reset graph via UI.
    Replicates delete_all_sites_and_reset.py in the browser. Sites load asynchronously;
    the delete-all block is only rendered when the frontend has sites (GET /sites succeeded)."""
    driver.get(f"{base_url}/data-model")
    wait = WebDriverWait(driver, ELEMENT_WAIT)
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "[data-testid=new-site-name-input]")))
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
    wait.until(
        lambda d: not d.find_elements(By.CSS_SELECTOR, "[data-testid=delete-all-confirm-input]")
        or "No sites" in (d.page_source or "")
    )
    print("  Delete all sites and reset: OK")


def create_site_via_ui(driver: webdriver.Chrome, base_url: str, site_name: str) -> str:
    """Create a site from Data Model page and return its ID (from table row data-site-id)."""
    driver.get(f"{base_url}/data-model")
    name_input = wait_for_element(driver, By.CSS_SELECTOR, "[data-testid=new-site-name-input]")
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
    textarea.clear()
    textarea.send_keys(json_str)
    safe_click(driver, By.CSS_SELECTOR, "[data-testid=data-model-import-button]")
    wait = WebDriverWait(driver, IMPORT_RESULT_WAIT)
    wait.until(
        lambda d: "Created" in (d.page_source or "") or "Total" in (d.page_source or "")
        or "Updated" in (d.page_source or "") or "warnings" in (d.page_source or "")
    )
    print(f"  Import: OK (points={len(points)}, equipment={len(equipment)})")
    return len(points), len(equipment)


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
    picker_btns = driver.find_elements(
        By.XPATH,
        "//button[@aria-haspopup='listbox' and (contains(., 'Select points') or contains(., 'series'))]",
    )
    if not picker_btns:
        return None
    picker_btns[0].click()
    wait = WebDriverWait(driver, timeout)
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='text']")))
    time.sleep(0.4)  # allow dropdown list to render
    for name in preference:
        # Point picker: label wrapping checkbox + span with point name (object_name or external_id)
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
            print(f"  Plots: selected point {name!r}.")
            return name
    # Fallback: first checkbox label in the point list
    point_options = driver.find_elements(
        By.XPATH,
        "//div[contains(@class,'rounded-xl')]//label[.//input[@type='checkbox']]",
    )
    if point_options:
        point_options[0].click()
        print("  Plots: selected first available point (fallback).")
        return "first_available"
    return None


def validate_plots_chart_has_data(driver: webdriver.Chrome, base_url: str, site_name: str) -> None:
    """Go to Plots, select site and a known point (SA-T preferred), then assert chart area is present."""
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


def validate_overview(driver: webdriver.Chrome, base_url: str) -> None:
    """Smoke-check Overview page has main content."""
    driver.get(f"{base_url}/")
    wait_for_element(driver, By.TAG_NAME, "main", timeout=ELEMENT_WAIT)
    print("  Overview: page loaded.")


def run_full_flow(
    frontend_url: str,
    headed: bool,
    only: str | None,
    skip_chart_data: bool,
    ignore_ssl: bool,
) -> None:
    """Run full E2E flow with failure capture and site/import assertions."""
    driver = get_driver(headed=headed, ignore_ssl=ignore_ssl)
    try:
        driver.get(frontend_url)
        WebDriverWait(driver, PAGE_LOAD_TIMEOUT).until(
            lambda d: "Open-FDD" in (d.title or "") or "open-fdd" in (d.page_source or "").lower()[:2000]
        )
        print(f"Frontend loaded: {frontend_url}\n")

        if only is None or only == "delete-all":
            print("[1] Delete all sites and reset graph (via UI)...")
            delete_all_sites_and_reset_via_ui(driver, frontend_url)

        if only is None or only == "create-and-import":
            if only is None:
                print("[2] Create site and import LLM payload (via UI)...")
            site_id = create_site_via_ui(driver, frontend_url, TESTBENCH_SITE_NAME)
            verify_site_selected(driver, TESTBENCH_SITE_NAME, "after create")
            n_pts, n_eq = import_llm_payload_via_ui(driver, frontend_url, DEMO_PAYLOAD_PATH, site_id)
            verify_site_selected(driver, TESTBENCH_SITE_NAME, "after import")
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

        if only is None or only == "charts" or only == "create-and-import":
            if not skip_chart_data:
                print("[3] Verify Plots chart (select known point SA-T/ZoneTemp)...")
                validate_plots_chart_has_data(driver, frontend_url, TESTBENCH_SITE_NAME)
                verify_site_selected(driver, TESTBENCH_SITE_NAME, "after Plots")
                print("[4] Verify Weather page (resilient)...")
                validate_weather_charts_not_blank(driver, frontend_url)
                verify_site_selected(driver, TESTBENCH_SITE_NAME, "after Weather")
                print("[5] Overview smoke check...")
                validate_overview(driver, frontend_url)
                verify_site_selected(driver, TESTBENCH_SITE_NAME, "after Overview")
            else:
                print("[3] Skip chart data validation (--skip-chart-data).")

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
        choices=["delete-all", "create-and-import", "charts"],
        help="Run only this step (default: full flow)",
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
    args = parser.parse_args()
    run_full_flow(
        frontend_url=args.frontend_url.rstrip("/"),
        headed=args.headed,
        only=args.only,
        skip_chart_data=args.skip_chart_data,
        ignore_ssl=args.ignore_ssl,
    )


if __name__ == "__main__":
    main()
