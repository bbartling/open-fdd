#!/usr/bin/env python3
"""
SPARQL CRUD + frontend test.

Loads each .sparql file from scripts/automated_testing/sparql/ and runs it:

  Backend:
    - POST /data-model/sparql with body {"query": "<file contents>"} (raw SPARQL).
    - POST /data-model/sparql/upload with the first .sparql file (tests upload endpoint).

  Expected results (optional):
    - When config/data_model.ttl exists and rdflib is installed: expected bindings are
      computed by running each query against that TTL (source of truth for the graph).
    - Otherwise, when sparql/expected/<name>.json exists: expected bindings are loaded from JSON.
    - When no expected is available: we only assert API vs frontend parity.

  Frontend (when --frontend-parity):
    For each query we test both ways a human would use the Data Model Testing page:
    1) Upload .sparql file: use the UI "Upload .sparql file" button, then Run SPARQL; assert result.
    2) Type in form: put the same SPARQL into the textarea, click Run SPARQL; assert result.
    Both must match the API (and expected, when available). Uses route /data-model-testing
    (Summarize your HVAC + Custom SPARQL).

Asserts: API returns 200 and bindings; when expected is used, API and frontend match expected;
otherwise API and frontend match each other. When --frontend-parity is used, browser console
errors are collected and printed at the end.

Graph-DB sync (default on): Compares CRUD counts to SPARQL graph counts. GET /sites, /equipment,
/points (DB) vs 09_graph_db_sync_counts.sparql (graph). Sites and points must match; equipment
allows graph >= DB (synthetic equipment for orphan points). Use --skip-graph-db-sync to skip.

Usage:
  python 2_sparql_crud_and_frontend_test.py --api-url http://192.168.204.16:8000 --frontend-url http://192.168.204.16 --frontend-parity

  python sparql_crud_and_frontend_test.py --api-url http://localhost:8000 --generate-expected   # write sparql/expected/*.json from API
  python sparql_crud_and_frontend_test.py --api-url http://localhost:8000 --skip-graph-db-sync # skip graph vs DB count assertion

Requires: httpx. For --frontend-parity: selenium, webdriver-manager. For --expected-from-ttl: rdflib.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
SPARQL_DIR = SCRIPT_DIR / "sparql"
EXPECTED_DIR = SPARQL_DIR / "expected"
DATA_MODEL_TTL = REPO_ROOT / "config" / "data_model.ttl"


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
    repo_root = SCRIPT_DIR.parent.parent
    _load_env_file(str(repo_root / "stack" / ".env"))
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


def _run_graph_db_sync_check(api_url: str, skip: bool) -> int:
    """Assert SPARQL (graph) counts match CRUD (DB) counts. Returns number of failures (0 on success).
    GET /sites, /equipment, /points then run 09_graph_db_sync_counts.sparql.
    Sites and points must match. Equipment: graph >= DB (graph can have synthetic equipment for
    sites with orphan points — see data_model_ttl build_ttl_from_db)."""
    if skip:
        return 0
    sync_sparql = (SPARQL_DIR / "09_graph_db_sync_counts.sparql")
    if not sync_sparql.is_file():
        print("  Graph-DB sync: skip (09_graph_db_sync_counts.sparql not found)")
        return 0
    query = sync_sparql.read_text(encoding="utf-8").strip()
    query = "\n".join([l for l in query.splitlines() if not l.strip().startswith("#")]).strip()
    if not query:
        return 0

    # CRUD counts from DB
    code_sites, body_sites = _request(api_url, "GET", "/sites")
    code_equip, body_equip = _request(api_url, "GET", "/equipment")
    code_pts, body_pts = _request(api_url, "GET", "/points?limit=10000")
    if code_sites != 200 or code_equip != 200 or code_pts != 200:
        print("  Graph-DB sync: skip (CRUD endpoints not reachable or auth required)")
        return 0
    db_sites = len(body_sites) if isinstance(body_sites, list) else 0
    db_equipment = len(body_equip) if isinstance(body_equip, list) else 0
    db_points = len(body_pts) if isinstance(body_pts, list) else 0

    ok, bindings, err = _run_sparql_api(api_url, query)
    if not ok or not bindings:
        print(f"  Graph-DB sync: FAIL — SPARQL count query failed ({err or 'no bindings'})")
        return 1
    row = bindings[0]
    row_lower = {k.lower(): v for k, v in row.items()}
    try:
        graph_sites = int(str(row_lower.get("site_count", "") or 0))
        graph_equipment = int(str(row_lower.get("equipment_count", "") or 0))
        graph_points = int(str(row_lower.get("point_count", "") or 0))
    except (TypeError, ValueError):
        print("  Graph-DB sync: FAIL — SPARQL count row missing or non-numeric")
        return 1
    failed = 0
    if db_sites != graph_sites:
        print(f"  Graph-DB sync: FAIL — sites DB={db_sites} vs graph={graph_sites}")
        failed += 1
    if graph_equipment < db_equipment:
        print(f"  Graph-DB sync: FAIL — equipment graph={graph_equipment} < DB={db_equipment}")
        failed += 1
    if db_points != graph_points:
        print(f"  Graph-DB sync: FAIL — points DB={db_points} vs graph={graph_points}")
        failed += 1
    if failed == 0:
        eq_note = f"equipment={db_equipment}" if graph_equipment == db_equipment else f"equipment={db_equipment}(DB) graph={graph_equipment}(+synthetic)"
        print(f"  Graph-DB sync: OK (sites={db_sites}, {eq_note}, points={db_points})")
    return failed


def _run_sparql_api(api_url: str, query: str) -> tuple[bool, list[dict], str]:
    code, body = _request(api_url, "POST", "/data-model/sparql", json_body={"query": query})
    if code != 200:
        return False, [], f"POST /data-model/sparql -> {code}"
    if "bindings" not in body:
        return False, [], "Response missing bindings"
    bindings = body["bindings"]
    if not isinstance(bindings, list):
        return False, [], "bindings is not a list"
    return True, bindings, ""


def _run_sparql_upload_api(api_url: str, path: Path) -> tuple[bool, list[dict], str]:
    """POST /data-model/sparql/upload with a .sparql file (multipart). Returns (ok, bindings, error)."""
    try:
        import httpx
    except ImportError:
        return False, [], "httpx required"
    url = f"{api_url.rstrip('/')}/data-model/sparql/upload"
    headers = {}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"
    with path.open("rb") as f:
        files = {"file": (path.name, f, "text/plain")}
        r = httpx.post(url, files=files, headers=headers or None, timeout=30.0)
    if r.status_code != 200:
        return False, [], f"POST /data-model/sparql/upload -> {r.status_code}"
    try:
        body = r.json()
    except Exception:
        return False, [], "Invalid JSON from upload"
    if "bindings" not in body:
        return False, [], "Response missing bindings"
    bindings = body["bindings"]
    if not isinstance(bindings, list):
        return False, [], "bindings is not a list"
    return True, bindings, ""


def _normalize_row(row: dict, keys: set[str] | None = None) -> tuple[tuple[str, str], ...]:
    """Sort (var, value) for comparison. Values normalized to str or empty string for None.
    If keys is given, use only those (fill missing with ""); else use row.keys()."""
    key_set = keys or set(row.keys())
    return tuple(sorted((k, (row.get(k) if row.get(k) is not None else "")) for k in key_set))


def _get_expected_from_ttl(ttl_path: Path, query: str) -> list[dict] | None:
    """Run the SPARQL query against the TTL file and return bindings as list[dict], or None if unavailable."""
    if not ttl_path.is_file():
        return None
    try:
        from rdflib import Graph
    except ImportError:
        return None
    try:
        g = Graph()
        g.parse(ttl_path, format="turtle")
        result = g.query(query)
        vars_list = getattr(result, "vars", None)
        bindings = []
        for row in result:
            if vars_list is not None:
                row_dict = {
                    str(v).lstrip("?"): (str(row[v]) if row[v] is not None else "")
                    for v in vars_list
                }
            else:
                row_dict = {str(k).lstrip("?"): (str(v) if v is not None else "") for k, v in row.items()}
            bindings.append(row_dict)
        return bindings
    except Exception:
        return None


def _load_expected_json(expected_path: Path) -> list[dict] | None:
    """Load expected bindings from a JSON file (list of dicts). Returns None if file missing or invalid."""
    if not expected_path.is_file():
        return None
    try:
        import json
        raw = json.loads(expected_path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            return None
        return [dict(r) for r in raw]
    except Exception:
        return None


def _assert_bindings_match(
    expected: list[dict],
    actual: list[dict],
    label: str,
) -> bool:
    """Return True if actual bindings match expected (same columns and row set); else print and return False."""
    exp_keys = set().union(*(r.keys() for r in expected)) if expected else set()
    act_keys = set().union(*(r.keys() for r in actual)) if actual else set()
    exp_keys_lower = {k.lower() for k in exp_keys}
    act_keys_lower = {k.lower() for k in act_keys}
    if exp_keys_lower != act_keys_lower:
        if expected and actual:
            print(f"         {label}: column mismatch — expected {sorted(exp_keys)} vs actual {sorted(act_keys)}")
        return False
    if len(expected) != len(actual):
        print(f"         {label}: row count mismatch — expected {len(expected)} vs actual {len(actual)}")
        return False
    canonical = exp_keys_lower | act_keys_lower
    exp_set = {_normalize_row(r, canonical) for r in expected}
    act_set = {_normalize_row(r, canonical) for r in actual}
    if exp_set != act_set:
        print(f"         {label}: bindings differ (set comparison)")
        return False
    return True


def _run_sparql_via_frontend(driver, frontend_url: str, query: str, timeout_sec: float = 15) -> tuple[bool, list[dict], str]:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait

    base = frontend_url.rstrip("/")
    driver.get(f"{base}/data-model-testing")
    wait = WebDriverWait(driver, timeout_sec)

    textarea = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "[data-testid=sparql-query-textarea]")))
    # React controlled input: use native value setter + input event so state updates (see e.g. React #10135).
    driver.execute_script(
        """
        var el = arguments[0];
        var v = arguments[1];
        var nativeInputValueSetter = Object.getOwnPropertyDescriptor(
            window.HTMLTextAreaElement.prototype, 'value'
        ).set;
        nativeInputValueSetter.call(el, v);
        el.dispatchEvent(new Event('input', { bubbles: true }));
        """
        ,
        textarea,
        query,
    )
    # Wait for textarea to show our query (React may re-render and set from state).
    wait.until(lambda d: d.find_element(By.CSS_SELECTOR, "[data-testid=sparql-query-textarea]").get_attribute("value") == query)
    time.sleep(0.5)  # Let React commit state before click so Run SPARQL sends this query

    btn = driver.find_element(By.CSS_SELECTOR, "[data-testid=sparql-run-button]")
    btn.click()

    # Wait for either results table or "No bindings"
    try:
        wait.until(
            lambda d: (
                d.find_elements(By.CSS_SELECTOR, "[data-testid=sparql-results-table] tbody tr")
                or "No bindings" in (d.page_source or "")
            )
        )
    except Exception as e:
        return False, [], f"Frontend wait: {e}"

    table = driver.find_elements(By.CSS_SELECTOR, "[data-testid=sparql-results-table]")
    if not table:
        return True, [], ""

    rows = driver.find_elements(By.CSS_SELECTOR, "[data-testid=sparql-results-table] tbody tr")
    raw_headers = [th.text.strip() for th in driver.find_elements(By.CSS_SELECTOR, "[data-testid=sparql-results-table] thead th")]
    if not raw_headers:
        return False, [], "No table headers"
    # Frontend may show headers in uppercase (e.g. CSS text-transform); normalize to lowercase to match API.
    headers = [h.lower() for h in raw_headers]
    bindings = []
    for tr in rows:
        cells = tr.find_elements(By.TAG_NAME, "td")
        if len(cells) != len(headers):
            continue
        row = {headers[i]: (cells[i].text.strip() or "").replace("—", "") for i in range(len(headers))}
        bindings.append(row)
    return True, bindings, ""


def _run_sparql_via_frontend_file(
    driver, frontend_url: str, path: Path, timeout_sec: float = 15
) -> tuple[bool, list[dict], str]:
    """Run SPARQL on the frontend by uploading the .sparql file via the UI (like a human would)."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait

    base = frontend_url.rstrip("/")
    driver.get(f"{base}/data-model-testing")
    wait = WebDriverWait(driver, timeout_sec)

    file_input = wait.until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "[data-testid=sparql-file-input]"))
    )
    # Send absolute path so the browser can read the file (must be path the runner can access).
    file_input.send_keys(str(path.resolve()))
    # FileReader is async; wait for textarea to contain file content (e.g. PREFIX or SELECT).
    expected_start = path.read_text(encoding="utf-8").strip()[:80]
    try:
        wait.until(
            lambda d: expected_start in (d.find_element(By.CSS_SELECTOR, "[data-testid=sparql-query-textarea]").get_attribute("value") or "")
        )
    except Exception as e:
        return False, [], f"Frontend file upload wait: {e}"
    time.sleep(0.3)

    btn = driver.find_element(By.CSS_SELECTOR, "[data-testid=sparql-run-button]")
    btn.click()

    try:
        wait.until(
            lambda d: (
                d.find_elements(By.CSS_SELECTOR, "[data-testid=sparql-results-table] tbody tr")
                or "No bindings" in (d.page_source or "")
            )
        )
    except Exception as e:
        return False, [], f"Frontend (file) wait: {e}"

    table = driver.find_elements(By.CSS_SELECTOR, "[data-testid=sparql-results-table]")
    if not table:
        return True, [], ""

    rows = driver.find_elements(By.CSS_SELECTOR, "[data-testid=sparql-results-table] tbody tr")
    raw_headers = [th.text.strip() for th in driver.find_elements(By.CSS_SELECTOR, "[data-testid=sparql-results-table] thead th")]
    if not raw_headers:
        return False, [], "No table headers"
    headers = [h.lower() for h in raw_headers]
    bindings = []
    for tr in rows:
        cells = tr.find_elements(By.TAG_NAME, "td")
        if len(cells) != len(headers):
            continue
        row = {headers[i]: (cells[i].text.strip() or "").replace("—", "") for i in range(len(headers))}
        bindings.append(row)
    return True, bindings, ""


def _get_console_errors(driver) -> list[dict]:
    """Get browser console log entries that are errors or warnings (SEVERE/WARNING)."""
    try:
        logs = driver.get_log("browser")
    except Exception:
        return []
    out = []
    for e in logs:
        level = (e.get("level") or "").upper()
        msg = e.get("message") or ""
        if "favicon.ico" in msg and "404" in msg:
            continue
        if level == "SEVERE" or (level == "WARNING" and ("error" in msg.lower() or "400" in msg or "500" in msg)):
            out.append({"level": level, "message": msg})
    return out


def _parse_args():
    api_url = None
    frontend_url = None
    frontend_parity = False
    headed = False
    print_results = False
    expected_from_ttl = False
    generate_expected = False
    skip_graph_db_sync = False
    args = list(sys.argv[1:])
    i = 0
    while i < len(args):
        if args[i] == "--api-url" and i + 1 < len(args):
            api_url = (args[i + 1] or "").strip().rstrip("/")
            i += 2
            continue
        if args[i] == "--frontend-url" and i + 1 < len(args):
            frontend_url = (args[i + 1] or "").strip().rstrip("/")
            i += 2
            continue
        if args[i] == "--frontend-parity":
            frontend_parity = True
            i += 1
            continue
        if args[i] == "--headed":
            headed = True
            i += 1
            continue
        if args[i] in ("--print-results", "-p"):
            print_results = True
            i += 1
            continue
        if args[i] == "--expected-from-ttl":
            expected_from_ttl = True
            i += 1
            continue
        if args[i] == "--generate-expected":
            generate_expected = True
            i += 1
            continue
        if args[i] == "--skip-graph-db-sync":
            skip_graph_db_sync = True
            i += 1
            continue
        i += 1
    return api_url, frontend_url, frontend_parity, headed, print_results, expected_from_ttl, generate_expected, skip_graph_db_sync


def main() -> int:
    api_url, frontend_url, frontend_parity, headed, print_results, expected_from_ttl, generate_expected, skip_graph_db_sync = _parse_args()
    if not api_url:
        api_url = os.environ.get("BASE_URL", "http://localhost:8000").rstrip("/")
        print(f"Using API URL: {api_url} (set --api-url or BASE_URL to override)")
    else:
        print(f"API URL: {api_url}")

    if not SPARQL_DIR.is_dir():
        print(f"SPARQL dir missing: {SPARQL_DIR}", file=sys.stderr)
        return 1

    sparql_files = sorted(SPARQL_DIR.glob("*.sparql"))
    if not sparql_files:
        print(f"No .sparql files in {SPARQL_DIR}", file=sys.stderr)
        return 1

    if generate_expected:
        EXPECTED_DIR.mkdir(parents=True, exist_ok=True)
        print(f"Expected results: generating into {EXPECTED_DIR} from API")

    use_ttl_expected = expected_from_ttl or (DATA_MODEL_TTL.is_file() and not generate_expected)
    if expected_from_ttl and not DATA_MODEL_TTL.is_file():
        print(f"Expected from TTL requested but {DATA_MODEL_TTL} not found.", file=sys.stderr)
        return 1

    failed = 0
    # Backend: test POST /data-model/sparql/upload with first .sparql file (same result as raw POST).
    first_path = sparql_files[0]
    first_query = first_path.read_text(encoding="utf-8").strip()
    first_query = "\n".join([l for l in first_query.splitlines() if not l.strip().startswith("#")]).strip()
    if first_query:
        ok_up, bindings_up, err_up = _run_sparql_upload_api(api_url, first_path)
        ok_raw, bindings_raw, _ = _run_sparql_api(api_url, first_query)
        if not ok_up:
            print(f"  Upload endpoint FAIL — {err_up}")
            failed += 1
        elif not ok_raw:
            print(f"  Upload endpoint: raw POST failed")
            failed += 1
        else:
            keys_up = {k.lower() for k in set().union(*(r.keys() for r in bindings_up))}
            keys_raw = {k.lower() for k in set().union(*(r.keys() for r in bindings_raw))}
            canonical = keys_up | keys_raw
            up_set = {_normalize_row(r, canonical) for r in bindings_up}
            raw_set = {_normalize_row(r, canonical) for r in bindings_raw}
            if up_set == raw_set and len(bindings_up) == len(bindings_raw):
                print(f"  Upload endpoint (POST /data-model/sparql/upload): OK — {first_path.name}")
            else:
                print(f"  Upload endpoint: bindings differ from POST /data-model/sparql")
                failed += 1

    # Graph vs DB sync: assert GET /sites, /equipment, /points counts match SPARQL (09_graph_db_sync_counts.sparql)
    failed += _run_graph_db_sync_check(api_url, skip=skip_graph_db_sync)

    driver = None
    if frontend_parity and frontend_url:
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options as ChromeOptions
            from selenium.webdriver.chrome.service import Service as ChromeService
            from webdriver_manager.chrome import ChromeDriverManager
        except ImportError:
            print("For --frontend-parity install: pip install -r requirements-e2e.txt", file=sys.stderr)
            return 1
        opts = ChromeOptions()
        if not headed:
            opts.add_argument("--headless=new")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        driver = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()), options=opts)
        print(f"Frontend: {frontend_url} (parity check enabled)")

    # Collect browser console errors per query when --frontend-parity is used
    console_errors: list[tuple[str, list[dict]]] = []
    for path in sparql_files:
        name = path.name
        query = path.read_text(encoding="utf-8").strip()
        # Strip leading comment-only lines (files start with # Recipe ...)
        lines = [l for l in query.splitlines() if not l.strip().startswith("#")]
        query = "\n".join(lines).strip()
        if not query:
            print(f"  {name}: skip (no query after stripping comments)")
            continue

        # Resolve expected: from TTL (config/data_model.ttl), or from sparql/expected/<stem>.json
        expected = None
        if use_ttl_expected:
            expected = _get_expected_from_ttl(DATA_MODEL_TTL, query)
            if expected_from_ttl and expected is None:
                print(f"  {name}: expected-from-ttl FAIL — could not run query against {DATA_MODEL_TTL} (install rdflib?)")
                failed += 1
                continue
        if expected is None and EXPECTED_DIR.is_dir():
            expected = _load_expected_json(EXPECTED_DIR / f"{path.stem}.json")
        reference = expected  # for assertions; when None we use api_bindings as reference

        ok, api_bindings, err = _run_sparql_api(api_url, query)
        if not ok:
            print(f"  {name}: API FAIL — {err}")
            failed += 1
            continue

        if generate_expected:
            import json
            out_path = EXPECTED_DIR / f"{path.stem}.json"
            out_path.write_text(json.dumps(api_bindings, indent=2), encoding="utf-8")
            print(f"  {name}: API OK — {len(api_bindings)} row(s) → wrote {out_path.name}")
            if frontend_parity and frontend_url and driver:
                ok_f_file, fe_bindings_file, err_f_file = _run_sparql_via_frontend_file(driver, frontend_url, path)
                if not ok_f_file:
                    print(f"         Frontend (file upload) FAIL — {err_f_file}")
                    failed += 1
                elif not _assert_bindings_match(api_bindings, fe_bindings_file, "Frontend (file upload)"):
                    failed += 1
                else:
                    print(f"         Frontend (file upload) OK")
                ok_f, fe_bindings, err_f = _run_sparql_via_frontend(driver, frontend_url, query)
                if not ok_f:
                    print(f"         Frontend (textarea) FAIL — {err_f}")
                    failed += 1
                elif not _assert_bindings_match(api_bindings, fe_bindings, "Frontend (textarea)"):
                    failed += 1
                else:
                    print(f"         Frontend (textarea) OK")
            if driver and (frontend_parity and frontend_url):
                errs = _get_console_errors(driver)
                if errs:
                    console_errors.append((name, errs))
            continue

        print(f"  {name}: API OK — {len(api_bindings)} row(s)")
        if print_results and api_bindings:
            import json
            print(json.dumps(api_bindings, indent=2))
        elif print_results and not api_bindings:
            print("    (empty result)")

        if reference is not None:
            if not _assert_bindings_match(reference, api_bindings, "API vs expected"):
                failed += 1
                continue
            print(f"         API matches expected (data_model.ttl)" if use_ttl_expected else f"         API matches expected ({path.stem}.json)")

        if frontend_parity and frontend_url and driver:
            ref = reference if reference is not None else api_bindings
            # 1) Via file upload (like a human uploading a .sparql file)
            ok_f_file, fe_bindings_file, err_f_file = _run_sparql_via_frontend_file(
                driver, frontend_url, path
            )
            if not ok_f_file:
                print(f"         Frontend (file upload) FAIL — {err_f_file}")
                failed += 1
                continue
            if not _assert_bindings_match(ref, fe_bindings_file, "Frontend (file upload)"):
                failed += 1
                continue
            print(f"         Frontend (file upload) OK")

            # 2) Via textarea (like a human typing/pasting SPARQL into the form)
            ok_f, fe_bindings, err_f = _run_sparql_via_frontend(driver, frontend_url, query)
            if not ok_f:
                print(f"         Frontend (textarea) FAIL — {err_f}")
                failed += 1
                continue
            if not _assert_bindings_match(ref, fe_bindings, "Frontend (textarea)"):
                failed += 1
                continue
            print(f"         Frontend (textarea) OK")
        if driver and (frontend_parity and frontend_url):
            errs = _get_console_errors(driver)
            if errs:
                console_errors.append((name, errs))

    if driver:
        driver.quit()

    if console_errors:
        print("\nBrowser console errors (SEVERE / API errors in console):")
        for name, errs in console_errors:
            for e in errs:
                print(f"  [{name}] {e.get('level', '?')}: {e.get('message', '')[:200]}")
        if not failed:
            print("(SPARQL results matched; consider fixing the above so the UI stays clean.)")

    if failed:
        print(f"\n{failed} query/queries failed.")
        return 1
    print(f"\nAll {len(sparql_files)} SPARQL queries passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
