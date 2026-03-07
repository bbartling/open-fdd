#!/usr/bin/env python3
"""
E2E tests for the Open-FDD frontend using Selenium. All actions are performed via the UI
(no direct API calls from this script). Covers: delete-all-sites + reset, create site,
import LLM payload, and validation that charts render and (when data exists) show data.

Requires: pip install -e ".[e2e]"  (selenium, webdriver-manager)
Stack: frontend + API + DB (and optionally BACnet scraper for chart data).
Default frontend URL: http://localhost:5173 (or set FRONTEND_URL).

Usage:
  # Full flow: delete all, create site, import demo payload, validate charts
  python scripts/e2e_frontend_selenium.py

  # Only delete-all and reset
  python scripts/e2e_frontend_selenium.py --only delete-all

  # Only chart validation (assumes site + data already exist)
  python scripts/e2e_frontend_selenium.py --only charts

  # Headed browser (default is headless)
  python scripts/e2e_frontend_selenium.py --headed
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Optional: use webdriver_manager to get ChromeDriver
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options as ChromeOptions
    from selenium.webdriver.chrome.service import Service as ChromeService
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait
    from webdriver_manager.chrome import ChromeDriverManager
except ImportError as e:
    print("Install e2e deps: pip install -e \".[e2e]\"  (selenium, webdriver-manager)", file=sys.stderr)
    raise SystemExit(1) from e

# Paths
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
DEMO_PAYLOAD_PATH = SCRIPT_DIR / "demo_site_llm_payload.json"

# Defaults
DEFAULT_FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:5173").rstrip("/")
TESTBENCH_SITE_NAME = os.environ.get("TESTBENCH_SITE_NAME", "TestBenchSite")

# Timeouts (seconds)
PAGE_LOAD_TIMEOUT = 30
ELEMENT_WAIT = 15
CHART_DATA_WAIT = 25
IMPORT_RESULT_WAIT = 30


def get_driver(headed: bool = False) -> webdriver.Chrome:
    """Create Chrome WebDriver (headless by default)."""
    from selenium.common.exceptions import WebDriverException

    options = ChromeOptions()
    if not headed:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    try:
        service = ChromeService(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)
        return driver
    except WebDriverException as e:
        msg = str(e).lower()
        if "chrome" in msg and ("binary" in msg or "cannot find" in msg or "not found" in msg):
            print(
                "Chrome/Chromium not found. Install a browser (e.g. apt install chromium-browser) or run with Chrome.",
                file=sys.stderr,
            )
            print("E2E tests are optional and not run in CI; use them locally when the stack and Chrome are available.", file=sys.stderr)
        raise


def wait_and_find(driver: webdriver.Chrome, by: str, value: str, timeout: float = ELEMENT_WAIT):
    """Wait for element and return it."""
    wait = WebDriverWait(driver, timeout)
    return wait.until(EC.presence_of_element_located((by, value)))


def wait_and_clickable(driver: webdriver.Chrome, by: str, value: str, timeout: float = ELEMENT_WAIT):
    """Wait for element to be clickable and return it."""
    wait = WebDriverWait(driver, timeout)
    return wait.until(EC.element_to_be_clickable((by, value)))


def delete_all_sites_and_reset_via_ui(driver: webdriver.Chrome, base_url: str) -> None:
    """Navigate to Data Model, remove all sites and reset graph via UI."""
    driver.get(f"{base_url}/data-model")
    wait = WebDriverWait(driver, ELEMENT_WAIT)
    # Wait for Data Model page (Sites card with Add site or delete-all section)
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "[data-testid=new-site-name-input]")))
    confirm_input = driver.find_elements(By.CSS_SELECTOR, "[data-testid=delete-all-confirm-input]")
    if not confirm_input:
        print("  No sites to delete.")
        return
    confirm_input = confirm_input[0]

    placeholder = confirm_input.get_attribute("placeholder") or ""
    # Placeholder is "Type N to confirm" -> extract N
    try:
        n = int(placeholder.replace("Type", "").replace("to confirm", "").strip())
    except ValueError:
        n = 1
    confirm_input.clear()
    confirm_input.send_keys(str(n))
    btn = wait_and_clickable(driver, By.CSS_SELECTOR, "[data-testid=delete-all-and-reset-button]")
    btn.click()
    # Wait for the delete-all section to disappear (sites list empty) or for "No sites"
    wait.until(
        lambda d: not d.find_elements(By.CSS_SELECTOR, "[data-testid=delete-all-confirm-input]")
        or "No sites" in (d.page_source or "")
    )
    print("  Delete all sites and reset: OK")


def create_site_via_ui(driver: webdriver.Chrome, base_url: str, site_name: str) -> str:
    """Create a site from Data Model page and return its ID (from table row data-site-id)."""
    driver.get(f"{base_url}/data-model")
    name_input = wait_and_find(driver, By.CSS_SELECTOR, "[data-testid=new-site-name-input]")
    name_input.clear()
    name_input.send_keys(site_name)
    add_btn = wait_and_clickable(driver, By.CSS_SELECTOR, "[data-testid=add-site-button]")
    add_btn.click()
    # Wait for site to appear in table (row with data-site-id and text site_name)
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
) -> None:
    """Load JSON payload, inject site_id into points and equipment, paste and import via UI."""
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
    textarea = wait_and_find(driver, By.CSS_SELECTOR, "[data-testid=data-model-import-json]")
    textarea.clear()
    textarea.send_keys(json_str)
    import_btn = wait_and_clickable(driver, By.CSS_SELECTOR, "[data-testid=data-model-import-button]")
    import_btn.click()
    # Wait for result: "Created:" or "Total:" or "Updated:" in the same card
    wait = WebDriverWait(driver, IMPORT_RESULT_WAIT)
    wait.until(
        lambda d: "Created" in (d.page_source or "") or "Total" in (d.page_source or "") or "Updated" in (d.page_source or "") or "warnings" in (d.page_source or "")
    )
    print(f"  Import: OK (points={len(points)}, equipment={len(equipment)})")


def select_site_in_topbar(driver: webdriver.Chrome, site_name: str) -> None:
    """Open site selector in top bar and click the option with the given name."""
    # Site selector is the listbox button that shows "All Sites" or a site name (not "Select points")
    wait = WebDriverWait(driver, ELEMENT_WAIT)
    selector_btn = wait.until(
        EC.element_to_be_clickable(
            (By.XPATH, "//button[@aria-haspopup='listbox' and (contains(., 'All Sites') or contains(., 'Site'))]")
        )
    )
    selector_btn.click()
    # Dropdown: click the option that contains the site name (span with truncated text)
    site_option = wait.until(
        EC.element_to_be_clickable(
            (By.XPATH, f"//div[contains(@class,'rounded-2xl')]//button[.//span[contains(text(), '{site_name}')]]")
        )
    )
    site_option.click()


def validate_plots_chart_has_data(driver: webdriver.Chrome, base_url: str, site_name: str) -> None:
    """Go to Plots, select site and at least one point, then assert chart is not blank (has data or rendered)."""
    driver.get(f"{base_url}/plots")
    # If "Select a site" is shown, select the site
    if "Select a site" in (driver.page_source or ""):
        select_site_in_topbar(driver, site_name)
        WebDriverWait(driver, ELEMENT_WAIT).until(
            lambda d: "Select a site" not in (d.page_source or "") or "Select points" in (d.page_source or "")
        )
    else:
        select_site_in_topbar(driver, site_name)

    # Wait for page to show either "Select points" or chart
    wait = WebDriverWait(driver, ELEMENT_WAIT)
    wait.until(
        EC.presence_of_element_located(
            (By.XPATH, "//*[contains(text(), 'Select points') or contains(@class, 'recharts')]")
        )
    )
    # Open point picker and select first available point
    point_picker_btn = driver.find_elements(
        By.XPATH,
        "//button[@aria-haspopup='listbox' and contains(., 'Select points') or contains(., 'series')]",
    )
    if point_picker_btn:
        point_picker_btn[0].click()
        # In the dropdown, click first point option (listbox item or button with external_id-like text)
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='text']")))
        # Click first row that looks like a point (e.g. SA-T, ZoneTemp, or any button in the list)
        point_options = driver.find_elements(
            By.XPATH,
            "//div[contains(@class,'rounded-xl')]//button[.//span[contains(@class,'truncate')]]",
        )
        if point_options:
            point_options[0].click()

    # Wait for chart: either Recharts SVG with data (curve path) or "No point data" message
    wait_chart = WebDriverWait(driver, CHART_DATA_WAIT)
    try:
        # Recharts uses .recharts-curve for Line; path has "d" attribute with line data
        path_with_data = wait_chart.until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, ".recharts-curve, .recharts-line-curve, path.recharts-curve")
            )
        )
        d_attr = path_with_data.get_attribute("d") or ""
        if len(d_attr) > 20:
            print("  Plots: chart has data (path d length > 20).")
        else:
            print("  Plots: chart rendered (path present).")
    except Exception:
        # Accept "No point data in this range" as valid (chart rendered, scraper may not have data yet)
        if "No point data" in (driver.page_source or "") or "Select points" in (driver.page_source or ""):
            print("  Plots: chart area rendered (no timeseries data in range yet).")
        else:
            raise AssertionError("Plots page: no chart curve/path and no 'no data' message found.")


def validate_weather_charts_not_blank(driver: webdriver.Chrome, base_url: str) -> None:
    """Go to Weather page and assert at least one chart panel is present and not broken."""
    driver.get(f"{base_url}/weather")
    wait = WebDriverWait(driver, CHART_DATA_WAIT)
    # Weather page has Recharts or "No data" / skeleton
    try:
        # Recharts container or line/area
        wait.until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, ".recharts-wrapper, .recharts-line, .recharts-area, [class*='recharts']")
            )
        )
        # If it's a wrapper, check for inner path
        paths = driver.find_elements(By.CSS_SELECTOR, ".recharts-curve, .recharts-line-curve, .recharts-area-area")
        if paths:
            any_data = any((p.get_attribute("d") or "").strip() for p in paths)
            if any_data:
                print("  Weather: at least one chart has data.")
            else:
                print("  Weather: chart(s) rendered (paths present).")
        else:
            print("  Weather: chart container present.")
    except Exception:
        if "No data" in (driver.page_source or "") or "Loading" in (driver.page_source or ""):
            print("  Weather: page loaded (no weather data yet).")
        else:
            raise AssertionError("Weather page: no chart element found.")


def validate_overview_or_faults_charts(driver: webdriver.Chrome, base_url: str) -> None:
    """Smoke-check Overview or Faults page has content (optional)."""
    driver.get(f"{base_url}/")
    wait = WebDriverWait(driver, ELEMENT_WAIT)
    wait.until(EC.presence_of_element_located((By.TAG_NAME, "main")))
    print("  Overview: page loaded.")


def run_full_flow(
    frontend_url: str,
    headed: bool,
    only: str | None,
    skip_chart_data: bool,
) -> None:
    """Run e2e flow: delete all -> create site -> import -> validate charts (or only requested step)."""
    driver = get_driver(headed=headed)
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
            import_llm_payload_via_ui(driver, frontend_url, DEMO_PAYLOAD_PATH, site_id)

        if only is None or only == "charts" or only == "create-and-import":
            if not skip_chart_data:
                print("[3] Validate Plots chart (not blank)...")
                validate_plots_chart_has_data(driver, frontend_url, TESTBENCH_SITE_NAME)
                print("[4] Validate Weather chart(s) (not blank)...")
                validate_weather_charts_not_blank(driver, frontend_url)
                print("[5] Overview smoke check...")
                validate_overview_or_faults_charts(driver, frontend_url)
            else:
                print("[3] Skip chart data validation (--skip-chart-data).")

        print("\n=== E2E frontend tests passed ===")
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
    args = parser.parse_args()
    run_full_flow(
        frontend_url=args.frontend_url.rstrip("/"),
        headed=args.headed,
        only=args.only,
        skip_chart_data=args.skip_chart_data,
    )


if __name__ == "__main__":
    main()
