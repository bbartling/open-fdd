#!/usr/bin/env python3
"""
SPARQL CRUD + frontend test.

Paths are resolved from this script's directory (``SCRIPT_DIR``): ``sparql/*.sparql``,
``sparql/expected/*.json``, and repo ``config/data_model.ttl`` for TTL-expected mode.

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
    Requires a current frontend build: Data Model Testing exposes ``data-testid=sparql-finished-generation``
    so Selenium waits for each SPARQL mutation to finish (React Query keeps the previous table visible
    while a new query runs; scraping too early caused false parity failures).

    For each query we test both ways a human would use the Data Model Testing page:
    1) Upload .sparql file: use the UI "Upload .sparql file" button, then Run SPARQL; assert result.
    2) Type in form: put the same SPARQL into the textarea, click Run SPARQL; assert result.
    Both must match the API (and expected, when available). Uses route /data-model-testing
    (Summarize your HVAC + Custom SPARQL).

    Parity uses a **fresh POST /data-model/sparql** immediately after scraping the results table,
    not the first API call at the start of the query iteration. On a live edge, BACnet/weather
    scrapers and graph sync change triple/orphan counts between httpx and the browser; comparing
    the UI to that first snapshot false-fails ``07_count_triples`` / ``23_orphan_external_references``.

Asserts: API returns 200 and bindings; when expected is used, API and frontend match expected;
otherwise API and frontend match each other. When --frontend-parity is used, browser console
errors are collected and printed at the end.

Graph-DB sync (default on): Compares CRUD counts to SPARQL graph counts. GET /sites, /equipment,
/points (DB) vs 09_graph_db_sync_counts.sparql (graph). Sites and points must match; equipment
allows graph >= DB (synthetic equipment for orphan points). Use --skip-graph-db-sync to skip.

Environment (optional):
  BASE_URL — default API base if ``--api-url`` is omitted (default http://localhost:8000).
  OFDD_API_KEY — sent as ``Authorization: Bearer …`` on API requests if set. Wrong key → 403;
  missing header when the server requires a key → 401. HTTP 4xx lines include the API ``error.message``
  when present (e.g. ``SPARQL error: …``, ``Invalid TTL: …``).

CLI flags (machine-friendly):
  --api-url URL          Backend base URL (no trailing slash required).
  --frontend-url URL     Origin for Selenium (e.g. http://host); required with --frontend-parity.
  --frontend-parity      Run each query via UI (file upload + textarea) and match API/expected.
  --headed               Show browser (default headless for Chrome).
  --print-results, -p    After each query, print API bindings JSON.
  --expected-from-ttl    Require expected from config/data_model.ttl (fail if TTL query fails).
  --generate-expected    Write sparql/expected/<stem>.json from API; still runs frontend if given.
  --skip-graph-db-sync   Skip GET vs SPARQL count check.
  --print-hvac-summary   Print AHU/VAV counts and BACnet point rows (extra SPARQL).
  --show-bacnet-addresses  Same as --print-hvac-summary (AHU/VAV points with device + object id).
  --http-timeout SEC     Per-request timeout for httpx (default 120). Use on slow/large graphs.
  --no-predefined-buttons Skip the Data Model Testing **Summarize your HVAC** button suite (15×2 with/without BACnet refs).
  --predefined-buttons-only  Only backend smoke (upload/sync/BACnet) + predefined-button parity; skip per-file .sparql loop.
  --save-report [PATH]   Write JSON report (flags, predefined-button rows, HVAC/BACnet summary). Default file in this script dir: sparql_crud_report_<UTC>.json. Summary is always fetched for the report; use --show-bacnet-addresses to also print it.

  Predefined buttons: after each click, the script reads the **textarea** (same SPARQL the UI ran, including
  ``equipmentPointsWithBacnet(...)`` expansion) and compares the results table to a fresh POST /data-model/sparql.
  Short labels are read from ``frontend/.../data-model-testing-queries.ts`` when the repo is present; otherwise
  a built-in list is used (update TS when Brick classes change).

Exit: 0 if all checks pass, 1 if any failed (API, parity, sync, BACnet check, HVAC summary, etc.).

Usage (from **repo root**; forward slashes work on Windows too):

    python scripts/automated_testing/2_sparql_crud_and_frontend_test.py \\
      --api-url http://localhost:8000 \\
      --frontend-url http://localhost \\
      --frontend-parity \\
      --save-report

  PowerShell line continuation uses backtick (`` ` ``) instead of ``\\``.

Requires: httpx. For --frontend-parity: selenium, webdriver-manager. For --expected-from-ttl: rdflib.

Note vs ``1_e2e_frontend_selenium.py``: the E2E script drives the **browser**; API calls use the frontend’s
configured base URL and (when set) the same key as ``VITE_OFDD_API_KEY``, and may go through Caddy with
``X-Caddy-Auth``. This script calls **:8000** directly with **httpx** and ``OFDD_API_KEY`` only—same secret,
different path. **HTTP 400** from ``/data-model/sparql`` is never “wrong Bearer”; it is **Invalid TTL** or
**SPARQL error** from the server (the printed line includes the API message when using a current copy of
this file).

Windows: ``stack/.env`` is found via ``__file__`` → repo ``open-fdd/stack/.env``. Copied-only scripts
(e.g. under OneDrive without the full tree) must set ``OFDD_API_KEY`` (PowerShell: ``$env:OFDD_API_KEY = '…'``).
Env files are read as UTF-8 with BOM stripped (``utf-8-sig``). Use ``curl.exe`` or ``Invoke-RestMethod`` for
manual API checks—PowerShell’s ``curl`` alias is not curl.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
_log = logging.getLogger(__name__)
REPO_ROOT = SCRIPT_DIR.parent.parent.parent
SPARQL_DIR = SCRIPT_DIR.parent / "sparql"
EXPECTED_DIR = SPARQL_DIR / "expected"
DATA_MODEL_TTL = REPO_ROOT / "config" / "data_model.ttl"
# Predefined SPARQL buttons on Data Model Testing — keep in sync with:
#   frontend/src/data/data-model-testing-queries.ts
FRONTEND_PREDEFINED_QUERIES_TS = (
    REPO_ROOT / "frontend" / "src" / "data" / "data-model-testing-queries.ts"
)
_FALLBACK_PREDEFINED_SHORT_LABELS: tuple[str, ...] = (
    "Sites",
    "AHUs",
    "Zones",
    "Building",
    "VAV boxes",
    "VAVs per AHU",
    "Feed topology",
    "Chillers",
    "Cooling towers",
    "Boilers",
    "Central plant",
    "HVAC equipment",
    "Meters",
    "Points",
    "Class summary",
)
BRICK_SCHEMA_NS = "https://brickschema.org/schema/Brick#"


def _load_env_file(path: str) -> None:
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8-sig") as f:
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
    repo_root = SCRIPT_DIR.parent.parent.parent
    candidate_envs = [
        repo_root / "stack" / ".env",
        Path(os.getcwd()) / ".env",
        SCRIPT_DIR / ".env",
    ]
    extra = os.environ.get("OPENCLAW_STACK_ENV", "").strip()
    if extra:
        candidate_envs.append(Path(extra))
    home_stack = Path.home() / ".openclaw" / "workspace" / "open-fdd" / "stack" / ".env"
    candidate_envs.append(home_stack)
    for env_path in candidate_envs:
        _load_env_file(str(env_path))


_load_stack_env()

API_KEY = os.environ.get("OFDD_API_KEY", "").strip()

# Mutable container so main() can set timeout without `global` (SPARQL on large graphs can exceed 30s).
_HTTP_TIMEOUT_SEC: dict[str, float] = {"sec": 120.0}


def _format_api_error(body: dict | list | None, fallback_text: str = "") -> str:
    """Extract human message from Open-FDD JSON error body or raw text."""
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):
            msg = err.get("message")
            if msg:
                return str(msg)
        detail = body.get("detail")
        if detail is not None:
            return str(detail)
    t = (fallback_text or "").strip()
    if len(t) > 800:
        t = t[:800] + "…"
    return t


def _request(
    api_url: str, method: str, path: str, json_body: dict | None = None
) -> tuple[int, dict | list, str]:
    """HTTP request to API. Returns (status_code, json_body, error_message).

    - On network/timeout errors: status is 0 and error_message explains the transport failure.
    - On HTTP 4xx/5xx with a body: error_message is the API ``error.message`` (or raw snippet).
    - On HTTP 2xx: error_message is \"\".
    """
    try:
        import httpx
    except ImportError:
        print("pip install httpx", file=sys.stderr)
        sys.exit(1)
    url = f"{api_url.rstrip('/')}{path}"
    headers = {}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"
    try:
        r = httpx.request(
            method,
            url,
            json=json_body,
            headers=headers or None,
            timeout=_HTTP_TIMEOUT_SEC["sec"],
            # Avoid Windows proxy/env SSL quirks and long hangs loading CA store (e.g. Python 3.14).
            trust_env=False,
        )
    except httpx.RequestError as e:
        return 0, {}, f"{type(e).__name__}: {e}"
    try:
        body = r.json()
    except Exception:
        body = {}
    if r.status_code >= 400:
        raw = r.text or ""
        detail = _format_api_error(body if isinstance(body, dict) else {}, raw)
        if not detail.strip():
            detail = raw.strip()[:600]
        return r.status_code, body, detail or f"HTTP {r.status_code}"
    return r.status_code, body, ""


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
    query = sync_sparql.read_text(encoding="utf-8-sig").strip()
    query = "\n".join(
        [line for line in query.splitlines() if not line.strip().startswith("#")]
    ).strip()
    if not query:
        return 0

    # CRUD counts from DB
    code_sites, body_sites, err_sites = _request(api_url, "GET", "/sites")
    code_equip, body_equip, err_equip = _request(api_url, "GET", "/equipment")
    code_pts, body_pts, err_pts = _request(api_url, "GET", "/points?limit=10000")
    for label, code, err in (
        ("GET /sites", code_sites, err_sites),
        ("GET /equipment", code_equip, err_equip),
        ("GET /points", code_pts, err_pts),
    ):
        if code == 0:
            print(f"  Graph-DB sync: FAIL — {label}: {err}")
            return 1
        if code != 200:
            print(f"  Graph-DB sync: FAIL — {label} -> {code} — {err}")
            return 1
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
    code, body, req_err = _request(
        api_url, "POST", "/data-model/sparql", json_body={"query": query}
    )
    if code == 0:
        return False, [], req_err
    if code != 200:
        return False, [], f"POST /data-model/sparql -> {code} — {req_err}"
    if "bindings" not in body:
        return False, [], "Response missing bindings"
    bindings = body["bindings"]
    if not isinstance(bindings, list):
        return False, [], "bindings is not a list"
    return True, bindings, ""


def _api_bindings_fresh_after_ui(
    api_url: str, query: str, fallback: list[dict], context: str
) -> list[dict]:
    """Re-run the same SPARQL right after reading the UI table for parity (live graph may drift)."""
    ok, bindings, err = _run_sparql_api(api_url, query)
    if ok:
        return bindings
    print(f"         {context}: parity API re-fetch failed — {err} (using earlier API bindings)")
    return fallback


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
        try:
            r = httpx.post(
                url,
                files=files,
                headers=headers or None,
                timeout=_HTTP_TIMEOUT_SEC["sec"],
                trust_env=False,
            )
        except httpx.RequestError as e:
            return False, [], f"{type(e).__name__}: {e}"
    try:
        body = r.json()
    except Exception:
        body = {}
    if r.status_code != 200:
        detail = _format_api_error(body if isinstance(body, dict) else {}, r.text or "")
        return False, [], (
            f"POST /data-model/sparql/upload -> {r.status_code}"
            + (f" — {detail}" if detail else "")
        )
    if "bindings" not in body:
        return False, [], "Response missing bindings"
    bindings = body["bindings"]
    if not isinstance(bindings, list):
        return False, [], "bindings is not a list"
    return True, bindings, ""


def _row_get_ci(row: dict, key: str):
    """Return row[key] with case-insensitive key match (API vs UI header casing)."""
    if key in row:
        return row[key]
    kl = key.lower()
    for rk, rv in row.items():
        if rk.lower() == kl:
            return rv
    return None


def _normalize_cell_for_parity(s: str) -> str:
    """Align UI-formatted numbers with JSON (e.g. 150,709 → 150709). URIs/labels mostly unchanged."""
    t = (s or "").strip().replace("—", "")
    t = t.strip("<>")
    for ch in ("\u00a0", "\u202f", "\u2009", "\u2007"):
        t = t.replace(ch, "")
    # JSON may serialize large integers as scientific notation strings
    if re.search(r"[eE]", t):
        try:
            d = Decimal(t.replace(",", "").replace(" ", ""))
            if d == d.to_integral_value():
                return str(int(d))
        except (InvalidOperation, ValueError, ArithmeticError):
            pass
    collapsed = re.sub(r"[,\s]+", "", t)
    if collapsed.isdigit():
        return collapsed
    return t.strip()


def _normalize_row(row: dict, keys: set[str] | None = None) -> tuple[tuple[str, str], ...]:
    """Sort (var, value) for comparison. Values normalized to str or empty string for None.
    If keys is given, use only those (fill missing with ""); else use row.keys()."""
    key_set = keys or set(row.keys())
    return tuple(
        sorted(
            (
                k,
                (
                    _normalize_cell_for_parity(str(v))
                    if (v := _row_get_ci(row, k)) is not None
                    else ""
                ),
            )
            for k in key_set
        )
    )


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
        # Help debug stale-table / formatting issues (show up to 2 rows each side).
        only_exp = exp_set - act_set
        only_act = act_set - exp_set
        if only_exp:
            print(f"         {label}: only in API/reference (sample): {list(only_exp)[:2]}")
        if only_act:
            print(f"         {label}: only in frontend (sample): {list(only_act)[:2]}")
        return False
    return True


def _normalized_query_text(text: str) -> str:
    return (text or "").replace("\r\n", "\n").strip().lstrip("\ufeff")


def _ensure_data_model_testing_page(driver, frontend_url: str) -> None:
    base = frontend_url.rstrip("/")
    target = f"{base}/data-model-testing"
    current = (getattr(driver, "current_url", "") or "").rstrip("/")
    if not current.endswith("/data-model-testing"):
        driver.get(target)


def _sparql_finished_generation(driver) -> str:
    """Counter bumped in DataModelTestingPage on every SPARQL mutation settle (success or error)."""
    from selenium.webdriver.common.by import By
    from selenium.common.exceptions import NoSuchElementException

    try:
        el = driver.find_element(By.CSS_SELECTOR, "[data-testid=sparql-finished-generation]")
    except NoSuchElementException as e:
        raise RuntimeError(
            "Frontend is missing data-testid=sparql-finished-generation (rebuild/deploy "
            "open-fdd frontend so DataModelTestingPage includes the SPARQL E2E hook)."
        ) from e
    return (el.get_attribute("data-gen") or "0").strip()


def _wait_for_sparql_generation_increment(
    driver, timeout_sec: float, generation_before: str
) -> None:
    """Wait until React Query finishes the SPARQL call (avoids scraping a stale results table).

    We require **both** ``data-gen`` to change **and** the Run button to be enabled again.
    ``isPending`` keeps the previous success table visible; ``data-gen`` can bump in the same
    React tick as the new ``data``, but on slower clients (e.g. Windows + headed Chrome) waiting
    for the button avoids reading a stale table after file upload.
    """
    from selenium.webdriver.common.by import By
    from selenium.common.exceptions import TimeoutException

    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            cur = (
                driver.find_element(
                    By.CSS_SELECTOR, "[data-testid=sparql-finished-generation]"
                ).get_attribute("data-gen")
                or "0"
            ).strip()
            run_btn = driver.find_element(
                By.CSS_SELECTOR, "[data-testid=sparql-run-button]"
            )
            idle = run_btn.is_enabled()
        except Exception:
            time.sleep(0.03)
            continue
        if cur != generation_before and idle:
            time.sleep(0.22)
            return
        time.sleep(0.03)
    raise TimeoutException(
        f"SPARQL UI did not finish within {timeout_sec}s (generation still {generation_before!r})"
    )


def _sparql_ui_error_message(driver) -> str:
    from selenium.webdriver.common.by import By

    try:
        els = driver.find_elements(By.CSS_SELECTOR, "[data-testid=sparql-error]")
        if els:
            msg = (els[0].text or "").strip()
            if msg:
                return msg
    except Exception:
        _log.exception("could not read data-testid=sparql-error from DOM")
    return ""


def _read_sparql_results_bindings_from_dom(driver) -> tuple[bool, list[dict], str]:
    """Parse the results table in one execute_script call (avoids StaleElementReference on React re-render)."""
    script = """
    var table = document.querySelector('[data-testid=sparql-results-table]');
    if (!table) { return { ok: false, reason: 'no_table' }; }
    var heads = Array.from(table.querySelectorAll('thead th')).map(function(th) {
      return (th.innerText || th.textContent || '').trim();
    });
    var bodyRows = Array.from(table.querySelectorAll('tbody tr')).map(function(tr) {
      return Array.from(tr.querySelectorAll('td')).map(function(td) {
        return (td.innerText || td.textContent || '').trim();
      });
    });
    return { ok: true, headers: heads, rows: bodyRows };
    """
    try:
        data = driver.execute_script(script)
    except Exception as e:
        return False, [], f"DOM read failed: {e}"
    if not data:
        return False, [], "DOM read returned empty"
    if not data.get("ok"):
        if data.get("reason") == "no_table":
            return True, [], ""
        return False, [], f"Table read: {data.get('reason', 'unknown')}"
    raw_headers = data.get("headers") or []
    if not raw_headers:
        return False, [], "No table headers"
    headers = [h.lower() for h in raw_headers]
    bindings: list[dict] = []
    for cells in data.get("rows") or []:
        if len(cells) != len(headers):
            continue
        row = {
            headers[i]: _normalize_cell_for_parity(cells[i]) for i in range(len(headers))
        }
        bindings.append(row)
    return True, bindings, ""


def _run_sparql_via_frontend(driver, frontend_url: str, query: str, timeout_sec: float = 60) -> tuple[bool, list[dict], str]:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait

    _ensure_data_model_testing_page(driver, frontend_url)
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
    wait.until(
        lambda d: _normalized_query_text(
            d.find_element(By.CSS_SELECTOR, "[data-testid=sparql-query-textarea]").get_attribute("value")
        )
        == _normalized_query_text(query)
    )
    time.sleep(0.05)

    before = _sparql_finished_generation(driver)
    btn = driver.find_element(By.CSS_SELECTOR, "[data-testid=sparql-run-button]")
    btn.click()

    try:
        _wait_for_sparql_generation_increment(driver, timeout_sec, before)
    except Exception as e:
        return False, [], f"Frontend wait: {e}"

    err_ui = _sparql_ui_error_message(driver)
    if err_ui:
        return False, [], f"Frontend SPARQL error: {err_ui}"

    ok_read, bindings, err_read = _read_sparql_results_bindings_from_dom(driver)
    if not ok_read:
        return False, [], err_read
    return True, bindings, ""


def _run_sparql_via_frontend_file(
    driver, frontend_url: str, path: Path, timeout_sec: float = 60
) -> tuple[bool, list[dict], str]:
    """Run SPARQL on the frontend by uploading the .sparql file via the UI (like a human would)."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait

    _ensure_data_model_testing_page(driver, frontend_url)
    wait = WebDriverWait(driver, timeout_sec)

    file_input = wait.until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "[data-testid=sparql-file-input]"))
    )
    # Send absolute path so the browser can read the file (must be path the runner can access).
    file_input.send_keys(str(path.resolve()))
    # FileReader is async; wait for textarea to contain the full file content.
    expected_query = _normalized_query_text(path.read_text(encoding="utf-8-sig"))
    try:
        wait.until(
            lambda d: (
                _normalized_query_text(
                    d.find_element(By.CSS_SELECTOR, "[data-testid=sparql-query-textarea]").get_attribute("value")
                )
                == expected_query
            )
        )
    except Exception as e:
        return False, [], f"Frontend file upload wait: {e}"
    time.sleep(0.05)

    before = _sparql_finished_generation(driver)
    btn = driver.find_element(By.CSS_SELECTOR, "[data-testid=sparql-run-button]")
    btn.click()

    try:
        _wait_for_sparql_generation_increment(driver, timeout_sec, before)
    except Exception as e:
        return False, [], f"Frontend (file) wait: {e}"

    err_ui = _sparql_ui_error_message(driver)
    if err_ui:
        return False, [], f"Frontend SPARQL error: {err_ui}"

    ok_read, bindings, err_read = _read_sparql_results_bindings_from_dom(driver)
    if not ok_read:
        return False, [], err_read
    return True, bindings, ""


def _run_with_single_retry(run_fn, *args):
    ok, bindings, err = run_fn(*args)
    if ok:
        return ok, bindings, err
    # One retry smooths transient React/Selenium timing jitter on slower hosts.
    time.sleep(0.2)
    return run_fn(*args)


def _load_predefined_short_labels() -> list[str]:
    """Button labels in UI order — parsed from frontend TS when repo is available."""
    if FRONTEND_PREDEFINED_QUERIES_TS.is_file():
        text = FRONTEND_PREDEFINED_QUERIES_TS.read_text(encoding="utf-8")
        found = re.findall(r'shortLabel:\s*"([^"]+)"\s*,', text)
        if found:
            return found
    return list(_FALLBACK_PREDEFINED_SHORT_LABELS)


def _run_predefined_button_via_frontend(
    driver,
    frontend_url: str,
    button_text: str,
    *,
    include_bacnet_refs: bool = False,
    timeout_sec: float = 60,
    navigate: bool = True,
) -> tuple[bool, list[dict], str, str]:
    """Click one predefined HVAC button; return (ok, bindings, err, sparql_from_textarea).

    When ``navigate`` is False, assumes we are already on /data-model-testing and the BACnet
    checkbox is already in the desired state (full suite mode).
    """
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait

    wait = WebDriverWait(driver, timeout_sec)
    if navigate:
        base = frontend_url.rstrip("/")
        driver.get(f"{base}/data-model-testing")
        wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "[data-testid=sparql-query-textarea]"))
        )
        checkbox = wait.until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, "[data-testid=include-bacnet-refs-checkbox]")
            )
        )
        if checkbox.is_selected() != include_bacnet_refs:
            checkbox.click()
            time.sleep(0.12)

    btn = wait.until(
        EC.element_to_be_clickable((By.XPATH, f"//button[normalize-space()='{button_text}']"))
    )
    before = _sparql_finished_generation(driver)
    btn.click()

    try:
        _wait_for_sparql_generation_increment(driver, timeout_sec, before)
    except Exception as e:
        return False, [], f"Predefined button wait failed ({button_text}): {e}", ""

    err_ui = _sparql_ui_error_message(driver)
    if err_ui:
        return False, [], f"Frontend SPARQL error: {err_ui}", ""

    ok_read, bindings, err_read = _read_sparql_results_bindings_from_dom(driver)
    if not ok_read:
        return False, [], err_read, ""

    try:
        ta = driver.find_element(By.CSS_SELECTOR, "[data-testid=sparql-query-textarea]")
        q_used = _normalized_query_text(ta.get_attribute("value") or "")
    except Exception:
        q_used = ""
    return True, bindings, "", q_used


def _run_predefined_buttons_parity_suite(
    api_url: str,
    driver,
    frontend_url: str,
    *,
    print_results: bool,
    report_rows: list[dict] | None,
) -> int:
    """
    Exercise every Summarize-your-HVAC button with BACnet refs off, then on.
    Parity: UI table vs fresh API using the exact SPARQL read from the textarea after each click.
    """
    labels = _load_predefined_short_labels()
    if not labels:
        print("  Predefined buttons: skip (no short labels)")
        return 0

    failed = 0
    print(
        f"  Predefined buttons: {len(labels)} controls × 2 (BACnet refs off/on); "
        f"queries from UI textarea vs API (Brick NS {BRICK_SCHEMA_NS})"
    )

    for bacnet_refs in (False, True):
        mode = "BACnet refs off" if not bacnet_refs else "BACnet refs on"
        print(f"    --- {mode} ---")
        first = True
        for label in labels:
            ok, fe_bindings, err, q_used = _run_predefined_button_via_frontend(
                driver,
                frontend_url,
                label,
                include_bacnet_refs=bacnet_refs,
                navigate=first,
            )
            first = False
            row: dict = {
                "short_label": label,
                "bacnet_refs": bacnet_refs,
                "ok": ok,
                "error": err,
                "row_count": len(fe_bindings) if ok else 0,
                "query_preview": (q_used[:200] + "…") if len(q_used) > 200 else q_used,
            }
            if not ok:
                print(f"      [{label}] FAIL — {err}")
                failed += 1
                if report_rows is not None:
                    report_rows.append(row)
                continue

            if not q_used.strip():
                print(f"      [{label}] FAIL — empty textarea after predefined click")
                failed += 1
                row["error"] = "empty textarea"
                row["ok"] = False
                if report_rows is not None:
                    report_rows.append(row)
                continue

            ref_snap = _api_bindings_fresh_after_ui(
                api_url,
                q_used,
                fe_bindings,
                f"Predefined [{label}]",
            )
            parity_ok = _assert_bindings_match(
                ref_snap,
                fe_bindings,
                f"Predefined [{label}] UI vs API ({mode})",
            )
            row["parity_ok"] = parity_ok
            if not parity_ok:
                failed += 1
            else:
                extra = f" — {len(fe_bindings)} row(s)"
                if print_results and fe_bindings:
                    extra += f" | query: {q_used[:120]}…" if len(q_used) > 120 else f" | query: {q_used}"
                print(f"      [{label}] OK{extra}")

            if bacnet_refs and label == "AHUs" and ok and fe_bindings:
                keys = {k.lower() for r in fe_bindings for k in r.keys()}
                if "bacnet_device_id" not in keys or "object_identifier" not in keys:
                    print(
                        "      [AHUs + BACnet refs] FAIL — missing BACnet columns in table"
                    )
                    failed += 1
                    row["bacnet_columns_ok"] = False
                else:
                    row["bacnet_columns_ok"] = True
                values = " ".join(
                    str(v)
                    for r in fe_bindings
                    for v in r.values()
                    if v is not None
                )
                if "3456789" not in values:
                    print(
                        "      [AHUs + BACnet refs] FAIL — expected test device 3456789 in table"
                    )
                    failed += 1
                    row["bacnet_test_device_ok"] = False
                else:
                    row["bacnet_test_device_ok"] = True

            if report_rows is not None:
                report_rows.append(row)

    return failed


def _run_bacnet_address_backend_checks(api_url: str) -> int:
    """
    Validate graph exposes BACnet device addresses for algorithm/vendor workflows.
    Checks:
      1) 04_bacnet_devices.sparql returns rows
      2) Expected fake devices 3456789 + 3456790 are present
    """
    q_path = SPARQL_DIR / "04_bacnet_devices.sparql"
    if not q_path.is_file():
        print("  BACnet address check: skip (04_bacnet_devices.sparql missing)")
        return 0
    query = q_path.read_text(encoding="utf-8-sig").strip()
    query = "\n".join(
        [line for line in query.splitlines() if not line.strip().startswith("#")]
    ).strip()
    ok, bindings, err = _run_sparql_api(api_url, query)
    if not ok:
        print(f"  BACnet address check: FAIL — {err}")
        return 1
    if not bindings:
        print("  BACnet address check: FAIL — no BACnet devices in graph")
        return 1
    values = " ".join(
        str(v)
        for row in bindings
        for v in row.values()
        if v is not None
    )
    missing = [d for d in ("3456789", "3456790") if d not in values]
    if missing:
        print(
            "  BACnet address check: FAIL — expected test devices missing in graph:",
            ", ".join(missing),
        )
        return 1
    print("  BACnet address check: OK — found devices 3456789 and 3456790.")
    return 0


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
    print_hvac_summary = False
    http_timeout_sec = 120.0
    save_report_path: str | None = None
    no_predefined_buttons = False
    predefined_buttons_only = False
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
        if args[i] in ("--print-hvac-summary", "--show-bacnet-addresses"):
            print_hvac_summary = True
            i += 1
            continue
        if args[i] == "--http-timeout" and i + 1 < len(args):
            try:
                http_timeout_sec = float(args[i + 1])
            except ValueError:
                print(
                    f"Invalid --http-timeout value: {args[i + 1]!r} (expected seconds, e.g. 120)",
                    file=sys.stderr,
                )
                sys.exit(1)
            i += 2
            continue
        if args[i] == "--save-report":
            i += 1
            if i < len(args) and args[i] and not args[i].startswith("-"):
                save_report_path = args[i]
                i += 1
            else:
                save_report_path = ""
            continue
        if args[i] == "--no-predefined-buttons":
            no_predefined_buttons = True
            i += 1
            continue
        if args[i] == "--predefined-buttons-only":
            predefined_buttons_only = True
            i += 1
            continue
        i += 1
    return (
        api_url,
        frontend_url,
        frontend_parity,
        headed,
        print_results,
        expected_from_ttl,
        generate_expected,
        skip_graph_db_sync,
        print_hvac_summary,
        http_timeout_sec,
        save_report_path,
        no_predefined_buttons,
        predefined_buttons_only,
    )


def _hvac_summary_payload(api_url: str, *, echo: bool) -> tuple[int, dict | None]:
    """Run HVAC/BACnet summary queries; optionally print. Returns (failure_count, json-able dict)."""
    ahu_count_q = """
PREFIX brick: <https://brickschema.org/schema/Brick#>
SELECT (COUNT(?ahu) AS ?count) WHERE { ?ahu a brick:Air_Handling_Unit . }
""".strip()
    vav_count_q = """
PREFIX brick: <https://brickschema.org/schema/Brick#>
SELECT (COUNT(?vav) AS ?count) WHERE {
  { ?vav a brick:Variable_Air_Volume_Box . }
  UNION
  { ?vav a brick:Variable_Air_Volume_Box_With_Reheat . }
}
""".strip()
    ahu_points_q = """
PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX ofdd: <http://openfdd.local/ontology#>
SELECT ?equipment_label ?point_label ?bacnet_device_id ?object_identifier WHERE {
  ?equipment a brick:Air_Handling_Unit .
  OPTIONAL { ?equipment rdfs:label ?equipment_label . }
  ?point brick:isPointOf ?equipment .
  OPTIONAL { ?point rdfs:label ?point_label . }
  OPTIONAL { ?point ofdd:bacnetDeviceId ?bacnet_device_id . }
  OPTIONAL { ?point ofdd:objectIdentifier ?object_identifier . }
}
ORDER BY ?equipment_label ?point_label
""".strip()
    vav_points_q = """
PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX ofdd: <http://openfdd.local/ontology#>
SELECT ?equipment_label ?point_label ?bacnet_device_id ?object_identifier WHERE {
  { ?equipment a brick:Variable_Air_Volume_Box . }
  UNION
  { ?equipment a brick:Variable_Air_Volume_Box_With_Reheat . }
  OPTIONAL { ?equipment rdfs:label ?equipment_label . }
  ?point brick:isPointOf ?equipment .
  OPTIONAL { ?point rdfs:label ?point_label . }
  OPTIONAL { ?point ofdd:bacnetDeviceId ?bacnet_device_id . }
  OPTIONAL { ?point ofdd:objectIdentifier ?object_identifier . }
}
ORDER BY ?equipment_label ?point_label
""".strip()

    def _run(label: str, q: str) -> tuple[bool, list[dict]]:
        ok, bindings, err = _run_sparql_api(api_url, q)
        if not ok:
            if echo:
                print(f"  {label}: FAIL — {err}")
            return False, []
        return True, bindings

    if echo:
        print("\nHVAC/BACnet summary:")
    ok_ahu_c, ahu_c = _run("AHU count", ahu_count_q)
    ok_vav_c, vav_c = _run("VAV count", vav_count_q)
    ok_ahu_p, ahu_p = _run("AHU BACnet points", ahu_points_q)
    ok_vav_p, vav_p = _run("VAV BACnet points", vav_points_q)
    if not (ok_ahu_c and ok_vav_c and ok_ahu_p and ok_vav_p):
        return 1, None

    ahu_count = ahu_c[0].get("count", "0") if ahu_c else "0"
    vav_count = vav_c[0].get("count", "0") if vav_c else "0"
    if echo:
        print(f"  AHUs in Brick model: {ahu_count}")
        print(f"  VAVs in Brick model: {vav_count}")
        print("  AHU BACnet addresses:")
        for r in ahu_p:
            print(
                f"    - eq={r.get('equipment_label','')} point={r.get('point_label','')} "
                f"device={r.get('bacnet_device_id','')} object={r.get('object_identifier','')}"
            )
        print("  VAV BACnet addresses:")
        for r in vav_p:
            print(
                f"    - eq={r.get('equipment_label','')} point={r.get('point_label','')} "
                f"device={r.get('bacnet_device_id','')} object={r.get('object_identifier','')}"
            )

    payload = {
        "ahu_count": ahu_count,
        "vav_count": vav_count,
        "ahu_bacnet_points": ahu_p,
        "vav_bacnet_points": vav_p,
        "brick_namespace": BRICK_SCHEMA_NS,
    }
    return 0, payload


def _append_sparql_file_report(
    report_data: dict | None,
    path: Path,
    name: str,
    rec_status: str,
    rec_err: str | None,
    rec_rows: int | None,
    t0: float,
) -> None:
    """Append one row to report_data['sparql_file_results'] (no-op if report disabled)."""
    if report_data is None:
        return
    report_data["sparql_file_results"].append(
        {
            "file": str(path),
            "name": name,
            "status": rec_status,
            "error": rec_err,
            "row_count": rec_rows,
            "elapsed_sec": round(time.perf_counter() - t0, 4),
        }
    )


def main() -> int:
    (
        api_url,
        frontend_url,
        frontend_parity,
        headed,
        print_results,
        expected_from_ttl,
        generate_expected,
        skip_graph_db_sync,
        print_hvac_summary,
        http_timeout_sec,
        save_report_path,
        no_predefined_buttons,
        predefined_buttons_only,
    ) = _parse_args()
    if http_timeout_sec <= 0:
        print("--http-timeout must be positive", file=sys.stderr)
        return 1
    if predefined_buttons_only and generate_expected:
        print(
            "--predefined-buttons-only cannot be combined with --generate-expected",
            file=sys.stderr,
        )
        return 1
    if predefined_buttons_only and (not frontend_parity or not frontend_url):
        print(
            "--predefined-buttons-only requires --frontend-parity and --frontend-url",
            file=sys.stderr,
        )
        return 1
    if frontend_parity and not frontend_url:
        print("--frontend-parity requires --frontend-url", file=sys.stderr)
        return 1
    _HTTP_TIMEOUT_SEC["sec"] = http_timeout_sec
    if not api_url:
        api_url = os.environ.get("BASE_URL", "http://localhost:8000").rstrip("/")
        print(f"Using API URL: {api_url} (set --api-url or BASE_URL to override)")
    else:
        print(f"API URL: {api_url}")
    print(f"HTTP timeout: {_HTTP_TIMEOUT_SEC['sec']}s (override with --http-timeout)")

    if predefined_buttons_only:
        sparql_files: list[Path] = []
    elif not SPARQL_DIR.is_dir():
        print(f"SPARQL dir missing: {SPARQL_DIR}", file=sys.stderr)
        return 1
    else:
        sparql_files = sorted(SPARQL_DIR.glob("*.sparql"))
        if not sparql_files:
            print(f"No .sparql files in {SPARQL_DIR}", file=sys.stderr)
            return 1

    report_data: dict | None = None
    if save_report_path is not None:
        report_data = {
            "schema": "open-fdd-sparql-test-report-v1",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "argv": sys.argv,
            "api_url": api_url,
            "frontend_url": frontend_url,
            "brick_queries_source": str(FRONTEND_PREDEFINED_QUERIES_TS)
            if FRONTEND_PREDEFINED_QUERIES_TS.is_file()
            else None,
            "brick_namespace": BRICK_SCHEMA_NS,
            "flags": {
                "headed": headed,
                "print_results": print_results,
                "print_hvac_summary": print_hvac_summary,
                "frontend_parity": frontend_parity,
                "predefined_buttons_only": predefined_buttons_only,
                "no_predefined_buttons": no_predefined_buttons,
            },
            "sparql_file_results": [],
            "predefined_button_results": [],
            "hvac_summary": None,
        }

    if generate_expected:
        EXPECTED_DIR.mkdir(parents=True, exist_ok=True)
        print(f"Expected results: generating into {EXPECTED_DIR} from API")

    use_ttl_expected = expected_from_ttl or (DATA_MODEL_TTL.is_file() and not generate_expected)
    if expected_from_ttl and not DATA_MODEL_TTL.is_file():
        print(f"Expected from TTL requested but {DATA_MODEL_TTL} not found.", file=sys.stderr)
        return 1

    failed = 0
    # Backend: test POST /data-model/sparql/upload with first .sparql file (same result as raw POST).
    if sparql_files:
        first_path = sparql_files[0]
        first_query = first_path.read_text(encoding="utf-8-sig").strip()
        first_query = "\n".join(
            [
                line
                for line in first_query.splitlines()
                if not line.strip().startswith("#")
            ]
        ).strip()
        if first_query:
            ok_up, bindings_up, err_up = _run_sparql_upload_api(api_url, first_path)
            ok_raw, bindings_raw, _ = _run_sparql_api(api_url, first_query)
            if not ok_up:
                print(f"  Upload endpoint FAIL — {err_up}")
                failed += 1
            elif not ok_raw:
                print("  Upload endpoint: raw POST failed")
                failed += 1
            else:
                keys_up = {k.lower() for k in set().union(*(r.keys() for r in bindings_up))}
                keys_raw = {k.lower() for k in set().union(*(r.keys() for r in bindings_raw))}
                canonical = keys_up | keys_raw
                up_set = {_normalize_row(r, canonical) for r in bindings_up}
                raw_set = {_normalize_row(r, canonical) for r in bindings_raw}
                if up_set == raw_set and len(bindings_up) == len(bindings_raw):
                    print(
                        f"  Upload endpoint (POST /data-model/sparql/upload): OK — {first_path.name}"
                    )
                else:
                    print("  Upload endpoint: bindings differ from POST /data-model/sparql")
                    failed += 1

    # Graph vs DB sync: assert GET /sites, /equipment, /points counts match SPARQL (09_graph_db_sync_counts.sparql)
    failed += _run_graph_db_sync_check(api_url, skip=skip_graph_db_sync)
    # Dedicated BACnet-address visibility check for vendor/algorithm workflows.
    failed += _run_bacnet_address_backend_checks(api_url)
    if print_hvac_summary:
        hf, hv_pay = _hvac_summary_payload(api_url, echo=True)
        failed += hf
        if report_data is not None:
            report_data["hvac_summary"] = hv_pay
    elif report_data is not None:
        # Embed AHU/VAV + BACnet rows in JSON report without console spam.
        hf, hv_pay = _hvac_summary_payload(api_url, echo=False)
        failed += hf
        report_data["hvac_summary"] = hv_pay

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
        chrome_mode = "headed (visible)" if headed else "headless (no window — pass --headed to watch)"
        print(f"Frontend: {frontend_url} (parity + Selenium: {chrome_mode})")

    # Collect browser console errors per query when --frontend-parity is used
    console_errors: list[tuple[str, list[dict]]] = []
    for path in sparql_files:
        name = path.name
        t0 = time.perf_counter()
        rec_status = "skipped"
        rec_err: str | None = None
        rec_rows: int | None = None

        query = path.read_text(encoding="utf-8-sig").strip()
        # Strip leading comment-only lines (files start with # Recipe ...)
        lines = [line for line in query.splitlines() if not line.strip().startswith("#")]
        query = "\n".join(lines).strip()
        if not query:
            print(f"  {name}: skip (no query after stripping comments)")
            _append_sparql_file_report(
                report_data, path, name, rec_status, rec_err, rec_rows, t0
            )
            continue

        # Resolve expected: from TTL (config/data_model.ttl), or from sparql/expected/<stem>.json
        expected = None
        if use_ttl_expected:
            expected = _get_expected_from_ttl(DATA_MODEL_TTL, query)
            if expected_from_ttl and expected is None:
                print(f"  {name}: expected-from-ttl FAIL — could not run query against {DATA_MODEL_TTL} (install rdflib?)")
                failed += 1
                rec_status = "error"
                rec_err = f"expected-from-ttl: could not run query against {DATA_MODEL_TTL}"
                _append_sparql_file_report(
                    report_data, path, name, rec_status, rec_err, rec_rows, t0
                )
                continue
        if expected is None and EXPECTED_DIR.is_dir():
            expected = _load_expected_json(EXPECTED_DIR / f"{path.stem}.json")
        reference = expected  # for assertions; when None we use api_bindings as reference

        ok, api_bindings, err = _run_sparql_api(api_url, query)
        if not ok:
            print(f"  {name}: API FAIL — {err}")
            failed += 1
            rec_status = "api_error"
            rec_err = str(err) if err else "API request failed"
            _append_sparql_file_report(
                report_data, path, name, rec_status, rec_err, rec_rows, t0
            )
            continue

        rec_rows = len(api_bindings)
        rec_status = "success"

        if generate_expected:
            out_path = EXPECTED_DIR / f"{path.stem}.json"
            out_path.write_text(json.dumps(api_bindings, indent=2), encoding="utf-8")
            print(f"  {name}: API OK — {len(api_bindings)} row(s) → wrote {out_path.name}")
            if frontend_parity and frontend_url and driver:
                ok_f_file, fe_bindings_file, err_f_file = _run_with_single_retry(
                    _run_sparql_via_frontend_file, driver, frontend_url, path
                )
                if not ok_f_file:
                    print(f"         Frontend (file upload) FAIL — {err_f_file}")
                    failed += 1
                else:
                    ref_fe_file = _api_bindings_fresh_after_ui(
                        api_url, query, api_bindings, "Frontend (file upload)"
                    )
                    if not _assert_bindings_match(ref_fe_file, fe_bindings_file, "Frontend (file upload)"):
                        failed += 1
                        print("         (running textarea path anyway)")
                    else:
                        print("         Frontend (file upload) OK")
                ok_f, fe_bindings, err_f = _run_with_single_retry(
                    _run_sparql_via_frontend, driver, frontend_url, query
                )
                if not ok_f:
                    print(f"         Frontend (textarea) FAIL — {err_f}")
                    failed += 1
                else:
                    ref_fe_ta = _api_bindings_fresh_after_ui(
                        api_url, query, api_bindings, "Frontend (textarea)"
                    )
                    if not _assert_bindings_match(ref_fe_ta, fe_bindings, "Frontend (textarea)"):
                        failed += 1
                    else:
                        print("         Frontend (textarea) OK")
            if driver and (frontend_parity and frontend_url):
                errs = _get_console_errors(driver)
                if errs:
                    console_errors.append((name, errs))
            rec_status = "generated_expected"
            _append_sparql_file_report(
                report_data, path, name, rec_status, rec_err, rec_rows, t0
            )
            continue

        print(f"  {name}: API OK — {len(api_bindings)} row(s)")
        if print_results and api_bindings:
            print(json.dumps(api_bindings, indent=2))
        elif print_results and not api_bindings:
            print("    (empty result)")

        if reference is not None:
            if not _assert_bindings_match(reference, api_bindings, "API vs expected"):
                failed += 1
                rec_status = "expected_mismatch"
                rec_err = "API bindings differ from expected (TTL or JSON)"
                _append_sparql_file_report(
                    report_data, path, name, rec_status, rec_err, rec_rows, t0
                )
                continue
            print(f"         API matches expected (data_model.ttl)" if use_ttl_expected else f"         API matches expected ({path.stem}.json)")

        if frontend_parity and frontend_url and driver:
            ref = reference if reference is not None else api_bindings
            # 1) Via file upload (like a human uploading a .sparql file)
            ok_f_file, fe_bindings_file, err_f_file = _run_with_single_retry(
                _run_sparql_via_frontend_file, driver, frontend_url, path
            )
            if not ok_f_file:
                print(f"         Frontend (file upload) FAIL — {err_f_file}")
                failed += 1
                rec_status = "frontend_upload_error"
                rec_err = str(err_f_file) if err_f_file else "frontend file upload failed"
                _append_sparql_file_report(
                    report_data, path, name, rec_status, rec_err, rec_rows, t0
                )
                continue
            ref_fe_file = _api_bindings_fresh_after_ui(
                api_url, query, ref, "Frontend (file upload)"
            )
            if not _assert_bindings_match(ref_fe_file, fe_bindings_file, "Frontend (file upload)"):
                failed += 1
                print("         (running textarea path anyway)")
            else:
                print("         Frontend (file upload) OK")

            # 2) Via textarea (like a human typing/pasting SPARQL into the form)
            ok_f, fe_bindings, err_f = _run_with_single_retry(
                _run_sparql_via_frontend, driver, frontend_url, query
            )
            if not ok_f:
                print(f"         Frontend (textarea) FAIL — {err_f}")
                failed += 1
                rec_status = "frontend_textarea_error"
                rec_err = str(err_f) if err_f else "frontend textarea run failed"
                _append_sparql_file_report(
                    report_data, path, name, rec_status, rec_err, rec_rows, t0
                )
                continue
            ref_fe_ta = _api_bindings_fresh_after_ui(
                api_url, query, ref, "Frontend (textarea)"
            )
            if not _assert_bindings_match(ref_fe_ta, fe_bindings, "Frontend (textarea)"):
                failed += 1
                rec_status = "frontend_parity_mismatch"
                rec_err = "Frontend (textarea) bindings differ from API"
                _append_sparql_file_report(
                    report_data, path, name, rec_status, rec_err, rec_rows, t0
                )
                continue
            print("         Frontend (textarea) OK")
        if driver and (frontend_parity and frontend_url):
            errs = _get_console_errors(driver)
            if errs:
                console_errors.append((name, errs))
        _append_sparql_file_report(
            report_data, path, name, rec_status, rec_err, rec_rows, t0
        )

    if driver:
        if frontend_parity and frontend_url and not no_predefined_buttons:
            pre_rows = (
                report_data["predefined_button_results"]
                if report_data is not None
                else None
            )
            failed += _run_predefined_buttons_parity_suite(
                api_url,
                driver,
                frontend_url,
                print_results=print_results,
                report_rows=pre_rows,
            )
        driver.quit()

    if save_report_path is not None and report_data is not None:
        report_data["failed_total"] = failed
        if save_report_path == "":
            outp = (
                SCRIPT_DIR
                / f"sparql_crud_report_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
            )
        else:
            outp = Path(save_report_path)
            if not outp.is_absolute():
                outp = (SCRIPT_DIR / outp).resolve()
        outp.parent.mkdir(parents=True, exist_ok=True)
        outp.write_text(json.dumps(report_data, indent=2, default=str), encoding="utf-8")
        print(f"\nWrote JSON report: {outp}")

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
    bits: list[str] = []
    if sparql_files:
        bits.append(f"{len(sparql_files)} SPARQL file(s)")
    if frontend_parity and frontend_url and not no_predefined_buttons:
        bits.append("Summarize-your-HVAC predefined buttons (×2 BACnet modes)")
    print(f"\nPassed: {', '.join(bits) if bits else 'all checks'}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
