#!/usr/bin/env python3
"""
Hot-reload test: inject a new rule, trigger FDD run, verify fault definitions and (optional) frontend.

Requires the server to have OFDD_ALLOW_TEST_RULES=1 so POST/DELETE /rules/test-inject are enabled
(e.g. in stack/.env or container env). The test:

  1. GET /faults/definitions and GET /rules (baseline).
  2. POST /rules/test-inject with a new YAML rule (unique fault_id).
  3. POST /jobs/fdd/run, poll GET /jobs/{id} until finished (or timeout).
  4. GET /faults/definitions — assert the new fault_id appears (hot reload synced rules → DB).
  5. GET /rules — assert the new filename is in the files list.
  6. Optional (--frontend-url): open /faults and assert the new fault name appears.
  7. DELETE /rules/test-inject/{filename} to remove the test rule.

Modifying an existing rule (e.g. a tuning param) uses the same hot-reload path: the next FDD run
loads all YAML from disk and syncs to fault_definitions, so any edit under rules_dir is picked up
without restart. This test proves the "add new file" case; param edits work the same way.

Usage:

  # API-only (no browser)
  python 4_hot_reload_test.py --api-url http://192.168.204.16:8000

  # With frontend check (Selenium)
  python 4_hot_reload_test.py --api-url http://192.168.204.16:8000 --frontend-url http://192.168.204.16 --frontend-check --headed

  # Set API key if server requires auth
  set OFDD_API_KEY=your-key
  python 4_hot_reload_test.py --api-url http://192.168.204.16:8000
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent


def _load_env_file(path: str) -> None:
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip()
            if value.startswith('"') and value.endswith('"'):
                value = value[1:-1].replace('\\"', '"')
            elif value.startswith("'") and value.endswith("'"):
                value = value[1:-1].replace("\\'", "'")
            if key and os.environ.get(key) is None:
                os.environ[key] = value


def _load_stack_env() -> None:
    _load_env_file(str(REPO_ROOT / "stack" / ".env"))
    _load_env_file(os.path.join(os.getcwd(), ".env"))
    _load_env_file(str(SCRIPT_DIR / ".env"))


_load_stack_env()

API_KEY = os.environ.get("OFDD_API_KEY", "").strip()
JOB_POLL_INTERVAL = 2.0
JOB_TIMEOUT = 90.0


def _request(api_url: str, method: str, path: str, json_body: dict | None = None) -> tuple[int, dict | list]:
    try:
        import httpx
    except ImportError:
        print("pip install httpx", file=sys.stderr)
        sys.exit(1)
    url = f"{api_url.rstrip('/')}{path}"
    headers = {}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"
    r = httpx.request(method, url, json=json_body, headers=headers or None, timeout=30.0)
    try:
        body = r.json()
    except Exception:
        body = {}
    return r.status_code, body


def _main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Hot-reload test: inject rule, trigger FDD, verify definitions and optional frontend")
    parser.add_argument("--api-url", required=True, help="API base URL (e.g. http://192.168.204.16:8000)")
    parser.add_argument("--frontend-url", default=None, help="Frontend URL for optional /faults check")
    parser.add_argument("--frontend-check", action="store_true", help="Open Faults page and assert new fault appears")
    parser.add_argument("--headed", action="store_true", help="Run browser headed (with --frontend-check)")
    parser.add_argument("--skip-cleanup", action="store_true", help="Do not delete the injected rule file")
    args = parser.parse_args()
    api_url = args.api_url.rstrip("/")

    suffix = str(int(time.time()))
    test_filename = f"test_hot_reload_{suffix}.yaml"
    test_fault_id = f"test_hot_reload_{suffix}"
    test_rule_yaml = f"""# Injected by 4_hot_reload_test.py (hot-reload test)
name: test_hot_reload_{suffix}
description: "Test rule for hot-reload verification"
type: expression
flag: {test_fault_id}

inputs:
  Dummy_Sensor:
    brick: Dummy_Sensor

params:
  threshold: 1.0

expression: |
  1 == 0
"""

    print("Hot-reload test: inject rule -> FDD run -> verify definitions (and optional frontend)")
    print(f"  API: {api_url}")
    print(f"  Test rule: {test_filename} (fault_id={test_fault_id})")

    # 1) Baseline
    code, defs = _request(api_url, "GET", "/faults/definitions")
    if code != 200:
        print(f"  FAIL: GET /faults/definitions -> {code}")
        return 1
    definitions = defs if isinstance(defs, list) else []
    fault_ids_before = {d.get("fault_id") for d in definitions if d.get("fault_id")}
    if test_fault_id in fault_ids_before:
        print(f"  FAIL: fault_id {test_fault_id} already present (leftover from previous run?)")
        return 1

    code, rules_data = _request(api_url, "GET", "/rules")
    if code != 200:
        print(f"  FAIL: GET /rules -> {code}")
        return 1
    files_before = set(rules_data.get("files", [])) if isinstance(rules_data, dict) else set()
    if test_filename in files_before:
        print(f"  FAIL: {test_filename} already in rules list")
        return 1
    print(f"  Baseline: {len(definitions)} definitions, {len(files_before)} rule files")

    # 2) Inject rule
    code, inject_res = _request(api_url, "POST", "/rules/test-inject", json_body={"filename": test_filename, "content": test_rule_yaml})
    if code == 403:
        print("  SKIP: Test inject disabled. Set OFDD_ALLOW_TEST_RULES=1 on the server and restart.")
        return 0
    if code != 200 and code != 201:
        print(f"  FAIL: POST /rules/test-inject -> {code} {inject_res}")
        return 1
    print(f"  Injected: {test_filename}")

    try:
        # 3) Trigger FDD run
        code, job_res = _request(api_url, "POST", "/jobs/fdd/run", json_body={})
        if code != 200:
            print(f"  FAIL: POST /jobs/fdd/run -> {code}")
            return 1
        job_id = job_res.get("job_id") if isinstance(job_res, dict) else None
        if not job_id:
            print("  FAIL: No job_id in response")
            return 1
        print(f"  FDD job: {job_id}")

        # 4) Poll until finished
        deadline = time.monotonic() + JOB_TIMEOUT
        while time.monotonic() < deadline:
            code, job = _request(api_url, "GET", f"/jobs/{job_id}")
            if code != 200:
                print(f"  FAIL: GET /jobs/{job_id} -> {code}")
                return 1
            status = job.get("status", "")
            if status == "finished":
                print(f"  FDD job finished: {job.get('result')}")
                break
            if status == "failed":
                print(f"  FAIL: FDD job failed: {job.get('error')}")
                return 1
            time.sleep(JOB_POLL_INTERVAL)
        else:
            print("  FAIL: FDD job timed out")
            return 1

        # 5) Verify fault definitions
        code, defs2 = _request(api_url, "GET", "/faults/definitions")
        if code != 200:
            print(f"  FAIL: GET /faults/definitions (after FDD) -> {code}")
            return 1
        definitions2 = defs2 if isinstance(defs2, list) else []
        fault_ids_after = {d.get("fault_id") for d in definitions2 if d.get("fault_id")}
        if test_fault_id not in fault_ids_after:
            print(f"  FAIL: fault_id {test_fault_id} not in definitions after FDD run (hot reload did not sync)")
            return 1
        print(f"  Definitions: {test_fault_id} present (hot reload OK)")

        # 6) Verify rules list
        code, rules_data2 = _request(api_url, "GET", "/rules")
        if code != 200:
            print(f"  FAIL: GET /rules (after inject) -> {code}")
            return 1
        files_after = set(rules_data2.get("files", [])) if isinstance(rules_data2, dict) else set()
        if test_filename not in files_after:
            print(f"  FAIL: {test_filename} not in GET /rules files list")
            return 1
        print(f"  Rules list: {test_filename} present")

        # 7) Optional frontend check
        if args.frontend_check and args.frontend_url:
            frontend_url = args.frontend_url.rstrip("/")
            print(f"  Frontend: checking {frontend_url}/faults for new fault...")
            try:
                from selenium import webdriver
                from selenium.webdriver.chrome.options import Options as ChromeOptions
                from selenium.webdriver.chrome.service import Service as ChromeService
                from selenium.webdriver.common.by import By
                from selenium.webdriver.support import expected_conditions as EC
                from selenium.webdriver.support.ui import WebDriverWait
                from webdriver_manager.chrome import ChromeDriverManager
            except ImportError:
                print("  SKIP: Frontend check requires selenium, webdriver-manager. pip install selenium webdriver-manager")
            else:
                opts = ChromeOptions()
                if not args.headed:
                    opts.add_argument("--headless=new")
                opts.add_argument("--no-sandbox")
                opts.add_argument("--disable-dev-shm-usage")
                driver = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()), options=opts)
                try:
                    driver.get(f"{frontend_url}/faults")
                    WebDriverWait(driver, 15).until(
                        lambda d: "Faults" in (d.page_source or "") or "fault" in (d.page_source or "").lower()[:3000]
                    )
                    time.sleep(1.0)
                    page = driver.page_source or ""
                    # Fault matrix or definitions table may show fault_id or name
                    if test_fault_id not in page and f"test_hot_reload_{suffix}" not in page:
                        print(f"  FAIL: New fault {test_fault_id} not visible on Faults page")
                        return 1
                    print("  Frontend: new fault visible on Faults page")
                finally:
                    driver.quit()

    finally:
        # 8) Cleanup
        if not args.skip_cleanup:
            code, _ = _request(api_url, "DELETE", f"/rules/test-inject/{test_filename}")
            if code in (200, 204):
                print(f"  Cleanup: removed {test_filename}")
            else:
                print(f"  Cleanup: DELETE test-inject -> {code} (file may remain)")

    print("  Hot-reload test passed.")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
