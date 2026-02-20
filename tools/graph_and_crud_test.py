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

API coverage (OpenAPI paths exercised):
  - /health
  - /sites: list, create, get, patch, delete (demo-import site deleted at [20c])
  - /equipment: list, create, get, patch, delete
  - /points: list (by site, by equipment), create, get, patch, delete
  - /data-model: serialize, ttl, export, import (points + equipment feeds), sparql
  - /bacnet: server_hello, whois_range, point_discovery_to_graph
  - /download/csv (GET, POST), /download/faults (GET json, csv)
Not in this script: GET /bacnet/gateways, /data-model/check, /data-model/reset, /data-model/sparql/upload, /analytics/*, /run-fdd/*.

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

# Testbench devices to discover and validate in graph/TTL (when BACnet enabled)
BACNET_TEST_DEVICE_INSTANCES = (3456789, 3456790)
# Testbench site + equipment (BensOffice, BensFakeAhu, BensFakeVavBox) — created/validated, not deleted
BENSOFFICE_SITE_NAME = "BensOffice"
BENS_FAKE_AHU_NAME = "BensFakeAhu"
BENS_FAKE_VAV_NAME = "BensFakeVavBox"


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
        f"\n=== Open-FDD CRUD API Test (CRUD + RDF + SPARQL) ===\nBase URL: {BASE_URL}\n"
    )
    if BACNET_URL:
        print(f"BACNET_URL: {BACNET_URL} (point_discovery_to_graph, device_instances={list(BACNET_TEST_DEVICE_INSTANCES)})\n")

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

        # Graph from point_discovery: clean BACnet RDF into in-memory graph (both test devices)
        print(f"[1a3] POST /bacnet/point_discovery_to_graph (devices {list(BACNET_TEST_DEVICE_INSTANCES)} → in-memory graph)")
        _sample_names = []
        for dev_inst in BACNET_TEST_DEVICE_INSTANCES:
            code, pdg = _request(
                "POST",
                "/bacnet/point_discovery_to_graph",
                json_body={
                    "instance": {"device_instance": dev_inst},
                    "update_graph": True,
                    "write_file": True,
                },
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

    # --- BensOffice testbench: ensure site + BensFakeAhu / BensFakeVavBox, validate in graph and TTL ---
    print(f"[4d] BensOffice testbench: ensure site {BENSOFFICE_SITE_NAME!r} and equipment {BENS_FAKE_AHU_NAME!r}, {BENS_FAKE_VAV_NAME!r}")
    code, sites_list = _request("GET", "/sites")
    assert ok(code), f"GET /sites failed: {code}"
    bens_site = next((s for s in sites_list if s.get("name") == BENSOFFICE_SITE_NAME), None)
    if bens_site is None:
        code, bens_site = _request(
            "POST",
            "/sites",
            json_body={"name": BENSOFFICE_SITE_NAME, "description": "BensTestBench"},
        )
        assert ok(code), f"POST /sites BensOffice failed: {code} {bens_site}"
    bens_site_id = bens_site["id"]
    # Create equipment if not already present (by name under this site)
    code, eq_list = _request("GET", f"/equipment?site_id={bens_site_id}")
    assert ok(code)
    existing_names = {e.get("name") for e in eq_list if e.get("name")}
    if BENS_FAKE_AHU_NAME not in existing_names:
        code, _ = _request(
            "POST",
            "/equipment",
            json_body={
                "site_id": bens_site_id,
                "name": BENS_FAKE_AHU_NAME,
                "description": "Testbench AHU",
                "equipment_type": "Air_Handling_Unit",
            },
        )
        assert ok(code), f"POST /equipment {BENS_FAKE_AHU_NAME} failed: {code}"
    if BENS_FAKE_VAV_NAME not in existing_names:
        code, _ = _request(
            "POST",
            "/equipment",
            json_body={
                "site_id": bens_site_id,
                "name": BENS_FAKE_VAV_NAME,
                "description": "Testbench VAV",
                "equipment_type": "VAV",
            },
        )
        assert ok(code), f"POST /equipment {BENS_FAKE_VAV_NAME} failed: {code}"
    print(f"    OK — site_id={bens_site_id}\n")

    print("[4e] SPARQL: BensOffice site and testbench equipment in graph")
    site_labels = _sparql_site_labels()
    assert BENSOFFICE_SITE_NAME in site_labels, f"Expected {BENSOFFICE_SITE_NAME!r} in site labels: {site_labels}"
    eq_labels = _sparql_equipment_labels_for_site(BENSOFFICE_SITE_NAME)
    for name in (BENS_FAKE_AHU_NAME, BENS_FAKE_VAV_NAME):
        assert name in eq_labels, f"Expected {name!r} in equipment labels for BensOffice: {eq_labels}"
    print(f"    SPARQL result (site labels): {site_labels}")
    print(f"    SPARQL result (equipment for BensOffice): {eq_labels}")
    print(f"    OK — site {BENSOFFICE_SITE_NAME!r}, equipment {eq_labels}\n")

    print("[4f] GET /data-model/ttl?save=true (validate BensOffice + testbench equipment in TTL)")
    code, ttl_body_bens = _request("GET", "/data-model/ttl?save=true")
    assert code == 200, f"GET /data-model/ttl failed: {code}"
    assert isinstance(ttl_body_bens, str), "TTL response should be string"
    assert BENSOFFICE_SITE_NAME in ttl_body_bens, f"TTL should contain site label {BENSOFFICE_SITE_NAME!r}"
    assert BENS_FAKE_AHU_NAME in ttl_body_bens, f"TTL should contain equipment {BENS_FAKE_AHU_NAME!r}"
    assert BENS_FAKE_VAV_NAME in ttl_body_bens, f"TTL should contain equipment {BENS_FAKE_VAV_NAME!r}"
    print(f"    OK — TTL contains {BENSOFFICE_SITE_NAME!r}, {BENS_FAKE_AHU_NAME!r}, {BENS_FAKE_VAV_NAME!r}\n")

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
    print(f"    OK ({len(export)} rows; CRUD points SA-T, OAT present with point_id/site). Ready for LLM tagging → PUT /data-model/import (see MONOREPO_PLAN.md).\n")

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
                json_body={
                    "instance": {"device_instance": dev_inst},
                    "update_graph": True,
                    "write_file": True,
                },
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

    print("=== All features passed ===\n")
    print(
        "  Health, BACnet (server_hello, whois_range, point_discovery_to_graph),"
    )
    print(
        "  CRUD (sites, equipment, points), data model (TTL, export, SPARQL), merged BACnet+BRICK graph,"
    )
    print("  PUT /data-model/import (points + equipment feeds/fed_by), SPARQL feeds, polling=true (diy-bacnet ready),")
    print("  download (CSV, faults), lifecycle (create → delete → SPARQL; BACnet via point_discovery_to_graph).")
    print("  config/brick_model.ttl is updated on every CRUD and serialize.")
    print("  GET /data-model/export = unified dump (BACnet + DB points); ready to try LLM Brick tagging (MONOREPO_PLAN.md § Prompt to the LLM) → PUT /data-model/import.")
    print("  Note: BensOffice is left in place. The demo-import site created in [4g] is deleted in [20c] to avoid accumulation.\n")


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
