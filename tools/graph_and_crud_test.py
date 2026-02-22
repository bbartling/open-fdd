#!/usr/bin/env python3
# If run with bash, re-exec with Python (e.g. "bash tools/test_crud_api.py" still works)
""":'
exec python3 "$0" "$@"
"""

"""
End-to-end CRUD API test: hits Open-FDD API only (no direct calls to diy-bacnet-server).

All requests go to the Open-FDD API (--base-url). For BACnet, the test uses the API’s
gateway URL in request body (--bacnet-url; when base-url is localhost, default is host.docker.internal:8080 for container-to-host).
Flow: test → Open-FDD API → (API proxies to) diy-bacnet.

API coverage (OpenAPI paths exercised):
  - /health
  - /config: GET, PUT (platform config in RDF; same graph as Brick + BACnet)
  - /sites: list, create, get, patch, delete (demo-import deleted at [20c]; DemoSite deleted at [27] so only TestBenchSite remains)
  - /equipment: list, create, get, patch, delete
  - /points: list (by site, by equipment), create, get, patch, delete
  - /data-model: serialize, ttl, export, import (points + equipment feeds), sparql
  - /bacnet: server_hello, whois_range, point_discovery_to_graph
  - /download/csv (GET, POST), /download/faults (GET json, csv)
All SPARQL is via the Open-FDD CRUD API only: POST /data-model/sparql (see _sparql()). No direct triple-store or TTL file access.
Default API base is http://localhost:8000; use --base-url or BASE_URL for a remote host (e.g. http://192.168.204.16:8000).
Uses GET /data-model/check at [27] to assert TestBenchSite remains after deleting DemoSite (other sites e.g. BensOffice allowed). Not in this script: GET /bacnet/gateways, /data-model/reset, /data-model/sparql/upload, /analytics/*, /run-fdd/*.

This test uses pre-tagged import payloads (brick_type, rule_input, polling) that simulate the output of the
AI-assisted tagging step. The real workflow is: GET /data-model/export → LLM or human tags → PUT /data-model/import.
See docs/modeling/ai_assisted_tagging.md and AGENTS.md for the LLM prompt and export → tag → import flow.

Full LLM payload: Step [4f2] loads tools/demo_site_llm_payload.json (sites, equipments, relationships, points with
string IDs like site-1, ahu-1). The test maps those to API UUIDs and imports into DemoSite so many BACnet points
(two devices 3456789, 3456790) have polling=true. Idempotent: existing points are sent with point_id for update.

Usage:
# Default device 3456789
python tools/graph_and_crud_test.py

# Another device
python tools/graph_and_crud_test.py --bacnet-device-instance 3456788

# With BACnet URL and device
python tools/graph_and_crud_test.py --bacnet-url http://192.168.204.16:8080 --bacnet-device-instance 3456789

# Env override
BACNET_DEVICE_INSTANCE=999999 python tools/graph_and_crud_test.py

# Blast away all sites and re-run test (after test TestBenchSite remains; DemoSite deleted at [27])
./scripts/bootstrap.sh --reset-data && python tools/graph_and_crud_test.py
# Or API-only wipe (stack already up): python tools/delete_all_sites_and_reset.py && python tools/graph_and_crud_test.py
#
# Wait for 2 BACnet scrapes before exiting (requires scraper running and diy-bacnet reachable):
#   python tools/graph_and_crud_test.py --wait-scrapes 2 --scrape-interval-min 1
# Use --scrape-interval-min to match the scraper (Docker default 5; for 1 min set OFDD_BACNET_SCRAPE_INTERVAL_MIN=1
# in platform/.env and restart: cd platform && docker compose up -d).
#
# Reset and retry (full wipe + run test, then wait for scrapes):
#   ./scripts/bootstrap.sh --reset-data && python tools/graph_and_crud_test.py --wait-scrapes 2 --scrape-interval-min 1
"""

import argparse
import csv
import io
import json
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from uuid import UUID, uuid4

try:
    import httpx
except ImportError:
    import urllib.request
    import urllib.error

    httpx = None

# Set by main() from args (env overrides args)
BASE_URL = "http://localhost:8000"
BACNET_URL = ""
# When test hits API at localhost, API is often in Docker → from inside container use host to reach BACnet on host
BACNET_URL_FOR_API_DEFAULT = "http://host.docker.internal:8080"
BACNET_DEVICE_INSTANCE = 3456789  # default; override with --bacnet-device-instance
WAIT_SCRAPES = 0  # 0 = do not wait; 2+ = wait until this many BACnet scrapes seen before exit
SCRAPE_INTERVAL_MIN = 5  # used for wait timeout; Docker default is 5 (override in platform/docker-compose or .env)

# Testbench devices to discover and validate in graph/TTL (when BACnet enabled)
BACNET_TEST_DEVICE_INSTANCES = (3456789, 3456790)
# Testbench site + equipment — created/validated, not deleted; override with env TESTBENCH_SITE_NAME etc.
TESTBENCH_SITE_NAME = os.environ.get("TESTBENCH_SITE_NAME", "TestBenchSite")
TESTBENCH_AHU_NAME = os.environ.get("TESTBENCH_AHU_NAME", "TestBenchAhu")
TESTBENCH_VAV_NAME = os.environ.get("TESTBENCH_VAV_NAME", "TestBenchVav")
# DemoSite: full LLM payload (many BACnet points, two devices 3456789/3456790); see tools/demo_site_llm_payload.json
DEMO_SITE_LLM_NAME = "DemoSite"
DEMO_SITE_LLM_PAYLOAD_PATH = Path(__file__).resolve().parent / "demo_site_llm_payload.json"


def _wait_for_api_ready(max_wait_sec: float = 45.0, interval_sec: float = 2.0) -> None:
    """Wait for the API to accept requests (e.g. after bootstrap). Retries on connection errors."""
    url = f"{BASE_URL.rstrip('/')}/health"
    deadline = time.time() + max_wait_sec
    last_err = None
    first = True
    while time.time() < deadline:
        try:
            if httpx:
                with httpx.Client(timeout=5.0) as client:
                    r = client.get(url)
                if r.status_code == 200:
                    if not first:
                        print(f"    API ready at {BASE_URL}\n")
                    return
            else:
                req = urllib.request.Request(url, method="GET")
                with urllib.request.urlopen(req, timeout=5.0) as res:
                    if res.status == 200:
                        if not first:
                            print(f"    API ready at {BASE_URL}\n")
                        return
        except Exception as e:
            last_err = e
            if first:
                print(f"Waiting for API at {BASE_URL} (retrying every {interval_sec}s, max {max_wait_sec}s)...")
                first = False
        time.sleep(interval_sec)
    raise RuntimeError(
        f"API at {BASE_URL} not ready after {max_wait_sec}s (last error: {last_err}). "
        "If you just ran bootstrap, the API may still be starting; try again in a few seconds."
    ) from last_err


def _request(
    method: str, path: str, *, json_body: dict | None = None, timeout: float = 30.0
) -> tuple[int, dict | list | str | None]:
    """Send HTTP request, return (status_code, parsed_json or raw text for CSV)."""
    url = f"{BASE_URL.rstrip('/')}{path}"
    if httpx:
        with httpx.Client(timeout=timeout) as client:
            r = client.request(method, url, json=json_body)
            try:
                return r.status_code, r.json() if r.content else None
            except Exception:
                return r.status_code, r.text
    # Fallback: urllib
    req = urllib.request.Request(url, method=method)
    if json_body:
        req.add_header("Content-Type", "application/json")
        req.data = json.dumps(json_body).encode()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            body = res.read().decode("utf-8-sig")  # handle BOM in CSV responses
            if not body:
                return res.status, None
            try:
                return res.status, json.loads(body)
            except json.JSONDecodeError:
                return res.status, body
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            return e.code, json.loads(body) if body else None
        except Exception:
            return e.code, body
    except urllib.error.URLError as e:
        print(f"  ERROR: Cannot connect to {BASE_URL}: {e}")
        sys.exit(1)


def ok(code: int) -> bool:
    return 200 <= code < 300


def _sparql(query: str) -> list[dict]:
    """Run SPARQL against Open-FDD data model (DB + BACnet scan TTL when present). Return bindings."""
    code, data = _request("POST", "/data-model/sparql", json_body={"query": query})
    assert ok(code), f"SPARQL failed: {code} {data}"
    assert isinstance(data, dict) and "bindings" in data
    return data["bindings"]


def _sparql_site_labels() -> list[str]:
    q = """
    PREFIX brick: <https://brickschema.org/schema/Brick#>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    SELECT ?site_label WHERE { ?site a brick:Site . ?site rdfs:label ?site_label }
    """
    rows = _sparql(q)
    return [r.get("site_label") or "" for r in rows if r.get("site_label")]


def _sparql_point_labels() -> list[str]:
    q = """
    PREFIX brick: <https://brickschema.org/schema/Brick#>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    SELECT ?pt_label WHERE { ?pt brick:isPointOf ?eq . ?pt rdfs:label ?pt_label }
    """
    rows = _sparql(q)
    return [r.get("pt_label") or "" for r in rows if r.get("pt_label")]


def _sparql_point_labels_for_site(site_label: str) -> list[str]:
    """Point labels only for points under this site (Brick isPartOf). Excludes BACnet-only labels."""
    # Bind site label so we only get points from our test site (not BACnet graph)
    label_lit = json.dumps(site_label)
    q = f"""
    PREFIX brick: <https://brickschema.org/schema/Brick#>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    SELECT ?pt_label WHERE {{
      ?pt brick:isPointOf ?eq .
      ?eq brick:isPartOf ?site .
      ?site rdfs:label {label_lit} .
      ?pt rdfs:label ?pt_label .
    }}
    """
    rows = _sparql(q)
    return [r.get("pt_label") or "" for r in rows if r.get("pt_label")]


def _sparql_equipment_labels() -> list[str]:
    q = """
    PREFIX brick: <https://brickschema.org/schema/Brick#>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    SELECT ?eq_label WHERE { ?eq brick:isPartOf ?site . ?eq rdfs:label ?eq_label }
    """
    rows = _sparql(q)
    return [r.get("eq_label") or "" for r in rows if r.get("eq_label")]


def _sparql_equipment_labels_for_site(site_label: str) -> list[str]:
    """Equipment labels only for equipment under this site. Excludes other sites/BACnet."""
    label_lit = json.dumps(site_label)
    q = f"""
    PREFIX brick: <https://brickschema.org/schema/Brick#>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    SELECT ?eq_label WHERE {{
      ?eq brick:isPartOf ?site .
      ?site rdfs:label {label_lit} .
      ?eq rdfs:label ?eq_label .
    }}
    """
    rows = _sparql(q)
    return [r.get("eq_label") or "" for r in rows if r.get("eq_label")]


def _sparql_equipment_feeds_for_site(site_label: str) -> list[tuple[str, str]]:
    """(equipment_label, feeds_label) for equipment under this site that have brick:feeds."""
    label_lit = json.dumps(site_label)
    q = f"""
    PREFIX brick: <https://brickschema.org/schema/Brick#>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    SELECT ?eq_label ?feeds_label WHERE {{
      ?eq brick:isPartOf ?site .
      ?site rdfs:label {label_lit} .
      ?eq rdfs:label ?eq_label .
      ?eq brick:feeds ?other .
      ?other rdfs:label ?feeds_label .
    }}
    """
    rows = _sparql(q)
    return [(r.get("eq_label") or "", r.get("feeds_label") or "") for r in rows if r.get("eq_label") and r.get("feeds_label")]


def run():
    print(
        f"\n=== Open-FDD CRUD API Test (CRUD + RDF + SPARQL) ===\n"
        f"Base URL: {BASE_URL}\n"
        f"SPARQL: all queries via POST {BASE_URL}/data-model/sparql (CRUD API only; no direct triple store).\n"
    )
    if BACNET_URL:
        print(f"BACNET_URL: {BACNET_URL} (point_discovery_to_graph, device_instances={list(BACNET_TEST_DEVICE_INSTANCES)})\n")

    # Wait for API to be ready (avoids "Connection reset by peer" when test runs right after bootstrap)
    try:
        _wait_for_api_ready()
    except RuntimeError as e:
        print(f"  {e}\n")
        raise

    # --- [0] Verify all SPARQL is via CRUD endpoint only (POST /data-model/sparql; script uses BASE_URL = localhost by default) ---
    print("[0] SPARQL via CRUD only: POST /data-model/sparql (sites query)")
    sites_query = """
    PREFIX brick: <https://brickschema.org/schema/Brick#>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    SELECT ?site ?site_label WHERE { ?site a brick:Site . ?site rdfs:label ?site_label }
    """
    code, data = _request("POST", "/data-model/sparql", json_body={"query": sites_query})
    assert ok(code), f"SPARQL via CRUD failed: {code} {data}"
    assert isinstance(data, dict) and "bindings" in data, "SPARQL response must have bindings"
    print(f"    OK — SPARQL from {BASE_URL}/data-model/sparql only; bindings count={len(data['bindings'])}\n")

    # --- Health (graph_serialization when API supports it) ---
    print("[1] GET /health")
    code, data = _request("GET", "/health")
    assert ok(code), f"Expected 200, got {code}"
    assert data.get("status") == "ok"
    gs = data.get("graph_serialization") or {}
    if gs and ("last_ok" in gs or "current_time" in gs):
        print(f"    OK — graph_serialization: last_ok={gs.get('last_ok')}, last_serialization_at={gs.get('last_serialization_at')}\n")
    else:
        print("    OK (upgrade API for graph_serialization in /health)\n")

    # --- Serialize graph to file (same as interval job; 404 = old API) ---
    print("[1b] POST /data-model/serialize")
    code, ser = _request("POST", "/data-model/serialize")
    if code == 404:
        print("    SKIP — route not found (rebuild API for graph model)\n")
    elif ok(code):
        assert ser is None or ser.get("status") in ("ok", "error"), "serialize must return status"
        if isinstance(ser, dict) and ser.get("status") == "error":
            print(f"    WARN — {ser.get('error')}\n")
        else:
            print(f"    OK — path={ser.get('path') if isinstance(ser, dict) else '—'}\n")
    else:
        assert False, f"Serialize failed: {code} {ser}"

    # --- Config (RDF in same graph; mock setup with canonical defaults) ---
    from open_fdd.platform.default_config import DEFAULT_PLATFORM_CONFIG

    print("[1c] PUT /config (platform config into RDF graph — default config)")
    code, put_res = _request("PUT", "/config", json_body=DEFAULT_PLATFORM_CONFIG)
    assert ok(code), f"PUT /config failed: {code} {put_res}"
    print("    OK — config written to graph\n")

    print("[1d] GET /config")
    code, get_cfg = _request("GET", "/config")
    assert ok(code), f"GET /config failed: {code} {get_cfg}"
    assert isinstance(get_cfg, dict), "GET /config must return JSON object"
    assert get_cfg.get("rule_interval_hours") == DEFAULT_PLATFORM_CONFIG["rule_interval_hours"]
    assert get_cfg.get("bacnet_server_url") == DEFAULT_PLATFORM_CONFIG["bacnet_server_url"]
    print(f"    OK — rule_interval_hours={get_cfg.get('rule_interval_hours')}, bacnet_server_url={get_cfg.get('bacnet_server_url')}\n")

    print("[1e] SPARQL: ofdd:PlatformConfig (via POST /data-model/sparql only)")
    config_sparql = """
    PREFIX ofdd: <http://openfdd.local/ontology#>
    PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
    SELECT ?p ?v WHERE {
      ?c a ofdd:PlatformConfig .
      ?c ?p ?v .
    }
    """
    code, sparql_res = _request("POST", "/data-model/sparql", json_body={"query": config_sparql})
    assert ok(code), f"SPARQL config query failed: {code} {sparql_res}"
    assert isinstance(sparql_res, dict) and "bindings" in sparql_res
    bindings = sparql_res["bindings"]
    assert len(bindings) >= 5, f"Expected at least 5 config triples via SPARQL, got {len(bindings)}"
    preds = [str(b.get("p") or "") for b in bindings if b.get("p")]
    assert any("ruleIntervalHours" in p or "rule_interval" in p.lower() for p in preds), (
        f"SPARQL: expected ofdd:ruleIntervalHours in config triples; predicates: {preds[:15]}"
    )
    assert any("bacnetServerUrl" in p or "bacnet_server" in p.lower() for p in preds), (
        f"SPARQL: expected ofdd:bacnetServerUrl in config triples; predicates: {preds[:15]}"
    )
    print(f"    OK — {len(bindings)} config triples in graph (SPARQL via CRUD only)\n")

    # --- BACnet proxy (when gateway URL set) ---
    # Pass url in body so API (often in Docker) uses a URL reachable from the container (e.g. host.docker.internal:8080)
    def _bacnet_body(**kwargs):
        body = dict(kwargs)
        if BACNET_URL:
            body["url"] = BACNET_URL
        return body

    if BACNET_URL:
        print("[1a] POST /bacnet/server_hello (gateway reachable)")
        code, sh = _request("POST", "/bacnet/server_hello", json_body=_bacnet_body())
        assert ok(code), f"server_hello failed: {code} {sh}"
        # API returns {ok, body} or {ok, error}; gateway response shape varies (result/message/etc.)
        assert isinstance(sh, dict) and sh.get("ok"), (
            f"server_hello proxy failed: {sh.get('error', sh)}"
        )
        print("    OK — gateway reachable via CRUD API\n")

        print("[1a2] POST /bacnet/whois_range (discover devices)")
        code, wr = _request(
            "POST",
            "/bacnet/whois_range",
            json_body=_bacnet_body(request={"start_instance": 1, "end_instance": 3456800}),
            timeout=15.0,
        )
        assert ok(code), f"whois_range failed: {code} {wr}"
        _body = wr.get("body") if isinstance(wr, dict) else wr
        _res = _body.get("result") if isinstance(_body, dict) else {}
        _data = (_res.get("data") or _res) if isinstance(_res, dict) else {}
        devs = _data.get("devices") or []
        print(f"    OK — {len(devs)} device(s)\n")

        # Graph from point_discovery: clean BACnet RDF into in-memory graph (both test devices)
        print(f"[1a3] POST /bacnet/point_discovery_to_graph (devices {list(BACNET_TEST_DEVICE_INSTANCES)} → in-memory graph)")
        _sample_names = []
        for dev_inst in BACNET_TEST_DEVICE_INSTANCES:
            code, pdg = _request(
                "POST",
                "/bacnet/point_discovery_to_graph",
                json_body=_bacnet_body(
                    instance={"device_instance": dev_inst},
                    update_graph=True,
                    write_file=True,
                ),
                timeout=30.0,
            )
            assert ok(code), f"point_discovery_to_graph({dev_inst}) failed: {code} {pdg}"
            if pdg.get("graph_error"):
                print(f"    WARN — graph_error for {dev_inst}: {pdg['graph_error']}")
            # Grab object names from first device only for SPARQL sample check
            if not _sample_names:
                _body = pdg.get("body") if isinstance(pdg, dict) else pdg
                _res = _body.get("result") if isinstance(_body, dict) else {}
                _data = (_res.get("data") or _res) if isinstance(_res, dict) else {}
                _objs = _data.get("objects") or []
                for _o in _objs[:10]:
                    if isinstance(_o, dict):
                        _n = (_o.get("object_name") or _o.get("name") or "").strip()
                        if _n and _n not in _sample_names:
                            _sample_names.append(_n)
                            if len(_sample_names) >= 5:
                                break
        print(f"    OK — discovered {len(BACNET_TEST_DEVICE_INSTANCES)} device(s)\n")
        # SPARQL-only: bacnet:Device, object count, and that discovery names appear in graph
        print("[1a4] SPARQL: bacnet:Device, object count, and sample object names in graph")
        q_dev = """
        PREFIX bacnet: <http://data.ashrae.org/bacnet/2020#>
        SELECT ?dev WHERE { ?dev a bacnet:Device }
        """
        q_objs = """
        PREFIX bacnet: <http://data.ashrae.org/bacnet/2020#>
        SELECT (COUNT(?obj) AS ?n) WHERE { ?dev a bacnet:Device . ?dev bacnet:contains ?obj }
        """
        dev_bindings = _sparql(q_dev)
        obj_bindings = _sparql(q_objs)
        assert len(dev_bindings) >= len(BACNET_TEST_DEVICE_INSTANCES), (
            f"SPARQL: at least {len(BACNET_TEST_DEVICE_INSTANCES)} bacnet:Device, got {len(dev_bindings)}"
        )
        print(f"    SPARQL result (bacnet:Device): {[b.get('dev') for b in dev_bindings]}")
        print(f"    SPARQL result (object count): {obj_bindings[0].get('n') if obj_bindings else 'N/A'}")
        dev_uris = [str(b.get("dev") or "") for b in dev_bindings if b.get("dev")]
        for dev_inst in BACNET_TEST_DEVICE_INSTANCES:
            assert any(str(dev_inst) in u for u in dev_uris), (
                f"SPARQL: device {dev_inst} not in graph; URIs: {dev_uris}"
            )
        n_objs = 0
        if obj_bindings and obj_bindings[0].get("n"):
            try:
                n_objs = int(obj_bindings[0]["n"].strip())
            except (ValueError, TypeError):
                pass
        # For first device instance, get object names from graph and assert discovery sample is there
        if _sample_names:
            inst = BACNET_TEST_DEVICE_INSTANCES[0]
            q_names = f"""
            PREFIX bacnet: <http://data.ashrae.org/bacnet/2020#>
            SELECT ?name WHERE {{
              ?dev a bacnet:Device ; bacnet:device-instance {inst} ; bacnet:contains ?obj .
              ?obj bacnet:object-name ?name .
            }}
            """
            name_bindings = _sparql(q_names)
            graph_names = [r.get("name") or "" for r in name_bindings if r.get("name")]
            for _name in _sample_names:
                assert _name in graph_names, (
                    f"SPARQL: discovery object name {_name!r} not in graph for device {inst}. "
                    f"Graph names (sample): {graph_names[:15]!r}"
                )
            print(f"    OK — {len(dev_bindings)} Device(s), {n_objs} objects, {len(_sample_names)} sample names in graph\n")
        else:
            print(f"    OK — {len(dev_bindings)} Device(s), {n_objs} objects (no object names from discovery)\n")

        print("[1a5] GET /data-model/ttl?save=true (validate BACnet devices in TTL)")
        code, ttl_body = _request("GET", "/data-model/ttl?save=true")
        assert code == 200, f"GET /data-model/ttl failed: {code}"
        assert isinstance(ttl_body, str) and len(ttl_body) > 0, "TTL response should be non-empty string"
        for dev_inst in BACNET_TEST_DEVICE_INSTANCES:
            assert str(dev_inst) in ttl_body, f"TTL should contain device instance {dev_inst}"
        assert "bacnet:Device" in ttl_body, "TTL should contain bacnet:Device"
        print(f"    OK — TTL contains devices {list(BACNET_TEST_DEVICE_INSTANCES)} and bacnet:Device\n")
    else:
        print("[1a] SKIP BACnet (use --bacnet-url or omit --skip-bacnet)\n")

    # Unique site name per run so [20b] SPARQL assertion isn't affected by leftover sites from previous runs
    test_site_name = f"test-crud-site-{uuid4().hex[:8]}"

    # --- Create site ---
    print("[2] POST /sites")
    code, site = _request(
        "POST",
        "/sites",
        json_body={"name": test_site_name, "description": "Script test site"},
    )
    assert ok(code), f"Expected 201/200, got {code}: {site}"
    site_id = site["id"]
    print(f"    OK → site_id={site_id}\n")

    # --- Get site ---
    print("[3] GET /sites/{id}")
    code, got = _request("GET", f"/sites/{site_id}")
    assert ok(code)
    assert got["name"] == test_site_name
    print("    OK\n")

    # --- List sites ---
    print("[4] GET /sites")
    code, sites = _request("GET", "/sites")
    assert ok(code)
    assert any(s["id"] == site_id for s in sites)
    print(f"    OK ({len(sites)} sites)\n")

    # --- SPARQL: site in TTL after create ---
    print("[4b] SPARQL: site labels (TTL in sync)")
    labels = _sparql_site_labels()
    assert test_site_name in labels, f"Expected {test_site_name!r} in {labels}"
    print(f"    SPARQL result: {labels}")
    print(f"    OK — {labels}\n")

    # --- Data model TTL (SPARQL already validated site/points; no grep on TTL) ---
    print("[4c] GET /data-model/ttl (smoke: 200, string)")
    code, ttl_body = _request("GET", "/data-model/ttl")
    assert ok(code), f"GET /data-model/ttl failed: {code}"
    assert isinstance(ttl_body, str), "TTL response should be string"
    assert len(ttl_body) > 0, "TTL non-empty"
    print(f"    OK — TTL length {len(ttl_body)} (site/points validated via SPARQL in [4b])\n")

    # --- TestBenchSite testbench: ensure site + TestBenchAhu / TestBenchVav, validate in graph and TTL ---
    print(f"[4d] TestBenchSite testbench: ensure site {TESTBENCH_SITE_NAME!r} and equipment {TESTBENCH_AHU_NAME!r}, {TESTBENCH_VAV_NAME!r}")
    code, sites_list = _request("GET", "/sites")
    assert ok(code), f"GET /sites failed: {code}"
    bens_site = next((s for s in sites_list if s.get("name") == TESTBENCH_SITE_NAME), None)
    if bens_site is None:
        code, bens_site = _request(
            "POST",
            "/sites",
            json_body={"name": TESTBENCH_SITE_NAME, "description": "TestBench"},
        )
        assert ok(code), f"POST /sites TestBenchSite failed: {code} {bens_site}"
    bens_site_id = bens_site["id"]
    # Create equipment if not already present (by name under this site)
    code, eq_list = _request("GET", f"/equipment?site_id={bens_site_id}")
    assert ok(code)
    existing_names = {e.get("name") for e in eq_list if e.get("name")}
    if TESTBENCH_AHU_NAME not in existing_names:
        code, _ = _request(
            "POST",
            "/equipment",
            json_body={
                "site_id": bens_site_id,
                "name": TESTBENCH_AHU_NAME,
                "description": "Testbench AHU",
                "equipment_type": "Air_Handling_Unit",
            },
        )
        assert ok(code), f"POST /equipment {TESTBENCH_AHU_NAME} failed: {code}"
    if TESTBENCH_VAV_NAME not in existing_names:
        code, _ = _request(
            "POST",
            "/equipment",
            json_body={
                "site_id": bens_site_id,
                "name": TESTBENCH_VAV_NAME,
                "description": "Testbench VAV",
                "equipment_type": "VAV",
            },
        )
        assert ok(code), f"POST /equipment {TESTBENCH_VAV_NAME} failed: {code}"
    print(f"    OK — site_id={bens_site_id}\n")

    print("[4e] SPARQL: TestBenchSite site and testbench equipment in graph")
    site_labels = _sparql_site_labels()
    assert TESTBENCH_SITE_NAME in site_labels, f"Expected {TESTBENCH_SITE_NAME!r} in site labels: {site_labels}"
    eq_labels = _sparql_equipment_labels_for_site(TESTBENCH_SITE_NAME)
    for name in (TESTBENCH_AHU_NAME, TESTBENCH_VAV_NAME):
        assert name in eq_labels, f"Expected {name!r} in equipment labels for TestBenchSite: {eq_labels}"
    print(f"    SPARQL result (site labels): {site_labels}")
    print(f"    SPARQL result (equipment for TestBenchSite): {eq_labels}")
    print(f"    OK — site {TESTBENCH_SITE_NAME!r}, equipment {eq_labels}\n")

    print("[4f] GET /data-model/ttl?save=true (validate TestBenchSite + testbench equipment in TTL)")
    code, ttl_body_bens = _request("GET", "/data-model/ttl?save=true")
    assert code == 200, f"GET /data-model/ttl failed: {code}"
    assert isinstance(ttl_body_bens, str), "TTL response should be string"
    assert TESTBENCH_SITE_NAME in ttl_body_bens, f"TTL should contain site label {TESTBENCH_SITE_NAME!r}"
    assert TESTBENCH_AHU_NAME in ttl_body_bens, f"TTL should contain equipment {TESTBENCH_AHU_NAME!r}"
    assert TESTBENCH_VAV_NAME in ttl_body_bens, f"TTL should contain equipment {TESTBENCH_VAV_NAME!r}"
    print(f"    OK — TTL contains {TESTBENCH_SITE_NAME!r}, {TESTBENCH_AHU_NAME!r}, {TESTBENCH_VAV_NAME!r}\n")

    # --- [4f1] TestBenchSite: 2 BACnet points (SA-T, ZoneTemp) so after [27] scraper still has points to poll ---
    print("[4f1] PUT /data-model/import (2 BACnet points for TestBenchSite — SA-T, ZoneTemp; survives [27] so scraper has work)")
    code, eq_list_bens = _request("GET", f"/equipment?site_id={bens_site_id}")
    assert ok(code), f"GET /equipment failed: {code}"
    bens_ahu = next((e for e in eq_list_bens if e.get("name") == TESTBENCH_AHU_NAME), None)
    bens_vav = next((e for e in eq_list_bens if e.get("name") == TESTBENCH_VAV_NAME), None)
    assert bens_ahu and bens_vav, f"TestBenchSite equipment not found: {eq_list_bens}"
    code, existing_bens_points = _request("GET", f"/points?site_id={bens_site_id}")
    assert ok(code), f"GET /points failed: {code}"
    existing_bens_by_ext = {p["external_id"]: p for p in (existing_bens_points or []) if isinstance(p, dict) and p.get("external_id")}
    bens_pts = []
    for ext_id, dev, oid, eq_id, brick, rule in [
        ("SA-T", "3456789", "analog-input,2", bens_ahu["id"], "Supply_Air_Temperature_Sensor", "Supply_Air_Temperature_Sensor"),
        ("ZoneTemp", "3456790", "analog-input,1", bens_vav["id"], "Zone_Temperature_Sensor", "Zone_Temperature_Sensor"),
    ]:
        existing = existing_bens_by_ext.get(ext_id)
        if existing:
            bens_pts.append({"point_id": existing["id"], "equipment_id": eq_id, "brick_type": brick, "rule_input": rule, "polling": True})
        else:
            bens_pts.append({"site_id": bens_site_id, "external_id": ext_id, "bacnet_device_id": dev, "object_identifier": oid, "object_name": ext_id, "equipment_id": eq_id, "brick_type": brick, "rule_input": rule, "unit": "degF", "polling": True})
    code, res = _request("PUT", "/data-model/import", json_body={"points": bens_pts})
    assert ok(code), f"PUT /data-model/import TestBenchSite points failed: {code} {res}"
    print(f"    OK — TestBenchSite has 2 BACnet points; after [27] only TestBenchSite remains and scraper will poll these.\n")

    # --- [4f1b] AI-style import: equipment by name (no equipment_id), site_id from “export?site_id=…” so no UUID paste; feeds/fed_by by name ---
    # Simulates: GET /data-model/export?site_id=BensTestBench → LLM tags → PUT /data-model/import (equipment_name only; site_id pre-filled from export).
    print("[4f1b] PUT /data-model/import (AI-style payload: equipment_name only, site_id from export; feeds/fed_by by name)")
    ai_site_id = bens_site_id  # as if export?site_id=TestBenchSite pre-filled this
    ai_points = [
        {
            "point_id": None,
            "bacnet_device_id": "3456789",
            "object_identifier": "analog-input,1",
            "object_name": "DAP-P",
            "site_id": ai_site_id,
            "equipment_name": "AHU-1",
            "external_id": "DAP-P",
            "brick_type": "Supply_Air_Static_Pressure_Sensor",
            "rule_input": "ahu_dsp",
            "polling": True,
        },
        {
            "point_id": None,
            "bacnet_device_id": "3456790",
            "object_identifier": "analog-input,2",
            "object_name": "VAVFlow",
            "site_id": ai_site_id,
            "equipment_name": "VAV-1",
            "external_id": "VAVFlow",
            "brick_type": "Zone_Air_Flow_Sensor",
            "rule_input": "vav_flow",
            "polling": True,
        },
    ]
    ai_equipment = [
        {"equipment_name": "AHU-1", "site_id": ai_site_id, "feeds": ["VAV-1"], "fed_by": []},
        {"equipment_name": "VAV-1", "site_id": ai_site_id, "feeds": [], "fed_by": ["AHU-1"]},
    ]
    code, ai_res = _request("PUT", "/data-model/import", json_body={"points": ai_points, "equipment": ai_equipment})
    assert ok(code), f"PUT /data-model/import AI-style payload failed: {code} {ai_res}"
    ai_created = ai_res.get("created", 0)
    ai_total = ai_res.get("total", 0)
    assert ai_created >= 2 or ai_total >= 2, f"AI import should create at least 2 points: {ai_res}"
    print(f"    OK — {ai_res.get('created', 0)} created, {ai_res.get('updated', 0)} updated, total={ai_total}\n")

    print("[4f1c] SPARQL + TTL: verify AI payload (AHU-1, VAV-1, feeds) in model")
    eq_labels_bens = _sparql_equipment_labels_for_site(TESTBENCH_SITE_NAME)
    for ai_eq in ("AHU-1", "VAV-1"):
        assert ai_eq in eq_labels_bens, f"Expected {ai_eq!r} in equipment for {TESTBENCH_SITE_NAME!r}: {eq_labels_bens}"
    feeds_bens = _sparql_equipment_feeds_for_site(TESTBENCH_SITE_NAME)
    feeds_map_bens = {e: f for e, f in feeds_bens}
    assert "AHU-1" in feeds_map_bens and feeds_map_bens["AHU-1"] == "VAV-1", f"Expected AHU-1 feeds VAV-1: {feeds_bens}"
    code, ttl_after_ai = _request("GET", "/data-model/ttl?save=true")
    assert code == 200, f"GET /data-model/ttl failed: {code}"
    assert "AHU-1" in ttl_after_ai, f"TTL should contain equipment AHU-1 after AI import"
    assert "VAV-1" in ttl_after_ai, f"TTL should contain equipment VAV-1 after AI import"
    pt_labels_bens = _sparql_point_labels_for_site(TESTBENCH_SITE_NAME)
    assert "DAP-P" in pt_labels_bens or "VAVFlow" in pt_labels_bens, f"Expected DAP-P or VAVFlow in point labels: {pt_labels_bens}"
    print(f"    SPARQL equipment (TestBenchSite): {eq_labels_bens}")
    print(f"    SPARQL feeds: {feeds_bens}")
    print(f"    OK — AI payload in model (AHU-1, VAV-1, feeds); TTL and points verified.\n")

    # --- [4f2] Full LLM payload import into DemoSite (many BACnet points, two devices; idempotent) ---
    # Uses tools/demo_site_llm_payload.json: sites/equipments/relationships/points with string IDs (site-1, ahu-1, ...).
    # Transform to API format (UUIDs), create-or-update points so re-runs do not duplicate.
    print("[4f2] PUT /data-model/import (full LLM payload → DemoSite: many BACnet points, devices 3456789 + 3456790)")
    assert DEMO_SITE_LLM_PAYLOAD_PATH.exists(), f"Missing {DEMO_SITE_LLM_PAYLOAD_PATH}"
    with open(DEMO_SITE_LLM_PAYLOAD_PATH, encoding="utf-8") as f:
        llm_payload = json.load(f)
    sites_llm = llm_payload.get("sites") or []
    equipments_llm = llm_payload.get("equipments") or []
    relationships_llm = llm_payload.get("relationships") or []
    points_llm = llm_payload.get("points") or []
    assert sites_llm, "LLM payload must have at least one site"
    site_name_llm = sites_llm[0].get("site_name") or DEMO_SITE_LLM_NAME
    code, sites_list = _request("GET", "/sites")
    assert ok(code), f"GET /sites failed: {code}"
    demo_site = next((s for s in sites_list if s.get("name") == site_name_llm), None)
    if demo_site is None:
        code, demo_site = _request("POST", "/sites", json_body={"name": site_name_llm, "description": "LLM payload DemoSite"})
        assert ok(code), f"POST /sites {site_name_llm} failed: {code} {demo_site}"
    demo_site_id_full = demo_site["id"]
    code, eq_list = _request("GET", f"/equipment?site_id={demo_site_id_full}")
    assert ok(code), f"GET /equipment failed: {code}"
    existing_eq_by_name = {e["name"]: e for e in eq_list if isinstance(e, dict) and e.get("name")}
    eq_key_to_uuid = {}
    for eq in equipments_llm:
        eid_key = eq.get("equipment_id")
        ename = eq.get("equipment_name")
        if not eid_key or not ename:
            continue
        if ename not in existing_eq_by_name:
            eq_type = eq.get("brick_type") or "Equipment"
            code, created = _request("POST", "/equipment", json_body={"site_id": demo_site_id_full, "name": ename, "description": eq_type, "equipment_type": eq_type})
            assert ok(code), f"POST /equipment {ename} failed: {code} {created}"
            existing_eq_by_name[ename] = created
        eq_key_to_uuid[eid_key] = existing_eq_by_name[ename]["id"]
    code, existing_points = _request("GET", f"/points?site_id={demo_site_id_full}")
    assert ok(code), f"GET /points failed: {code}"
    existing_by_key = {}
    for p in existing_points or []:
        if isinstance(p, dict) and p.get("external_id") is not None:
            key = (p["external_id"], str(p.get("bacnet_device_id") or ""), str(p.get("object_identifier") or ""))
            existing_by_key[key] = p
    used_external_ids = {p["external_id"] for p in (existing_points or []) if isinstance(p, dict) and p.get("external_id")}
    api_points = []
    for pt in points_llm:
        if not isinstance(pt, dict):
            continue
        ext_id = pt.get("external_id")
        site_id_llm = pt.get("site_id")
        eq_id_llm = pt.get("equipment_id")
        if site_id_llm != sites_llm[0].get("site_id"):
            continue
        equipment_uuid = eq_key_to_uuid.get(eq_id_llm) if eq_id_llm and eq_id_llm in eq_key_to_uuid else None
        key = (ext_id, str(pt.get("bacnet_device_id") or ""), str(pt.get("object_identifier") or ""))
        key_alt = (f"{ext_id}_{pt.get('bacnet_device_id')}", str(pt.get("bacnet_device_id") or ""), str(pt.get("object_identifier") or ""))
        existing = existing_by_key.get(key) or existing_by_key.get(key_alt)
        if existing:
            api_points.append({
                "point_id": existing["id"],
                "equipment_id": equipment_uuid,
                "brick_type": pt.get("brick_type"),
                "rule_input": pt.get("rule_input"),
                "polling": pt.get("polling") if pt.get("polling") is not None else True,
            })
        else:
            if not pt.get("bacnet_device_id") or not pt.get("object_identifier"):
                continue
            external_id_final = ext_id
            if external_id_final in used_external_ids:
                external_id_final = f"{ext_id}_{pt['bacnet_device_id']}"
            used_external_ids.add(external_id_final)
            api_points.append({
                "site_id": demo_site_id_full,
                "external_id": external_id_final,
                "bacnet_device_id": str(pt["bacnet_device_id"]),
                "object_identifier": str(pt["object_identifier"]),
                "object_name": pt.get("object_name"),
                "equipment_id": equipment_uuid,
                "brick_type": pt.get("brick_type"),
                "rule_input": pt.get("rule_input"),
                "unit": pt.get("unit"),
                "polling": pt.get("polling") if pt.get("polling") is not None else True,
            })
    api_equipment = []
    for rel in relationships_llm:
        if rel.get("predicate") != "feeds":
            continue
        sub_id = eq_key_to_uuid.get(rel.get("subject_equipment_id"))
        obj_id = eq_key_to_uuid.get(rel.get("object_equipment_id"))
        if sub_id and obj_id:
            api_equipment.append({"equipment_id": sub_id, "feeds_equipment_id": obj_id})
            api_equipment.append({"equipment_id": obj_id, "fed_by_equipment_id": sub_id})
    code, import_res = _request("PUT", "/data-model/import", json_body={"points": api_points, "equipment": api_equipment})
    assert ok(code), f"PUT /data-model/import DemoSite failed: {code} {import_res}"
    created = import_res.get("created", 0)
    updated = import_res.get("updated", 0)
    polling_count = sum(1 for pt in points_llm if isinstance(pt, dict) and pt.get("polling") is True)
    print(f"    OK — DemoSite: {created} created, {updated} updated, {len(api_points)} points ({polling_count} with polling=true). Re-run safe (upsert).\n")

    # --- PUT /data-model/import (LLM-style payload: real UUIDs, points + equipment feeds) ---
    demo_site_name = f"demo-import-{uuid4().hex[:8]}"
    print(f"[4g] PUT /data-model/import (create DemoSite-style site + equipment, import tagged points + feeds)")
    code, demo_site = _request("POST", "/sites", json_body={"name": demo_site_name, "description": "Import test"})
    assert ok(code), f"POST /sites failed: {code} {demo_site}"
    demo_site_id = demo_site["id"]
    code, ahu = _request("POST", "/equipment", json_body={"site_id": demo_site_id, "name": "AHU-1", "description": "AHU", "equipment_type": "Air_Handling_Unit"})
    assert ok(code), f"POST /equipment AHU-1 failed: {code}"
    ahu_id = ahu["id"]
    code, vav = _request("POST", "/equipment", json_body={"site_id": demo_site_id, "name": "VAV-1", "description": "VAV", "equipment_type": "Variable_Air_Volume_Box"})
    assert ok(code), f"POST /equipment VAV-1 failed: {code}"
    vav_id = vav["id"]
    code, zone = _request("POST", "/equipment", json_body={"site_id": demo_site_id, "name": "ZONE-1", "description": "Zone", "equipment_type": "HVAC_Zone"})
    assert ok(code), f"POST /equipment ZONE-1 failed: {code}"
    zone_id = zone["id"]
    # Import body: only points + equipment (no sites/equipments/relationships). AHU feeds VAV, VAV feeds ZONE.
    import_points = [
        {"site_id": demo_site_id, "external_id": "SA-T", "bacnet_device_id": "3456789", "object_identifier": "analog-input,2", "object_name": "SA-T", "equipment_id": ahu_id, "brick_type": "Supply_Air_Temperature_Sensor", "rule_input": "Supply_Air_Temperature_Sensor", "unit": "degF", "polling": True},
        {"site_id": demo_site_id, "external_id": "ZoneTemp", "bacnet_device_id": "3456790", "object_identifier": "analog-input,1", "object_name": "ZoneTemp", "equipment_id": zone_id, "brick_type": "Zone_Temperature_Sensor", "rule_input": "Zone_Temperature_Sensor", "unit": "degF", "polling": True},
    ]
    import_equipment = [
        {"equipment_id": ahu_id, "feeds_equipment_id": vav_id},
        {"equipment_id": vav_id, "fed_by_equipment_id": ahu_id, "feeds_equipment_id": zone_id},
        {"equipment_id": zone_id, "fed_by_equipment_id": vav_id},
    ]
    code, import_res = _request("PUT", "/data-model/import", json_body={"points": import_points, "equipment": import_equipment})
    assert ok(code), f"PUT /data-model/import failed: {code} {import_res}"
    created = import_res.get("created", 0)
    updated = import_res.get("updated", 0)
    assert created >= 2 or updated >= 2 or (created + updated) >= 2, f"Import should create/update at least 2 points: {import_res}"
    print(f"    OK — site={demo_site_id}, created={created}, updated={updated}\n")

    print("[4h] SPARQL: DemoSite site + equipment labels + feeds (AHU feeds VAV, VAV feeds ZONE)")
    site_labels = _sparql_site_labels()
    assert demo_site_name in site_labels, f"Expected {demo_site_name!r} in site labels: {site_labels}"
    eq_labels = _sparql_equipment_labels_for_site(demo_site_name)
    for name in ("AHU-1", "VAV-1", "ZONE-1"):
        assert name in eq_labels, f"Expected {name!r} in equipment labels: {eq_labels}"
    feeds = _sparql_equipment_feeds_for_site(demo_site_name)
    feeds_map = {e: f for e, f in feeds}
    assert "AHU-1" in feeds_map and feeds_map["AHU-1"] == "VAV-1", f"Expected AHU-1 feeds VAV-1: {feeds}"
    assert "VAV-1" in feeds_map and feeds_map["VAV-1"] == "ZONE-1", f"Expected VAV-1 feeds ZONE-1: {feeds}"
    print(f"    SPARQL result (site labels): {site_labels}")
    print(f"    SPARQL result (equipment labels): {eq_labels}")
    print(f"    SPARQL result (feeds): {feeds}")
    print(f"    OK — site {demo_site_name!r}, equipment {eq_labels}, feeds {feeds}\n")

    print("[4i] GET /data-model/export (diy-bacnet ready: polling=true points with bacnet_device_id + object_identifier)")
    code, export_demo = _request("GET", f"/data-model/export?site_id={demo_site_id}")
    assert ok(code), f"GET /data-model/export failed: {code}"
    assert isinstance(export_demo, list), "Export should be a list"
    polling_true = [r for r in export_demo if isinstance(r, dict) and r.get("polling") is True]
    bacnet_polling = [r for r in polling_true if r.get("bacnet_device_id") and r.get("object_identifier")]
    by_ext = {r.get("external_id"): r for r in bacnet_polling if r.get("external_id")}
    assert "SA-T" in by_ext, f"Export should have SA-T with polling true and BACnet refs: {list(by_ext.keys())}"
    assert "ZoneTemp" in by_ext, f"Export should have ZoneTemp with polling true and BACnet refs: {list(by_ext.keys())}"
    print("    polling=true (diy-bacnet ready) — device + BACnet addressing:")
    for r in bacnet_polling:
        print(f"      external_id={r.get('external_id')!r}  bacnet_device_id={r.get('bacnet_device_id')!r}  object_identifier={r.get('object_identifier')!r}")
    print(f"    OK — {len(bacnet_polling)} BACnet point(s) with polling=true (diy-bacnet ready)\n")

    print("[4j] SPARQL: all BACnet devices and point addresses (graph); polling filter = use GET /data-model/export")
    q_bacnet = """
    PREFIX bacnet: <http://data.ashrae.org/bacnet/2020#>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    SELECT ?device_uri ?device_instance ?obj_uri ?object_id ?object_name WHERE {
      ?device_uri a bacnet:Device ;
        bacnet:device-instance ?device_instance ;
        bacnet:contains ?obj_uri .
      ?obj_uri bacnet:object-identifier ?object_id .
      OPTIONAL { ?obj_uri bacnet:object-name ?object_name . }
    }
    ORDER BY ?device_instance ?object_id
    """
    bacnet_bindings = _sparql(q_bacnet)
    assert len(bacnet_bindings) > 0, "SPARQL should return at least one BACnet device/point from graph"
    dev_instances = set()
    for b in bacnet_bindings:
        inst = b.get("device_instance")
        if inst is not None:
            dev_instances.add(str(inst).strip())
    for dev_inst in BACNET_TEST_DEVICE_INSTANCES:
        assert str(dev_inst) in dev_instances, f"SPARQL should include device {dev_inst}; got {dev_instances}"
    print("    SPARQL result (BACnet devices + point addresses):")
    for b in bacnet_bindings[:15]:  # first 15 rows
        print(f"      device_instance={b.get('device_instance')}  object_identifier={b.get('object_id')}  object_name={b.get('object_name')}")
    if len(bacnet_bindings) > 15:
        print(f"      ... and {len(bacnet_bindings) - 15} more")
    print(f"    OK — {len(bacnet_bindings)} BACnet point(s) in graph across devices {sorted(dev_instances)}. For diy-bacnet: use GET /data-model/export and filter polling=true.\n")

    # --- PATCH site ---
    print("[5] PATCH /sites/{id}")
    code, patched = _request(
        "PATCH",
        f"/sites/{site_id}",
        json_body={"description": "Updated description"},
    )
    assert ok(code)
    assert patched["description"] == "Updated description"
    print("    OK\n")

    # --- Create equipment ---
    print("[6] POST /equipment")
    code, equip = _request(
        "POST",
        "/equipment",
        json_body={
            "site_id": site_id,
            "name": "test-ahu-1",
            "description": "Test AHU",
            "equipment_type": "Air_Handling_Unit",
        },
    )
    assert ok(code)
    equipment_id = equip["id"]
    print(f"    OK → equipment_id={equipment_id}\n")

    # --- Get equipment ---
    print("[7] GET /equipment/{id}")
    code, got = _request("GET", f"/equipment/{equipment_id}")
    assert ok(code)
    assert got["name"] == "test-ahu-1"
    print("    OK\n")

    # --- List equipment (by site) ---
    print("[8] GET /equipment?site_id=...")
    code, eq_list = _request("GET", f"/equipment?site_id={site_id}")
    assert ok(code)
    assert any(e["id"] == equipment_id for e in eq_list)
    print("    OK\n")

    # --- PATCH equipment ---
    print("[9] PATCH /equipment/{id}")
    code, patched = _request(
        "PATCH",
        f"/equipment/{equipment_id}",
        json_body={"description": "Updated AHU"},
    )
    assert ok(code)
    assert patched["description"] == "Updated AHU"
    print("    OK\n")

    # --- Create point (with equipment) ---
    print("[10] POST /points (with equipment)")
    code, pt1 = _request(
        "POST",
        "/points",
        json_body={
            "site_id": site_id,
            "equipment_id": equipment_id,
            "external_id": "SA-T",
            "brick_type": "Supply_Air_Temperature_Sensor",
            "fdd_input": "sat",
            "unit": "degF",
        },
    )
    assert ok(code), f"POST /points failed: {code} — {pt1!r}"
    assert isinstance(pt1, dict) and pt1.get("id"), f"POST /points missing id: {pt1}"
    point1_id = pt1["id"]
    print(f"    OK → point_id={point1_id}\n")

    # --- Create point (site-only) ---
    print("[11] POST /points (site-only)")
    code, pt2 = _request(
        "POST",
        "/points",
        json_body={
            "site_id": site_id,
            "external_id": "OAT",
            "brick_type": "Outside_Air_Temperature_Sensor",
            "fdd_input": "oat",
        },
    )
    assert ok(code)
    point2_id = pt2["id"]
    print(f"    OK → point_id={point2_id}\n")

    # --- Get point ---
    print("[12] GET /points/{id}")
    code, got = _request("GET", f"/points/{point1_id}")
    assert ok(code)
    assert got["external_id"] == "SA-T"
    print("    OK\n")

    # --- List points (by site) ---
    print("[13] GET /points?site_id=...")
    code, pts = _request("GET", f"/points?site_id={site_id}")
    assert ok(code)
    assert len(pts) >= 2
    print(f"    OK ({len(pts)} points)\n")

    # --- List points (by equipment) ---
    print("[14] GET /points?equipment_id=...")
    code, pts = _request("GET", f"/points?equipment_id={equipment_id}")
    assert ok(code)
    assert any(p["id"] == point1_id for p in pts)
    print("    OK\n")

    # --- SPARQL: point labels for our site only (exclude BACnet graph labels) ---
    print("[14b] SPARQL: point labels for test site (TTL in sync)")
    pt_labels_site = _sparql_point_labels_for_site(test_site_name)
    assert (
        "SA-T" in pt_labels_site and "OAT" in pt_labels_site
    ), f"Expected SA-T, OAT in site points: {pt_labels_site}"
    print(f"    SPARQL result: {pt_labels_site}")
    print(f"    OK — {pt_labels_site}\n")

    # --- PATCH point ---
    print("[15] PATCH /points/{id}")
    code, patched = _request(
        "PATCH",
        f"/points/{point1_id}",
        json_body={"unit": "celsius"},
    )
    assert ok(code)
    assert patched["unit"] == "celsius"
    print("    OK\n")

    # --- Data model export (unified: BACnet + DB points; ready for LLM Brick tagging → PUT /data-model/import) ---
    print("[16] GET /data-model/export (unified dump; validate CRUD points and shape)")
    code, export = _request("GET", f"/data-model/export?site_id={site_id}")
    assert ok(code), f"GET /data-model/export failed: {code}"
    assert isinstance(export, list), "Export should be a list"
    # Rows from our CRUD: point_id set, external_id SA-T / OAT
    by_ext = {r.get("external_id"): r for r in export if isinstance(r, dict) and r.get("external_id")}
    assert "SA-T" in by_ext, f"Export should contain CRUD point SA-T; external_ids: {list(by_ext.keys())[:20]}"
    assert "OAT" in by_ext, f"Export should contain CRUD point OAT; external_ids: {list(by_ext.keys())[:20]}"
    for ext in ("SA-T", "OAT"):
        row = by_ext[ext]
        assert row.get("point_id"), f"CRUD point {ext} should have point_id in export"
        assert row.get("site_id") == site_id or row.get("site_name"), f"CRUD point {ext} should have site ref"
    # Shape: expect point_id, external_id, (site_id|site_name), optional bacnet_*, polling
    sample = export[0] if export else {}
    assert isinstance(sample, dict) and ("point_id" in sample or "external_id" in sample), (
        "Export rows should have point_id and/or external_id"
    )
    print(f"    OK ({len(export)} rows; CRUD points SA-T, OAT present with point_id/site). Ready for LLM tagging → PUT /data-model/import (see docs/modeling/ai_assisted_tagging and docs/appendix/technical_reference).\n")

    # --- Delete point 1 ---
    print("[17] DELETE /points/{id} (SA-T)")
    code, _ = _request("DELETE", f"/points/{point1_id}")
    assert ok(code)
    code, _ = _request("GET", f"/points/{point1_id}")
    assert code == 404
    print("    OK (verified 404)\n")

    # --- SPARQL: SA-T gone from our site's TTL (BACnet SA-T still in graph) ---
    print("[17b] SPARQL: SA-T removed from test site TTL")
    pt_labels_site = _sparql_point_labels_for_site(test_site_name)
    assert "SA-T" not in pt_labels_site, f"SA-T should be gone from site: {pt_labels_site}"
    assert "OAT" in pt_labels_site, f"OAT should remain: {pt_labels_site}"
    print(f"    SPARQL result: {pt_labels_site}")
    print(f"    OK — {pt_labels_site}\n")

    # --- Delete point 2 ---
    print("[18] DELETE /points/{id} (OAT)")
    code, _ = _request("DELETE", f"/points/{point2_id}")
    assert ok(code)
    code, _ = _request("GET", f"/points/{point2_id}")
    assert code == 404
    print("    OK (verified 404)\n")

    # --- SPARQL: no points left for our site (OAT and SA-T gone) ---
    print("[18b] SPARQL: point labels for test site after delete OAT")
    pt_labels_site = _sparql_point_labels_for_site(test_site_name)
    assert (
        "OAT" not in pt_labels_site and "SA-T" not in pt_labels_site
    ), f"Both points should be gone from site: {pt_labels_site}"
    print(f"    SPARQL result: {pt_labels_site}")
    print(f"    OK — {pt_labels_site}\n")

    # --- Delete equipment ---
    print("[19] DELETE /equipment/{id}")
    code, _ = _request("DELETE", f"/equipment/{equipment_id}")
    assert ok(code)
    code, _ = _request("GET", f"/equipment/{equipment_id}")
    assert code == 404
    print("    OK (verified 404)\n")

    # --- SPARQL: equipment gone from our site's TTL ---
    print("[19b] SPARQL: equipment labels for test site (test-ahu-1 gone)")
    eq_labels_site = _sparql_equipment_labels_for_site(test_site_name)
    assert "test-ahu-1" not in eq_labels_site, f"test-ahu-1 should be gone from site: {eq_labels_site}"
    print(f"    SPARQL result: {eq_labels_site}")
    print(f"    OK — {eq_labels_site}\n")

    # --- Re-add BACnet devices to graph (point_discovery_to_graph), then SPARQL ---
    if BACNET_URL:
        print(f"[19c] POST /bacnet/point_discovery_to_graph (re-add devices {list(BACNET_TEST_DEVICE_INSTANCES)} to graph)")
        for dev_inst in BACNET_TEST_DEVICE_INSTANCES:
            code, pdg2 = _request(
                "POST",
                "/bacnet/point_discovery_to_graph",
                json_body=_bacnet_body(
                    instance={"device_instance": dev_inst},
                    update_graph=True,
                    write_file=True,
                ),
                timeout=30.0,
            )
            assert ok(code), f"point_discovery_to_graph re-add ({dev_inst}) failed: {code} {pdg2}"
        print("    OK\n")
        print("[19d] SPARQL: bacnet:Device present again after re-add")
        dev_bindings2 = _sparql(
            "PREFIX bacnet: <http://data.ashrae.org/bacnet/2020#> SELECT ?dev WHERE { ?dev a bacnet:Device }"
        )
        assert len(dev_bindings2) >= len(BACNET_TEST_DEVICE_INSTANCES), (
            f"SPARQL: at least {len(BACNET_TEST_DEVICE_INSTANCES)} bacnet:Device after re-add, got {len(dev_bindings2)}"
        )
        print(f"    SPARQL result: {[b.get('dev') for b in dev_bindings2]}")
        print(f"    OK — {len(dev_bindings2)} bacnet:Device(s)\n")

    # --- Delete site ---
    print("[20] DELETE /sites/{id}")
    code, _ = _request("DELETE", f"/sites/{site_id}")
    assert ok(code)
    code, _ = _request("GET", f"/sites/{site_id}")
    assert code == 404
    print("    OK (verified 404)\n")

    # --- SPARQL: site gone from TTL ---
    print("[20b] SPARQL: site labels (test site gone)")
    site_labels = _sparql_site_labels()
    assert (
        test_site_name not in site_labels
    ), f"{test_site_name!r} should be gone: {site_labels}"
    print(f"    SPARQL result: {site_labels}")
    print(f"    OK — {site_labels}\n")

    # --- Delete demo-import site created this run (avoid accumulation of demo-import-* sites) ---
    print("[20c] DELETE /sites/{id} (demo-import site from [4g])")
    code, _ = _request("DELETE", f"/sites/{demo_site_id}")
    assert ok(code), f"DELETE demo-import site failed: {code}"
    code, _ = _request("GET", f"/sites/{demo_site_id}")
    assert code == 404
    print("    OK (verified 404)\n")

    # --- Download (may 404 if no timeseries) ---
    print("[21] GET /download/csv (smoke test)")
    code, body = _request(
        "GET",
        "/download/csv?site_id=default&start_date=2024-01-01&end_date=2024-01-31&format=wide",
    )
    assert code in (200, 404), f"Unexpected {code}"
    if code == 200 and isinstance(body, str):
        assert "timestamp" in body.lower() or "," in body  # CSV with header
    print(f"    OK (status {code})\n")

    print("[22] POST /download/csv (smoke test)")
    code, _ = _request(
        "POST",
        "/download/csv",
        json_body={
            "site_id": "default",
            "start_date": "2024-01-01",
            "end_date": "2024-01-31",
            "format": "wide",
        },
    )
    assert code in (200, 404), f"Unexpected {code}"
    print(f"    OK (status {code})\n")

    # --- Faults export (MSI/cloud) ---
    print("[23] GET /download/faults?format=json (smoke test)")
    code, data = _request(
        "GET",
        "/download/faults?start_date=2024-01-01&end_date=2024-01-31&format=json",
    )
    assert code == 200, f"Unexpected {code}"
    assert isinstance(data, dict) and "faults" in data and "count" in data
    print(f"    OK (faults={data['count']})\n")

    print("[24] GET /download/faults?format=csv (smoke test)")
    code, body = _request(
        "GET",
        "/download/faults?start_date=2024-01-01&end_date=2024-01-31&format=csv",
    )
    assert code == 200, f"Unexpected {code}"
    # Empty faults = BOM only or header-only CSV (no ts/site_id); non-empty has timestamp, site_id, commas
    if isinstance(body, str) and len(body.strip()) > 10:
        assert "ts" in body or "site_id" in body or "timestamp" in body or "," in body
    print("    OK\n")

    # --- Verify data model: DemoSite has many BACnet points with polling=true (scraper will poll them) ---
    print("[25] GET /points?site_id=<DemoSite> — verify many BACnet points with polling=true (data flowing via data model)")
    code, points_list = _request("GET", f"/points?site_id={demo_site_id_full}")
    assert ok(code), f"GET /points failed: {code}"
    assert isinstance(points_list, list), f"GET /points did not return a list: {type(points_list)}"
    bacnet_polling = [p for p in points_list if isinstance(p, dict) and p.get("bacnet_device_id") and p.get("polling")]
    min_bacnet_polling = 15
    assert len(bacnet_polling) >= min_bacnet_polling, (
        f"Expected at least {min_bacnet_polling} BACnet points with polling=true for DemoSite (full LLM payload); got {len(bacnet_polling)}. "
        f"Points: {[(p.get('external_id'), p.get('object_identifier'), p.get('polling')) for p in points_list if isinstance(p, dict) and p.get('bacnet_device_id')][:20]}"
    )
    devices = {p.get("bacnet_device_id") for p in bacnet_polling if p.get("bacnet_device_id")}
    for p in bacnet_polling[:5]:
        print(f"    {p.get('external_id', '')} {p.get('object_identifier', '')} dev={p.get('bacnet_device_id')} polling={p.get('polling')}")
    print(f"    OK — {len(bacnet_polling)} BACnet point(s) with polling=true across devices {sorted(devices)}; BACnet scraper will poll these.\n")

    # --- [25b] SPARQL count ofdd:polling true (TTL) and match to API/scraper count ---
    print("[25b] SPARQL (CRUD): count points with ofdd:polling true; must match scraper load and Grafana dropdowns")
    code, _ = _request("GET", "/data-model/ttl?save=true")
    assert ok(code), "GET /data-model/ttl?save=true failed"
    q_polling_count = """
    PREFIX ofdd: <http://openfdd.local/ontology#>
    SELECT (COUNT(?pt) AS ?n) WHERE { ?pt ofdd:polling true . }
    """
    bindings = _sparql(q_polling_count)
    assert bindings, "SPARQL polling count returned no bindings"
    n_val = bindings[0].get("n")
    sparql_n = int(str(n_val or "0").split("^")[0].strip())
    code, all_points = _request("GET", "/points")
    assert ok(code), f"GET /points failed: {code}"
    api_bacnet_polling = [p for p in (all_points or []) if isinstance(p, dict) and p.get("bacnet_device_id") and p.get("object_identifier") and p.get("polling")]
    api_n = len(api_bacnet_polling)
    min_expected = 17
    assert sparql_n >= min_expected, (
        f"SPARQL ofdd:polling true count {sparql_n} < {min_expected}; TTL should have many points from demo_site_llm_payload.json"
    )
    assert api_n >= min_expected, (
        f"API BACnet+polling count {api_n} < {min_expected}; scraper and Grafana need points in DB (DemoSite + TestBenchSite)"
    )
    # SPARQL counts all points with ofdd:polling true (Brick); API count is only BACnet points. So SPARQL >= api_n
    # when there are non-BACnet points with polling true (e.g. from other sites or previous runs).
    assert sparql_n >= api_n, (
        f"SPARQL ofdd:polling true ({sparql_n}) < API bacnet+polling ({api_n}); TTL should have at least the BACnet set"
    )
    print(f"    SPARQL ofdd:polling true = {sparql_n}; API bacnet+polling = {api_n}. Scraper load and Grafana dropdowns = {api_n} points.\n")

    # --- [26] Last BACnet scrape data (timeseries via CRUD/download API) before exit ---
    print("[26] GET /download/csv — last BACnet scrape data (timeseries sample)")
    end_d = date.today()
    start_d = end_d - timedelta(days=7)
    code, csv_body = _request(
        "GET",
        f"/download/csv?site_id={demo_site_id_full}&start_date={start_d}&end_date={end_d}&format=wide",
    )
    if code == 200 and isinstance(csv_body, str) and csv_body.strip():
        lines = csv_body.strip().splitlines()
        sample = lines[:20] if len(lines) > 20 else lines
        print(f"    Timeseries rows (last 7 days): {len(lines)} line(s); sample below:")
        for line in sample:
            print(f"      {line[:120]}{'...' if len(line) > 120 else ''}")
        print(f"    OK — last BACnet scrape data shown above.\n")
    else:
        print(f"    No timeseries yet for DemoSite (status={code}); scraper may not have run or diy-bacnet unreachable. See note below.\n")

    # --- [26b] Optional: wait until N BACnet scrapes have run (poll GET /download/csv until distinct timestamps >= N) ---
    if WAIT_SCRAPES >= 1:
        # Timeout must allow N scrapes at interval_min (e.g. 10 scrapes at 1 min = 10+ min)
        timeout_sec = max(
            2 * SCRAPE_INTERVAL_MIN * 60 + 120,
            WAIT_SCRAPES * SCRAPE_INTERVAL_MIN * 60 + 120,
        )
        print(f"[26b] Wait until {WAIT_SCRAPES} BACnet scrape(s) have run (scrape_interval_min={SCRAPE_INTERVAL_MIN}, timeout ~{timeout_sec // 60} min)")
        end_d = date.today()
        start_d = end_d - timedelta(days=1)
        poll_interval_sec = 20
        deadline = time.monotonic() + timeout_sec
        distinct_ts = 0
        while time.monotonic() < deadline:
            code, csv_body = _request(
                "GET",
                f"/download/csv?site_id={demo_site_id_full}&start_date={start_d}&end_date={end_d}&format=wide",
            )
            if code == 200 and isinstance(csv_body, str) and csv_body.strip():
                lines = csv_body.strip().splitlines()
                if len(lines) >= 2:
                    reader = csv.reader(io.StringIO(csv_body))
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
                    distinct_ts = len(seen)
                    if distinct_ts >= WAIT_SCRAPES:
                        print(f"    OK — {distinct_ts} distinct scrape timestamp(s) seen; {WAIT_SCRAPES}+ scrapes done.\n")
                        break
            elapsed = int(time.monotonic() - (deadline - timeout_sec))
            print(f"    ... waiting for scrapes ({distinct_ts} distinct ts so far, {elapsed}s elapsed)")
            time.sleep(poll_interval_sec)
        else:
            print(f"    WARNING — timeout after {timeout_sec}s; scrapes may not have run (check OFDD_BACNET_SCRAPE_INTERVAL_MIN and diy-bacnet reachability).\n")
    else:
        print("[26b] Skip (--wait-scrapes 0, default). Use --wait-scrapes 2 to wait for BACnet scrapes.\n")

    # --- [27] Leave only one site: delete DemoSite so GET /data-model/check returns sites=1 (TestBenchSite only) ---
    print("[27] DELETE /sites/{id} (DemoSite) — TestBenchSite must remain (data-model/check); other sites allowed")
    code, _ = _request("DELETE", f"/sites/{demo_site_id_full}")
    assert ok(code), f"DELETE DemoSite failed: {code}"
    code, _ = _request("GET", f"/sites/{demo_site_id_full}")
    assert code == 404, f"DemoSite should be gone: {code}"
    # GET /data-model/check syncs Brick from DB then counts. Require TestBenchSite present; allow other sites (e.g. BensOffice).
    code, check = _request("GET", "/data-model/check")
    assert ok(code), f"GET /data-model/check failed: {code}"
    sites_count = (check or {}).get("sites", 0)
    code, sites_list = _request("GET", "/sites")
    names = [s.get("name") for s in (sites_list or []) if isinstance(s, dict)]
    if sites_count < 1 or TESTBENCH_SITE_NAME not in names:
        assert False, (
            f"After [27] expected TestBenchSite present; GET /data-model/check sites={sites_count}, site names: {names}"
        )
    print(f"    OK — DemoSite deleted; TestBenchSite present (sites={sites_count}: {names}).\n")

    print("=== All features passed ===\n")
    print(
        "  Health, BACnet (server_hello, whois_range, point_discovery_to_graph),"
    )
    print(
        "  CRUD (sites, equipment, points), data model (TTL, export, SPARQL), merged BACnet+BRICK graph,"
    )
    print("  PUT /data-model/import (points + equipment feeds/fed_by), SPARQL feeds, polling=true (diy-bacnet ready),")
    print("  download (CSV, faults), lifecycle (create → delete → SPARQL; BACnet via point_discovery_to_graph).")
    print("  config/data_model.ttl is updated on every CRUD and serialize.")
    print("  GET /data-model/export = unified dump (BACnet + DB points); ready to try LLM Brick tagging (docs/modeling/ai_assisted_tagging, docs/appendix/technical_reference) → PUT /data-model/import.")
    print("  AI step: In production you use GET /data-model/export → LLM or human tags (brick_type, rule_input, polling) → PUT /data-model/import. See docs/modeling/ai_assisted_tagging.md and AGENTS.md.")
    print("  Note: After [27] TestBenchSite remains (DemoSite deleted); GET /data-model/check may show sites>=1 if e.g. BensOffice exists. Grafana BACnet dropdowns then show only 2 points (TestBenchSite: SA-T, ZoneTemp). To see 24 points in Grafana, stop before [27] or skip the DemoSite delete (docs/howto/grafana_cookbook). Scrape interval: set OFDD_BACNET_SCRAPE_INTERVAL_MIN=1 in platform/.env and 'cd platform && docker compose up -d' (no rebuild). If 'diy-bacnet-server unreachable': ensure bacnet-server is running and OFDD_BACNET_SERVER_URL. Re-run: ./scripts/bootstrap.sh --reset-data && python tools/graph_and_crud_test.py\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Open-FDD CRUD + SPARQL e2e test. Hits Open-FDD API only; API proxies to diy-bacnet when needed."
    )
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="Open-FDD API base URL — only server the test calls (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--bacnet-url",
        default="http://localhost:8080",
        help="Gateway URL sent in request body so API (e.g. in Docker) can reach BACnet. When base-url is localhost, default becomes host.docker.internal:8080 for container-to-host.",
    )
    parser.add_argument(
        "--skip-bacnet",
        action="store_true",
        help="Skip BACnet proxy steps (server_hello, whois_range, point_discovery_to_graph)",
    )
    parser.add_argument(
        "--bacnet-device-instance",
        type=int,
        default=3456789,
        metavar="ID",
        help="BACnet device instance for point_discovery_to_graph (0-4194303). Default: 3456789.",
    )
    parser.add_argument(
        "--wait-scrapes",
        type=int,
        default=0,
        metavar="N",
        help="Wait until N BACnet scrapes have run before exiting (0 = skip). Default: 0.",
    )
    parser.add_argument(
        "--scrape-interval-min",
        type=int,
        default=5,
        metavar="M",
        help="Assumed scraper interval in minutes (for wait timeout). Must match OFDD_BACNET_SCRAPE_INTERVAL_MIN. Default: 5.",
    )
    args = parser.parse_args()

    global BASE_URL, BACNET_URL, BACNET_DEVICE_INSTANCE, WAIT_SCRAPES, SCRAPE_INTERVAL_MIN
    BASE_URL = (os.environ.get("BASE_URL") or args.base_url).strip().rstrip("/")
    if args.skip_bacnet:
        BACNET_URL = ""
    else:
        raw = (os.environ.get("BACNET_URL") or args.bacnet_url).strip().rstrip("/")
        # When testing API at localhost, API is usually in Docker; from container, use host to reach BACnet
        if raw == "http://localhost:8080" and ("localhost" in BASE_URL or "127.0.0.1" in BASE_URL):
            BACNET_URL = BACNET_URL_FOR_API_DEFAULT
        else:
            BACNET_URL = raw
    BACNET_DEVICE_INSTANCE = int(
        os.environ.get("BACNET_DEVICE_INSTANCE", str(args.bacnet_device_instance))
    )
    WAIT_SCRAPES = int(os.environ.get("OFDD_WAIT_SCRAPES", str(args.wait_scrapes)))
    SCRAPE_INTERVAL_MIN = int(
        os.environ.get("OFDD_BACNET_SCRAPE_INTERVAL_MIN", str(args.scrape_interval_min))
    )

    run()


if __name__ == "__main__":
    main()
