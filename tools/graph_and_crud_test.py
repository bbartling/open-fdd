#!/usr/bin/env python3
# If run with bash, re-exec with Python (e.g. "bash tools/test_crud_api.py" still works)
""":'
exec python3 "$0" "$@"
"""

"""
End-to-end CRUD API test: hits Open-FDD API only (no direct calls to diy-bacnet-server).

All requests go to the Open-FDD API (--base-url). For BACnet, the test uses the API’s
default gateway URL (omit url in body when API runs in Docker) or --bacnet-url.
Flow: test → Open-FDD API → (API proxies to) diy-bacnet.

Features covered:
  - Health: GET /health
  - BACnet: server_hello, whois_range, point_discovery_to_graph.
  - CRUD: sites, equipment, points; data model TTL, export, SPARQL; graph serialize.
  - SPARQL-only checks; re-add device via point_discovery_to_graph. Download: CSV, faults.

Usage:
# Default device 3456789
python tools/graph_and_crud_test.py

# Another device
python tools/graph_and_crud_test.py --bacnet-device-instance 3456788

# With BACnet URL and device
python tools/graph_and_crud_test.py --bacnet-url http://192.168.204.16:8080 --bacnet-device-instance 3456789

# Env override
BACNET_DEVICE_INSTANCE=999999 python tools/graph_and_crud_test.py
"""

import argparse
import json
import os
import sys
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
BACNET_DEVICE_INSTANCE = 3456789  # default; override with --bacnet-device-instance


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


def run():
    print(
        f"\n=== Open-FDD CRUD API Test (CRUD + RDF + SPARQL) ===\nBase URL: {BASE_URL}\n"
    )
    if BACNET_URL:
        print(f"BACNET_URL: {BACNET_URL} (point_discovery_to_graph, device_instance={BACNET_DEVICE_INSTANCE})\n")

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

    # --- BACnet proxy (when gateway URL set) ---
    if BACNET_URL:
        print("[1a] POST /bacnet/server_hello (gateway reachable)")
        code, sh = _request("POST", "/bacnet/server_hello", json_body={})
        assert ok(code), f"server_hello failed: {code} {sh}"
        body = sh.get("body") if isinstance(sh, dict) else sh
        res = body.get("result") if isinstance(body, dict) else body
        assert res and (res.get("message") or "message" in str(res).lower())
        print("    OK\n")

        print("[1a2] POST /bacnet/whois_range (discover devices)")
        code, wr = _request(
            "POST",
            "/bacnet/whois_range",
            json_body={"request": {"start_instance": 1, "end_instance": 3456800}},
            timeout=15.0,
        )
        assert ok(code), f"whois_range failed: {code} {wr}"
        _body = wr.get("body") if isinstance(wr, dict) else wr
        _res = _body.get("result") if isinstance(_body, dict) else {}
        _data = (_res.get("data") or _res) if isinstance(_res, dict) else {}
        devs = _data.get("devices") or []
        print(f"    OK — {len(devs)} device(s)\n")

        # Graph from point_discovery: clean BACnet RDF into in-memory graph
        print(f"[1a3] POST /bacnet/point_discovery_to_graph (device {BACNET_DEVICE_INSTANCE} → in-memory graph)")
        code, pdg = _request(
            "POST",
            "/bacnet/point_discovery_to_graph",
            json_body={
                "instance": {"device_instance": BACNET_DEVICE_INSTANCE},
                "update_graph": True,
                "write_file": True,
            },
            timeout=30.0,
        )
        assert ok(code), f"point_discovery_to_graph failed: {code} {pdg}"
        if pdg.get("graph_error"):
            print(f"    WARN — graph_error: {pdg['graph_error']}\n")
        else:
            print("    OK\n")
        # Grab a few object names from discovery to assert in SPARQL (device-agnostic)
        _body = pdg.get("body") if isinstance(pdg, dict) else pdg
        _res = _body.get("result") if isinstance(_body, dict) else {}
        _data = (_res.get("data") or _res) if isinstance(_res, dict) else {}
        _objs = _data.get("objects") or []
        _sample_names = []
        for _o in _objs[:10]:  # up to 10 from discovery
            if isinstance(_o, dict):
                _n = (_o.get("object_name") or _o.get("name") or "").strip()
                if _n and _n not in _sample_names:
                    _sample_names.append(_n)
                    if len(_sample_names) >= 5:
                        break
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
        assert len(dev_bindings) >= 1, "SPARQL: at least one bacnet:Device"
        n_objs = 0
        if obj_bindings and obj_bindings[0].get("n"):
            try:
                n_objs = int(obj_bindings[0]["n"].strip())
            except (ValueError, TypeError):
                pass
        # For this device instance, get object names from graph and assert discovery sample is there
        if _sample_names:
            inst = BACNET_DEVICE_INSTANCE
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
    print(f"    OK — {labels}\n")

    # --- Data model TTL (SPARQL already validated site/points; no grep on TTL) ---
    print("[4c] GET /data-model/ttl (smoke: 200, string)")
    code, ttl_body = _request("GET", "/data-model/ttl")
    assert ok(code), f"GET /data-model/ttl failed: {code}"
    assert isinstance(ttl_body, str), "TTL response should be string"
    assert len(ttl_body) > 0, "TTL non-empty"
    print(f"    OK — TTL length {len(ttl_body)} (site/points validated via SPARQL in [4b])\n")

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

    # --- Data model export ---
    print("[16] GET /data-model/export")
    code, export = _request("GET", f"/data-model/export?site_id={site_id}")
    assert ok(code)
    assert len(export) >= 2
    print(f"    OK ({len(export)} points in export)\n")

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
    print(f"    OK — {eq_labels_site}\n")

    # --- Re-add BACnet device to graph (point_discovery_to_graph), then SPARQL (no gateway RDF) ---
    if BACNET_URL:
        print(f"[19c] POST /bacnet/point_discovery_to_graph (re-add device {BACNET_DEVICE_INSTANCE} to graph)")
        code, pdg2 = _request(
            "POST",
            "/bacnet/point_discovery_to_graph",
            json_body={
                "instance": {"device_instance": BACNET_DEVICE_INSTANCE},
                "update_graph": True,
                "write_file": True,
            },
            timeout=30.0,
        )
        assert ok(code), f"point_discovery_to_graph re-add failed: {code} {pdg2}"
        print("    OK\n")
        print("[19d] SPARQL: bacnet:Device present again after re-add")
        dev_bindings2 = _sparql(
            "PREFIX bacnet: <http://data.ashrae.org/bacnet/2020#> SELECT ?dev WHERE { ?dev a bacnet:Device }"
        )
        assert len(dev_bindings2) >= 1, "SPARQL: bacnet:Device back in graph"
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
    print(f"    OK — {site_labels}\n")

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

    print("=== All features passed ===\n")
    print(
        "  Health, BACnet (server_hello, whois_range, point_discovery_to_graph),"
    )
    print(
        "  CRUD (sites, equipment, points), data model (TTL, export, SPARQL), merged BACnet+BRICK graph,"
    )
    print("  download (CSV, faults), lifecycle (create → delete → SPARQL; BACnet via point_discovery_to_graph).")
    print("  config/brick_model.ttl is updated on every CRUD and serialize.\n")


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
        help="URL sent to Open-FDD so it can proxy to diy-bacnet-server (default: localhost:8080 for Docker)",
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
    args = parser.parse_args()

    global BASE_URL, BACNET_URL, BACNET_DEVICE_INSTANCE
    BASE_URL = (os.environ.get("BASE_URL") or args.base_url).strip().rstrip("/")
    if args.skip_bacnet:
        BACNET_URL = ""
    else:
        BACNET_URL = (
            (os.environ.get("BACNET_URL") or args.bacnet_url).strip().rstrip("/")
        )
    BACNET_DEVICE_INSTANCE = int(
        os.environ.get("BACNET_DEVICE_INSTANCE", str(args.bacnet_device_instance))
    )

    run()


if __name__ == "__main__":
    main()
