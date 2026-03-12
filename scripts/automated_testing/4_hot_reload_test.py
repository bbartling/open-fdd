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
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
RULES_DIR = SCRIPT_DIR / "rules"

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
    except Exception:
        body = {}
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


def _test_one_yaml(api_url: str, path: Path, test_filename: str, fault_id: str) -> str | None:
    """Upload, verify list/get/sync/definitions, delete. Returns None on success, else error message."""
    content = path.read_text(encoding="utf-8")
    content = _content_with_unique_name_flag(content, fault_id)

    code, _ = _request(api_url, "POST", "/rules", json_body={"filename": test_filename, "content": content})
    if code not in (200, 201):
        return f"POST /rules -> {code}"

    code, data = _request(api_url, "GET", "/rules")
    if code != 200 or test_filename not in (data.get("files") or []):
        return "GET /rules: file not in list"

    code, body_text = _get_text(api_url, f"/rules/{test_filename}")
    if code != 200 or fault_id not in body_text:
        return "GET /rules/{filename}: bad or missing content"

    code, _ = _request(api_url, "POST", "/rules/sync-definitions", json_body=None)
    if code != 200:
        return f"POST /rules/sync-definitions -> {code}"

    code, defs = _request(api_url, "GET", "/faults/definitions")
    if code != 200:
        return f"GET /faults/definitions -> {code}"
    ids = {d.get("fault_id") for d in (defs if isinstance(defs, list) else []) if d.get("fault_id")}
    if fault_id not in ids:
        return "fault_id not in definitions after sync"

    code, _ = _request(api_url, "DELETE", f"/rules/{test_filename}")
    if code not in (200, 204):
        return f"DELETE /rules/{test_filename} -> {code}"

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
        i += 1

    if not api_url:
        api_url = os.environ.get("BASE_URL", "http://localhost:8000").rstrip("/")
        print(f"Using API URL: {api_url} (set --api-url or BASE_URL to override)")
    else:
        print(f"API URL: {api_url}")

    if not RULES_DIR.is_dir():
        print(f"Rules dir missing: {RULES_DIR}", file=sys.stderr)
        return 1

    failed = 0
    suffix = str(int(__import__("time").time()))
    for name in YAML_FILES_TO_TEST:
        path = RULES_DIR / name
        if not path.is_file():
            print(f"  {name}: skip (not found)")
            continue
        test_filename = f"test_{path.stem}_{suffix}.yaml"
        fault_id = f"test_{path.stem}_{suffix}"
        err = _test_one_yaml(api_url, path, test_filename, fault_id)
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
