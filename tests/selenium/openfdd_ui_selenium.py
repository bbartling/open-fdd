#!/usr/bin/env python3
"""Selenium UI validation for Open-FDD dashboard (plots, SQL, buttons)."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

from openfdd_test_lib import Check, RunResult, bench_config, bench_root, log, resolve_password, utc_now

try:
    from selenium import webdriver
    from selenium.common.exceptions import NoSuchElementException, TimeoutException, WebDriverException
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import Select, WebDriverWait
except ImportError as exc:
    webdriver = None  # type: ignore
    WebDriverException = Exception  # type: ignore
    _IMPORT_ERR = exc
else:
    _IMPORT_ERR = None


ROUTES = [
    ("/", "home"),
    ("/model", "model"),
    ("/sql-fdd", "sql-fdd"),
    ("/host", "host"),
    ("/plot", "plot"),
    ("/modbus", "modbus"),
    ("/bacnet", "bacnet"),
    ("/live-fdd-validation", "live-fdd-validation"),
]


def ui_base_url(api_base: str) -> str:
    """When Selenium runs in Docker, localhost is the container — use host gateway."""
    if os.environ.get("OPENFDD_UI_BASE"):
        return os.environ["OPENFDD_UI_BASE"].rstrip("/")
    remote = os.environ.get("OPENFDD_SELENIUM_URL", "").strip()
    host_net = os.environ.get("OPENFDD_SELENIUM_HOST_NETWORK", "0") == "1"
    if remote and not host_net and api_base.startswith("http://127.0.0.1"):
        return api_base.replace("127.0.0.1", "host.docker.internal", 1)
    if remote and not host_net and api_base.startswith("http://localhost"):
        return api_base.replace("localhost", "host.docker.internal", 1)
    return api_base.rstrip("/")


def create_driver(base_url: str) -> Any:
    if webdriver is None:
        raise RuntimeError(f"selenium not installed: {_IMPORT_ERR}")

    remote = os.environ.get("OPENFDD_SELENIUM_URL", "").strip()
    opts = webdriver.ChromeOptions()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1600,1200")
    opts.add_argument("--disable-gpu")
    if not remote:
        opts.add_argument("--host-resolver-rules=MAP localhost 127.0.0.1")

    if remote:
        log(f"selenium remote → {remote}")
        return webdriver.Remote(command_executor=remote, options=opts)

    for binary in (
        os.environ.get("OPENFDD_CHROME_BINARY"),
        "/usr/bin/google-chrome",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
    ):
        if binary and Path(binary).exists():
            opts.binary_location = binary
            break

    try:
        from selenium.webdriver.chrome.service import Service
        from webdriver_manager.chrome import ChromeDriverManager

        service = Service(ChromeDriverManager().install())
        return webdriver.Chrome(service=service, options=opts)
    except WebDriverException as exc:
        raise RuntimeError(
            "No Chrome/Chromium found. Set OPENFDD_SELENIUM_URL=http://127.0.0.1:4444/wd/hub "
            "and run scripts/openfdd_selenium_up.sh"
        ) from exc


def inject_token(driver: Any, base_url: str, token: str) -> None:
    driver.get(f"{base_url.rstrip('/')}/login")
    driver.execute_script("window.sessionStorage.setItem('ofdd_token', arguments[0]);", token)
    driver.get(f"{base_url.rstrip('/')}/")


def login_form(driver: Any, base_url: str, user: str, password: str) -> None:
    driver.get(f"{base_url.rstrip('/')}/login")
    wait = WebDriverWait(driver, 20)
    wait.until(EC.presence_of_element_located((By.ID, "login-username")))
    driver.find_element(By.ID, "login-username").clear()
    driver.find_element(By.ID, "login-username").send_keys(user)
    driver.find_element(By.ID, "login-password").clear()
    driver.find_element(By.ID, "login-password").send_keys(password)
    driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
    wait.until(lambda d: "/login" not in d.current_url)


def screenshot(driver: Any, path: Path, name: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    try:
        driver.save_screenshot(str(path / f"{name}.png"))
    except WebDriverException:
        pass


def assert_no_error_banner(driver: Any) -> str | None:
    for sel in (".error-banner", "p.error", ".error"):
        try:
            el = driver.find_element(By.CSS_SELECTOR, sel)
            if el.is_displayed() and el.text.strip():
                return el.text.strip()
        except NoSuchElementException:
            continue
    return None


def tab_crash_message(driver: Any, tab: str) -> str | None:
    """TabErrorBoundary renders: `<tab> crashed: <message>` inside `.panel.error`."""
    body = driver.find_element(By.TAG_NAME, "body").text
    needle = f"{tab} crashed:"
    if needle not in body:
        return None
    for line in body.splitlines():
        if needle in line:
            return line.strip()
    return needle


def test_route_load(driver: Any, base: str, route: str, label: str, shots: Path) -> Check:
    url = f"{base.rstrip('/')}{route}"
    driver.get(url)
    time.sleep(1.5)
    screenshot(driver, shots, f"route_{label}")
    if "/login" in driver.current_url and route != "/login":
        return Check(f"ui-route-{label}", "FAIL", f"redirected to login from {route}")
    crash = tab_crash_message(driver, label)
    if crash:
        return Check(
            f"ui-route-{label}",
            "FAIL",
            crash[:240],
            product_bug=True,
        )
    err = assert_no_error_banner(driver)
    if err:
        if "unknown endpoint" in err.lower():
            return Check(f"ui-route-{label}", "SKIP", f"optional route {route}: {err[:120]}")
        return Check(f"ui-route-{label}", "FAIL", f"error banner on {route}: {err[:200]}")
    body = driver.find_element(By.TAG_NAME, "body").text
    if len(body.strip()) < 20:
        return Check(f"ui-route-{label}", "FAIL", f"empty body on {route}")
    return Check(f"ui-route-{label}", "PASS", f"{route} loaded")


def test_model_page(driver: Any, shots: Path) -> list[Check]:
    checks: list[Check] = []
    body = driver.find_element(By.TAG_NAME, "body").text
    if "site:import" in body:
        checks.append(
            Check(
                "ui-model-site",
                "FAIL",
                "Model page still shows site:import — agent bootstrap did not replace stale CSV model",
                product_bug=True,
            )
        )
    elif "site:local" in body or "equip:validation" in body or "equip:local" in body:
        checks.append(Check("ui-model-site", "PASS", "OT site/equip visible on model page"))
    else:
        checks.append(Check("ui-model-site", "FAIL", "no recognizable OT site on model page", product_bug=True))

    for text in ("Import", "Explorer", "Export"):
        if text in body:
            checks.append(Check(f"ui-model-tab-{text.lower()}", "PASS", f"tab '{text}' present"))
    screenshot(driver, shots, "model_page")
    return checks


def test_sql_page(driver: Any, shots: Path) -> list[Check]:
    checks: list[Check] = []
    crash = tab_crash_message(driver, "sql-fdd")
    if crash:
        checks.append(Check("ui-sql-tab-crash", "FAIL", crash[:240], product_bug=True))
        screenshot(driver, shots, "sql_page_crash")
        return checks
    checks.append(Check("ui-sql-tab-crash", "PASS", "SQL FDD tab did not crash"))

    body = driver.find_element(By.TAG_NAME, "body").text
    if "SQL FDD Rules" not in body:
        checks.append(Check("ui-sql-title", "FAIL", "SQL FDD Rules heading missing"))
        return checks
    checks.append(Check("ui-sql-title", "PASS", "SQL FDD Rules page rendered"))

    # v3.2.6+ ships CodeMirror-only SQL tab (Visual/NL mode tabs removed — FIX-4)
    legacy_modes = ("Visual rule", "SQL editor", "NL prompt")
    if any(label in body for label in legacy_modes):
        for mode, label in (("visual", "Visual rule"), ("sql", "SQL editor"), ("prompt", "NL prompt")):
            try:
                btn = driver.find_element(By.XPATH, f"//button[contains(normalize-space(),'{label}')]")
                btn.click()
                time.sleep(0.5)
                checks.append(Check(f"ui-sql-mode-{mode}", "PASS", f"legacy mode button '{label}' clickable"))
            except NoSuchElementException:
                checks.append(Check(f"ui-sql-mode-{mode}", "FAIL", f"legacy mode button '{label}' missing"))
    else:
        checks.append(Check("ui-sql-legacy-modes-absent", "PASS", "v3.2.6+ SQL tab — no Visual/NL mode chrome (FIX-4 shipped)"))

    cm_editors = driver.find_elements(By.CSS_SELECTOR, ".cm-editor, .cm-content, .CodeMirror")
    if cm_editors:
        checks.append(Check("ui-sql-codemirror", "PASS", f"CodeMirror editor present ({len(cm_editors)} node(s))"))
    else:
        checks.append(Check("ui-sql-codemirror", "FAIL", "CodeMirror editor missing — SqlFddQueryEditor not rendered"))

    if "telemetry_pivot" in body or "telemetry" in body:
        checks.append(Check("ui-sql-historian-table", "PASS", "historian table selector visible"))
    else:
        checks.append(Check("ui-sql-historian-table", "FAIL", "historian table dropdown missing"))

    for label, check_name in (("Format SQL", "ui-sql-btn-format"), ("Validate", "ui-sql-btn-validate"), ("Run query", "ui-sql-btn-run")):
        hits = driver.find_elements(By.XPATH, f"//button[contains(normalize-space(),'{label}')]")
        if hits:
            checks.append(Check(check_name, "PASS", f"'{label}' button present"))
        else:
            checks.append(Check(check_name, "FAIL", f"'{label}' button missing"))

    # Back-compat alias for older report scripts
    if any(c.name == "ui-sql-btn-validate" and c.status == "PASS" for c in checks):
        checks.append(Check("ui-sql-textarea", "PASS", "CodeMirror replaces legacy textarea flow (v3.2.6+)"))

    try:
        wait = WebDriverWait(driver, 15)
        equip_select = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".gf-context-bar select")))
        time.sleep(1)
        sel = Select(equip_select)
        opts = [o.get_attribute("value") for o in sel.options if o.get_attribute("value")]
        if opts:
            checks.append(Check("ui-sql-equipment-select", "PASS", f"equipment options={opts[:3]}"))
        else:
            checks.append(Check("ui-sql-equipment-select", "FAIL", "equipment dropdown empty", product_bug=True))
    except TimeoutException:
        checks.append(Check("ui-sql-equipment-select", "FAIL", "equipment dropdown missing"))

    screenshot(driver, shots, "sql_page")
    return checks


def test_plot_page(driver: Any, shots: Path) -> list[Check]:
    checks: list[Check] = []
    body = driver.find_element(By.TAG_NAME, "body").text
    if "Telemetry" not in body and "Refresh chart" not in body:
        checks.append(Check("ui-plot-page", "FAIL", "plot page missing expected controls"))
        return checks
    checks.append(Check("ui-plot-page", "PASS", "plot page controls present"))

    if "No numeric columns" in body or "No points for this device" in body:
        checks.append(
            Check(
                "ui-plot-catalog",
                "FAIL",
                "no telemetry series in feather/historian — polling not feeding plot catalog",
                product_bug=True,
            )
        )
    else:
        chips = driver.find_elements(By.CSS_SELECTOR, ".plot-series-chips .chip")
        if chips:
            chips[0].click()
            time.sleep(0.3)
            checks.append(Check("ui-plot-series-select", "PASS", f"selected series chip ({len(chips)} available)"))
        else:
            checks.append(Check("ui-plot-series-select", "FAIL", "no series chips to select", product_bug=True))

    try:
        refresh = driver.find_element(By.XPATH, "//button[contains(normalize-space(),'Refresh chart')]")
        refresh.click()
        time.sleep(3)
        chart = driver.find_elements(By.CSS_SELECTOR, ".plot-chart .js-plotly-plot, .plot-chart svg, .plot-chart canvas")
        if chart:
            checks.append(Check("ui-plot-render", "PASS", "Plotly chart rendered after refresh"))
        else:
            loading = driver.find_elements(By.CSS_SELECTOR, ".plot-chart-loading")
            if loading:
                checks.append(Check("ui-plot-render", "FAIL", "chart still loading after refresh", product_bug=True))
            else:
                checks.append(Check("ui-plot-render", "FAIL", "no Plotly/svg/canvas in chart panel", product_bug=True))
    except NoSuchElementException as exc:
        checks.append(Check("ui-plot-render", "FAIL", str(exc)))

    screenshot(driver, shots, "plot_page")
    return checks


def test_modbus_page(driver: Any, shots: Path) -> list[Check]:
    checks: list[Check] = []
    body = driver.find_element(By.TAG_NAME, "body").text.lower()
    if "poll" in body or "modbus" in body:
        checks.append(Check("ui-modbus-page", "PASS", "modbus page content loaded"))
    else:
        checks.append(Check("ui-modbus-page", "FAIL", "modbus page appears empty"))
    screenshot(driver, shots, "modbus_page")
    return checks


def test_host_page(driver: Any, shots: Path, host_stats_api: dict[str, Any] | None) -> list[Check]:
    checks: list[Check] = []
    crash = tab_crash_message(driver, "host")
    if crash:
        checks.append(Check("ui-host-tab-crash", "FAIL", crash[:240], product_bug=True))
        screenshot(driver, shots, "host_page_crash")
        return checks
    checks.append(Check("ui-host-tab-crash", "PASS", "Host stats tab did not crash"))

    body = driver.find_element(By.TAG_NAME, "body").text
    if any(x in body for x in ("Host", "CPU", "Storage", "Ollama", "external agent")):
        checks.append(Check("ui-host-page", "PASS", "Host stats content visible"))
    else:
        checks.append(Check("ui-host-page", "FAIL", "Host stats page missing expected content", product_bug=True))

    ollama_in_api = isinstance(host_stats_api, dict) and host_stats_api.get("ollama") is not None
    if not ollama_in_api:
        if "external" in body.lower() and "agent" in body.lower():
            checks.append(
                Check(
                    "ui-host-ollama-optional",
                    "PASS",
                    "API omitted ollama; UI shows external-agents note (v3.2.6 FIX-13)",
                )
            )
        elif "Ollama" in body:
            checks.append(
                Check(
                    "ui-host-ollama-optional",
                    "PASS",
                    "Ollama section rendered without crash despite absent API field",
                )
            )
        else:
            checks.append(
                Check(
                    "ui-host-ollama-optional",
                    "PASS",
                    "no TabErrorBoundary crash when stats.ollama omitted from API",
                )
            )
    else:
        ollama = host_stats_api.get("ollama") if isinstance(host_stats_api, dict) else {}
        api_ok = ollama.get("api_ok") if isinstance(ollama, dict) else "?"
        checks.append(Check("ui-host-ollama-present", "PASS", f"API ollama.api_ok={api_ok}"))

    screenshot(driver, shots, "host_page")
    return checks


def test_home_faults(driver: Any, shots: Path) -> list[Check]:
    checks: list[Check] = []
    driver.get(driver.current_url.split("#")[0].rsplit("/", 1)[0] + "/")
    time.sleep(2)
    body = driver.find_element(By.TAG_NAME, "body").text
    if "fault" in body.lower() or "validation" in body.lower() or "building" in body.lower():
        checks.append(Check("ui-home-dashboard", "PASS", "home/building dashboard rendered"))
    else:
        checks.append(Check("ui-home-dashboard", "FAIL", "home dashboard missing expected content"))
    screenshot(driver, shots, "home_dashboard")
    return checks


def run_ui_validation(out_dir: Path, use_form_login: bool = False) -> RunResult:
    root = bench_root()
    cfg = bench_config(root)
    api_base = cfg["bridge"]
    base = ui_base_url(api_base)
    result = RunResult(artifact_dir=str(out_dir), started_at=utc_now(), meta={"phase": "selenium_ui", "base": base, "api_base": api_base})
    shots = out_dir / "screenshots"
    out_dir.mkdir(parents=True, exist_ok=True)

    if webdriver is None:
        result.add(Check("selenium-import", "FAIL", str(_IMPORT_ERR)))
        result.finalize()
        result.write(out_dir)
        return result

    user, pw = resolve_password(root, "integrator")
    from openfdd_test_lib import OpenFddClient

    client = OpenFddClient.login(api_base, user, pw)
    driver = None
    try:
        driver = create_driver(base)
        if use_form_login or os.environ.get("OPENFDD_UI_FORM_LOGIN", "0") == "1":
            login_form(driver, base, user, pw)
            result.add(Check("ui-login-form", "PASS", "login form E2E succeeded"))
        else:
            inject_token(driver, base, client.token)
            result.add(Check("ui-login-token", "PASS", "sessionStorage JWT injected"))

        for route, label in ROUTES:
            result.add(test_route_load(driver, base, route, label, shots))

        driver.get(f"{base.rstrip('/')}/model")
        time.sleep(1.5)
        for c in test_model_page(driver, shots):
            result.add(c)

        driver.get(f"{base.rstrip('/')}/sql-fdd")
        time.sleep(1.5)
        for c in test_sql_page(driver, shots):
            result.add(c)

        _, host_stats_raw = client.get("/api/host/stats")
        host_stats_api = host_stats_raw if isinstance(host_stats_raw, dict) else {}
        (out_dir / "host_stats_browser_context.json").write_text(
            json.dumps(host_stats_api, indent=2),
            encoding="utf-8",
        )

        driver.get(f"{base.rstrip('/')}/host")
        time.sleep(1.5)
        for c in test_host_page(driver, shots, host_stats_api):
            result.add(c)

        driver.get(f"{base.rstrip('/')}/plot")
        time.sleep(1.5)
        for c in test_plot_page(driver, shots):
            result.add(c)

        driver.get(f"{base.rstrip('/')}/modbus")
        time.sleep(1.5)
        for c in test_modbus_page(driver, shots):
            result.add(c)

        for c in test_home_faults(driver, shots):
            result.add(c)

        # Network sanity: faults API from browser context
        faults = driver.execute_async_script(
            """
            const cb = arguments[arguments.length - 1];
            const tok = sessionStorage.getItem('ofdd_token');
            fetch('/api/faults/status', {headers: {Authorization: 'Bearer ' + tok}})
              .then(r => r.json()).then(j => cb(j)).catch(e => cb({error: String(e)}));
            """
        )
        (out_dir / "faults_status_browser.json").write_text(json.dumps(faults, indent=2), encoding="utf-8")
        if isinstance(faults, dict) and faults.get("ok", True):
            result.add(Check("ui-faults-api", "PASS", f"faults/status ok active={faults.get('active_fault_count', faults.get('count', '?'))}"))
        else:
            result.add(Check("ui-faults-api", "FAIL", str(faults.get("error") if isinstance(faults, dict) else faults)))

    except Exception as exc:
        screenshot(driver, shots, "fatal_error") if driver else None
        result.add(Check("selenium-fatal", "FAIL", str(exc)))
    finally:
        if driver:
            driver.quit()

    result.finalize()
    result.write(out_dir)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Open-FDD Selenium UI validation")
    parser.add_argument("--out", default=os.environ.get("OPENFDD_FRONTEND_ARTIFACT_DIR", ""))
    parser.add_argument("--form-login", action="store_true")
    args = parser.parse_args()
    out = Path(args.out) if args.out else bench_root() / "workspace/logs/frontend_ui_latest"
    log(f"selenium ui → {out}")
    result = run_ui_validation(out, use_form_login=args.form_login)
    log(f"done pass={result.pass_count} fail={result.fail_count} skip={result.skip_count}")
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
