#!/usr/bin/env python3
"""
Rules API test: upload a few YAML rule files via the frontend API, verify server accepts and parses.

Loads each of a small set of .yaml files from scripts/automated_testing/rules/ and:

  Backend:
    - POST /rules with {filename, content} (same API the React Faults page uses).
    - GET /rules — file appears in list.
    - GET /rules/{filename} — server returns stored content.
    - POST /rules/sync-definitions — sync rules_dir → fault_definitions.
    - GET /faults/definitions — fault_id from the rule appears.
    - DELETE /rules/{filename} — cleanup.

  Frontend (when --frontend-url): open /faults and assert page loads (optional parity check).

Usage:
  python 4_hot_reload_test.py --api-url http://localhost:8000
  python 4_hot_reload_test.py --api-url http://localhost:8000 --frontend-url http://localhost --frontend-check

Requires: httpx. For --frontend-check: selenium, webdriver-manager.
"""

from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent.parent
RULES_DIR = REPO_ROOT / "stack" / "rules"

# Small fixed set of rule files to test (must have name and flag in YAML)
YAML_FILES_TO_TEST = ["sensor_flatline.yaml", "sensor_bounds.yaml"]


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
    except Exception as e:
        raw = (r.text or "")[:500]
        body = {
            "_json_error": str(e),
            "_raw_preview": raw,
            "_status_code": r.status_code,
        }
    return r.status_code, body


def _get_text(api_url: str, path: str) -> tuple[int, str]:
    try:
        import httpx
    except ImportError:
        return 0, ""
    url = f"{api_url.rstrip('/')}{path}"
    headers = {}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"
    r = httpx.get(url, headers=headers or None, timeout=30.0)
    return r.status_code, r.text or ""


def _content_with_unique_name_flag(content: str, unique_flag: str) -> str:
    """Set name and flag to unique_flag so fault_definitions has a distinct fault_id."""
    out = re.sub(r"^name:\s*\S+", f"name: {unique_flag}", content, count=1, flags=re.MULTILINE)
    out = re.sub(r"^flag:\s*\S+", f"flag: {unique_flag}", out, count=1, flags=re.MULTILINE)
    return out


def _delete_rule_file(api_url: str, filename: str) -> str | None:
    code, _ = _request(api_url, "DELETE", f"/rules/{filename}")
    if code not in (200, 204):
        return f"DELETE /rules/{filename} -> {code}"
    return None


def _resolve_site_identifier(api_url: str, site_hint: str | None) -> str | None:
    code, body = _request(api_url, "GET", "/sites")
    if code != 200 or not isinstance(body, list) or not body:
        return None
    if site_hint:
        target = site_hint.strip().lower()
        for row in body:
            if not isinstance(row, dict):
                continue
            rid = str(row.get("id", "")).lower()
            rname = str(row.get("name", "")).lower()
            rdesc = str(row.get("description", "")).lower()
            if target in {rid, rname, rdesc}:
                return str(row.get("id"))
    return str(body[0].get("id"))


def _start_fdd_job(api_url: str) -> tuple[bool, str | None, str | None]:
    code, body = _request(api_url, "POST", "/jobs/fdd/run", json_body={})
    if code != 200 or not isinstance(body, dict):
        return False, None, f"POST /jobs/fdd/run -> {code}"
    job_id = body.get("job_id")
    if not job_id:
        return False, None, "POST /jobs/fdd/run missing job_id"
    return True, str(job_id), None


def _wait_for_job_completion(api_url: str, job_id: str, timeout_sec: int = 300) -> tuple[bool, str | None]:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        code, body = _request(api_url, "GET", f"/jobs/{job_id}")
        if code == 200 and isinstance(body, dict):
            status = str(body.get("status", "")).lower()
            if status == "finished":
                return True, None
            if status == "failed":
                err = body.get("error")
                return False, f"FDD job failed: {err}" if err else "FDD job failed"
        time.sleep(5)
    return False, "Timed out waiting for FDD job to finish"


def _fault_present(api_url: str, fault_id: str, site_id: str | None) -> tuple[bool, bool, str | None]:
    params = {"site_id": site_id} if site_id else {}
    qs = urlencode({k: v for k, v in params.items() if v})
    path = "/faults/state"
    if qs:
        path = f"{path}?{qs}"
    code, body = _request(api_url, "GET", path)
    if code != 200 or not isinstance(body, list):
        return False, False, f"GET /faults/state -> {code}"
    return True, any(str(row.get("fault_id")) == fault_id for row in body if isinstance(row, dict)), None


def _run_fdd_and_wait_for_fault(api_url: str, fault_id: str, site_id: str | None) -> tuple[bool, str | None]:
    ok, job_id, err = _start_fdd_job(api_url)
    if not ok or not job_id:
        return False, err
    job_ok, job_err = _wait_for_job_completion(api_url, job_id)
    if not job_ok:
        return False, job_err
    deadline = time.time() + 240
    while time.time() < deadline:
        ok_state, present, state_err = _fault_present(api_url, fault_id, site_id)
        if not ok_state:
            return False, state_err
        if present:
            return True, None
        time.sleep(5)
    return False, f"Fault {fault_id} not observed after FDD run"


def _test_one_yaml(
    api_url: str,
    path: Path,
    test_filename: str,
    fault_id: str,
    verify_faults: bool,
    site_id: str | None,
) -> str | None:
    """Upload, verify list/get/sync/definitions, delete. Returns None on success, else error message."""
    content = path.read_text(encoding="utf-8")
    content = _content_with_unique_name_flag(content, fault_id)
    created = False

    def cleanup_with_message(message: str | None) -> str | None:
        if not created:
            return message
        cleanup_err = _delete_rule_file(api_url, test_filename)
        if cleanup_err:
            if message:
                return f"{message}; {cleanup_err}"
            return cleanup_err
        return message

    code, _ = _request(api_url, "POST", "/rules", json_body={"filename": test_filename, "content": content})
    if code not in (200, 201):
        return f"POST /rules -> {code}"
    created = True

    code, data = _request(api_url, "GET", "/rules")
    if code != 200 or test_filename not in (data.get("files") or []):
        return cleanup_with_message("GET /rules: file not in list")

    code, body_text = _get_text(api_url, f"/rules/{test_filename}")
    if code != 200 or fault_id not in body_text:
        return cleanup_with_message("GET /rules/{filename}: bad or missing content")

    code, _ = _request(api_url, "POST", "/rules/sync-definitions", json_body=None)
    if code != 200:
        return cleanup_with_message(f"POST /rules/sync-definitions -> {code}")

    code, defs = _request(api_url, "GET", "/faults/definitions")
    if code != 200:
        return cleanup_with_message(f"GET /faults/definitions -> {code}")
    ids = {d.get("fault_id") for d in (defs if isinstance(defs, list) else []) if d.get("fault_id")}
    if fault_id not in ids:
        return cleanup_with_message("fault_id not in definitions after sync")

    if verify_faults:
        ok_verify, verify_err = _run_fdd_and_wait_for_fault(api_url, fault_id, site_id)
        if not ok_verify:
            return cleanup_with_message(verify_err or "FDD run did not produce the expected fault")

    cleanup_err = _delete_rule_file(api_url, test_filename)
    if cleanup_err:
        return cleanup_err

    return None


def _run_frontend_check(frontend_url: str, headed: bool) -> str | None:
    """Open /faults and assert page loads. Returns None on success, else error message."""
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options as ChromeOptions
        from selenium.webdriver.chrome.service import Service as ChromeService
        from selenium.webdriver.support.ui import WebDriverWait
        from webdriver_manager.chrome import ChromeDriverManager
    except ImportError:
        return "pip install selenium webdriver-manager"
    base = frontend_url.rstrip("/")
    opts = ChromeOptions()
    if not headed:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    driver = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()), options=opts)
    try:
        driver.get(f"{base}/faults")
        WebDriverWait(driver, 15).until(
            lambda d: "Faults" in (d.page_source or "") or "fault" in (d.page_source or "").lower()[:3000]
        )
    except Exception as e:
        return str(e)
    finally:
        driver.quit()
    return None


def main() -> int:
    api_url = None
    frontend_url = None
    frontend_check = False
    headed = False
    verify_faults = True
    site_hint = None
    i = 0
    args = sys.argv[1:]
    while i < len(args):
        if args[i] == "--api-url" and i + 1 < len(args):
            api_url = (args[i + 1] or "").strip().rstrip("/")
            i += 2
            continue
        if args[i] == "--frontend-url" and i + 1 < len(args):
            frontend_url = (args[i + 1] or "").strip().rstrip("/")
            i += 2
            continue
        if args[i] == "--frontend-check":
            frontend_check = True
            i += 1
            continue
        if args[i] == "--headed":
            headed = True
            i += 1
            continue
        if args[i] == "--skip-fault-verification":
            verify_faults = False
            i += 1
            continue
        if args[i] == "--site" and i + 1 < len(args):
            site_hint = (args[i + 1] or "").strip()
            i += 2
            continue
        i += 1

    if not api_url:
        api_url = os.environ.get("BASE_URL", "http://localhost:8000").rstrip("/")
        print(f"Using API URL: {api_url} (set --api-url or BASE_URL to override)")
    else:
        print(f"API URL: {api_url}")

    site_id_for_faults = None
    if verify_faults:
        site_id_for_faults = _resolve_site_identifier(api_url, site_hint)
        if site_id_for_faults:
            print(f"Using site {site_id_for_faults} for FDD fault verification")
        else:
            print("Could not resolve a site for fault verification; skipping fault checks.")
            verify_faults = False

    if not RULES_DIR.is_dir():
        print(f"Rules dir missing: {RULES_DIR}", file=sys.stderr)
        return 1

    failed = 0
    suffix = str(int(time.time()))
    for name in YAML_FILES_TO_TEST:
        path = RULES_DIR / name
        if not path.is_file():
            print(f"  {name}: skip (not found)")
            continue
        test_filename = f"test_{path.stem}_{suffix}.yaml"
        fault_id = f"test_{path.stem}_{suffix}"
        err = _test_one_yaml(api_url, path, test_filename, fault_id, verify_faults, site_id_for_faults)
        if err:
            print(f"  {name}: FAIL — {err}")
            failed += 1
        else:
            print(f"  {name}: OK")

    if frontend_check and frontend_url:
        print(f"  Frontend ({frontend_url}/faults): ", end="")
        err = _run_frontend_check(frontend_url, headed)
        if err:
            print(f"FAIL — {err}")
            failed += 1
        else:
            print("OK")

    if failed:
        print(f"\n{failed} check(s) failed.")
        return 1
    print(f"\nAll rules API checks passed ({len(YAML_FILES_TO_TEST)} YAML(s)).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
