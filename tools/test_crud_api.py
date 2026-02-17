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
  - BACnet proxy: server_hello, whois_range, point_discovery, discovery-to-rdf (store TTL + optional import_into_data_model)
  - CRUD: sites, equipment, points (create, get, list, PATCH, delete)
  - Data model: GET /data-model/ttl, GET /data-model/export, POST /data-model/sparql (TTL in sync after CRUD and import)
  - SPARQL: site/equipment/point labels, BACnet devices in merged graph (unified brick_model.ttl)
  - Download: CSV timeseries, faults (JSON/CSV)

  - Lifecycle: create site → (optional) BACnet discovery-to-rdf with import → CRUD points/equipment → delete BACnet points/equipment → delete site; SPARQL checks at each stage

Usage:
  python3 tools/test_crud_api.py
  python3 tools/test_crud_api.py --skip-bacnet   # skip BACnet proxy and discovery-to-rdf
  python3 tools/test_crud_api.py --base-url http://localhost:8000 --bacnet-url http://localhost:8080
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


def _sparql_equipment_labels() -> list[str]:
    q = """
    PREFIX brick: <https://brickschema.org/schema/Brick#>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    SELECT ?eq_label WHERE { ?eq brick:isPartOf ?site . ?eq rdfs:label ?eq_label }
    """
    rows = _sparql(q)
    return [r.get("eq_label") or "" for r in rows if r.get("eq_label")]


def run():
    print(
        f"\n=== Open-FDD CRUD API Test (CRUD + RDF + SPARQL) ===\nBase URL: {BASE_URL}\n"
    )
    if BACNET_URL:
        print(f"BACNET_URL: {BACNET_URL} (discovery-to-rdf enabled)\n")

    # --- Health ---
    print("[1] GET /health")
    code, data = _request("GET", "/health")
    assert ok(code), f"Expected 200, got {code}"
    assert data.get("status") == "ok"
    print("    OK\n")

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

        print(
            "[1b] POST /bacnet/discovery-to-rdf (Who-Is + deep scan → TTL stored & merged)"
        )
        code, data = _request(
            "POST",
            "/bacnet/discovery-to-rdf",
            json_body={"request": {"start_instance": 1, "end_instance": 3456800}},
            timeout=120.0,
        )
        assert ok(code), f"discovery-to-rdf failed: {code} {data}"
        body = data.get("body") if isinstance(data, dict) else data
        result = body.get("result") if isinstance(body, dict) else None
        if isinstance(result, dict):
            assert "ttl" in result and "summary" in result
            summary = result["summary"]
            print(
                f"    OK — devices={summary.get('devices', 0)}, objects={summary.get('objects', 0)}\n"
            )
        else:
            print("    OK (gateway response)\n")
    else:
        print("[1a] SKIP BACnet proxy (use --bacnet-url or omit --skip-bacnet)\n")
        print("[1b] SKIP /bacnet/discovery-to-rdf\n")

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

    # --- BACnet: discovery-to-rdf with import_into_data_model → validate in BRICK (only when BACNET_URL set) ---
    bacnet_equipment_id = None
    bacnet_point_ids: list[dict] = []  # [{"id": uuid, "external_id": str}, ...]
    DEVICE_3456789 = 3456789

    if BACNET_URL:
        print(
            "[2b] POST /bacnet/point_discovery (get expected point labels for assertion)"
        )
        code, pd_resp = _request(
            "POST",
            "/bacnet/point_discovery",
            json_body={"instance": {"device_instance": DEVICE_3456789}},
            timeout=30.0,
        )
        assert ok(code), f"point_discovery failed: {code} {pd_resp}"
        _body = pd_resp.get("body") if isinstance(pd_resp, dict) else pd_resp
        _res = _body.get("result") if isinstance(_body, dict) else {}
        if (
            not _res
            and isinstance(_body, dict)
            and ("data" in _body or "success" in _body)
        ):
            _res = _body
        _data = _res.get("data") or {} if isinstance(_res, dict) else {}
        _objs = _data.get("objects") or _res.get("objects") or []
        expected_bacnet_point_labels = []
        for _o in _objs:
            if isinstance(_o, dict):
                _name = (
                    _o.get("object_name")
                    or _o.get("name")
                    or _o.get("object_identifier")
                    or ""
                ).strip()
                if _name:
                    expected_bacnet_point_labels.append(_name)
        print("    OK\n")

        # Ensure no legacy TTL file before discovery-to-rdf (API must write only to brick_model.ttl)
        legacy_ttl = Path("config/bacnet_scan.ttl")
        if legacy_ttl.exists():
            legacy_ttl.unlink()
        print(
            "[2c] POST /bacnet/discovery-to-rdf (import_into_data_model=true → site/equipment/points + brick_model.ttl)"
        )
        code, rdf_resp = _request(
            "POST",
            "/bacnet/discovery-to-rdf",
            json_body={
                "request": {"start_instance": 1, "end_instance": 3456800},
                "import_into_data_model": True,
                "site_id": site_id,
                "create_site": False,
            },
            timeout=120.0,
        )
        assert ok(code), f"discovery-to-rdf failed: {code} {rdf_resp}"
        if legacy_ttl.exists():
            try:
                legacy_ttl.unlink()
            except OSError:
                pass
            print(
                f"\n  FAIL: {BASE_URL} recreated config/bacnet_scan.ttl. The API is running OLD code.\n"
                "  Restart the API so it uses the unified TTL (only brick_model.ttl):\n"
                "    Docker: docker compose up -d --build api\n"
                "    Local:  stop uvicorn and start it again from this repo.\n"
            )
            sys.exit(1)
        imp = rdf_resp.get("import_result") or {}
        points_created = imp.get("points_created", 0)
        if rdf_resp.get("import_error"):
            print(f"    WARN — import_error: {rdf_resp['import_error']}\n")
        else:
            print(f"    OK — points_created={points_created}\n")

        # Resolve equipment and point IDs only for later CRUD deletes (not for data model assertion)
        code, eq_list = _request("GET", f"/equipment?site_id={site_id}")
        assert ok(code)
        for eq in eq_list or []:
            if eq.get("name") == f"BACnet device {DEVICE_3456789}":
                bacnet_equipment_id = eq["id"]
                break
        if bacnet_equipment_id:
            code, pt_list = _request(
                "GET", f"/points?equipment_id={bacnet_equipment_id}"
            )
            assert ok(code)
            bacnet_point_ids = [
                {
                    "id": p["id"],
                    "external_id": p.get("external_id")
                    or p.get("object_identifier")
                    or "",
                }
                for p in (pt_list or [])
            ]

        # [2d]–[2f] only when import created equipment (points_created > 0 or bacnet_equipment_id found)
        if not bacnet_equipment_id:
            print(
                "[2d] SKIP SPARQL BACnet assertions (import created 0 points; TTL parser may not match gateway format)\n"
            )
            if points_created == 0 and not rdf_resp.get("import_error"):
                print(
                    "    Hint: check parse_bacnet_ttl_to_discovery() and bacnet TTL namespace (e.g. bacnet:device-instance, bacnet:contains).\n"
                )
        else:
            # [2d] Data model validation only via SPARQL (no assertion from GET response)
            print("[2d] SPARQL: BACnet device and points in BRICK")
            eq_labels = _sparql_equipment_labels()
            expected_eq_name = f"BACnet device {DEVICE_3456789}"
            assert (
                expected_eq_name in eq_labels
            ), f"Expected {expected_eq_name!r} in equipment labels: {eq_labels}"
            pt_labels = _sparql_point_labels()
            for expected_label in expected_bacnet_point_labels:
                assert (
                    expected_label in pt_labels
                ), f"Expected point {expected_label!r} in SPARQL labels: {pt_labels}"
            print(
                f"    OK — equipment {expected_eq_name!r}, {len(expected_bacnet_point_labels)} points in model (SPARQL)\n"
            )

            # [2e] SPARQL: merged graph contains BACnet RDF (unified brick_model.ttl = Brick + BACnet)
            print("[2e] SPARQL: bacnet:Device in merged graph (BACnet RDF + BRICK)")
            bacnet_q = """
            PREFIX bacnet: <http://data.ashrae.org/bacnet/2020#>
            SELECT ?dev WHERE { ?dev a bacnet:Device }
            """
            bacnet_bindings = _sparql(bacnet_q)
            assert (
                len(bacnet_bindings) >= 1
            ), "Expected at least one bacnet:Device in merged graph"
            print(f"    OK — {len(bacnet_bindings)} bacnet:Device(s) in merged graph\n")

            # [2f] GET /points: BACnet points have bacnet_device_id and object_identifier
            if bacnet_point_ids:
                code, one_pt = _request("GET", f"/points/{bacnet_point_ids[0]['id']}")
                assert ok(code) and one_pt
                assert one_pt.get("bacnet_device_id") and one_pt.get(
                    "object_identifier"
                ), "BACnet-imported point should have bacnet_device_id and object_identifier"
                print(
                    "[2f] GET /points/{id}: BACnet point has bacnet_device_id, object_identifier"
                )
                print("    OK\n")

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

    # --- Data model TTL (brick_model + merged BACnet when present) ---
    print("[4c] GET /data-model/ttl (TTL content smoke)")
    code, ttl_body = _request("GET", "/data-model/ttl")
    assert ok(code), f"GET /data-model/ttl failed: {code}"
    assert isinstance(ttl_body, str), "TTL response should be string"
    assert (
        "@prefix brick:" in ttl_body or "brick:" in ttl_body
    ), "TTL should contain Brick prefix/content"
    assert (
        test_site_name in ttl_body
    ), f"TTL should contain site name {test_site_name!r}"
    print(f"    OK — TTL length {len(ttl_body)}\n")

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
    assert ok(code)
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

    # --- SPARQL: point labels in TTL after create ---
    print("[14b] SPARQL: point labels (TTL in sync)")
    pt_labels = _sparql_point_labels()
    assert (
        "SA-T" in pt_labels and "OAT" in pt_labels
    ), f"Expected SA-T, OAT in {pt_labels}"
    print(f"    OK — {pt_labels}\n")

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

    # --- SPARQL: SA-T gone from TTL ---
    print("[17b] SPARQL: SA-T removed from TTL")
    pt_labels = _sparql_point_labels()
    assert "SA-T" not in pt_labels, f"SA-T should be gone: {pt_labels}"
    assert "OAT" in pt_labels, f"OAT should remain: {pt_labels}"
    print(f"    OK — {pt_labels}\n")

    # --- Delete point 2 ---
    print("[18] DELETE /points/{id} (OAT)")
    code, _ = _request("DELETE", f"/points/{point2_id}")
    assert ok(code)
    code, _ = _request("GET", f"/points/{point2_id}")
    assert code == 404
    print("    OK (verified 404)\n")

    # --- SPARQL: no points for our equipment (or OAT gone) ---
    print("[18b] SPARQL: point labels after delete OAT")
    pt_labels = _sparql_point_labels()
    assert (
        "OAT" not in pt_labels and "SA-T" not in pt_labels
    ), f"Both points should be gone: {pt_labels}"
    print(f"    OK — {pt_labels}\n")

    # --- Delete equipment ---
    print("[19] DELETE /equipment/{id}")
    code, _ = _request("DELETE", f"/equipment/{equipment_id}")
    assert ok(code)
    code, _ = _request("GET", f"/equipment/{equipment_id}")
    assert code == 404
    print("    OK (verified 404)\n")

    # --- SPARQL: equipment gone from TTL ---
    print("[19b] SPARQL: equipment labels (test-ahu-1 gone)")
    eq_labels = _sparql_equipment_labels()
    assert "test-ahu-1" not in eq_labels, f"test-ahu-1 should be gone: {eq_labels}"
    print(f"    OK — {eq_labels}\n")

    # --- BACnet device 3456789: CRUD delete a few points, then equipment; validate in CRUD + SPARQL ---
    if bacnet_equipment_id:
        if bacnet_point_ids:
            to_delete = bacnet_point_ids[:2]  # delete up to 2 points
            for i, bp in enumerate(to_delete):
                pid, ext = bp["id"], bp.get("external_id") or bp["id"]
                print(f"[19c.{i+1}] DELETE /points/{{id}} (BACnet point {ext})")
                code, _ = _request("DELETE", f"/points/{pid}")
                assert ok(code)
                code, _ = _request("GET", f"/points/{pid}")
                assert code == 404
                print("    OK (verified 404)\n")
            print("[19d] SPARQL: deleted BACnet points removed from TTL")
            pt_labels_after = _sparql_point_labels()
            for bp in to_delete:
                ext = (bp.get("external_id") or "").strip()
                if ext:
                    assert (
                        ext not in pt_labels_after
                    ), f"Point {ext!r} should be gone: {pt_labels_after}"
            print(f"    OK — {pt_labels_after}\n")

            # Delete remaining BACnet points (so we can delete equipment)
            for bp in bacnet_point_ids[2:]:
                pid = bp["id"]
                print("[19e] DELETE /points/{id} (remaining BACnet point)")
                code, _ = _request("DELETE", f"/points/{pid}")
                assert ok(code)
                print("    OK\n")

        print("[19f] DELETE /equipment/{id} (BACnet device 3456789)")
        code, _ = _request("DELETE", f"/equipment/{bacnet_equipment_id}")
        assert ok(code)
        code, _ = _request("GET", f"/equipment/{bacnet_equipment_id}")
        assert code == 404
        print("    OK (verified 404)\n")

        print("[19g] SPARQL: BACnet device 3456789 removed from TTL")
        eq_labels = _sparql_equipment_labels()
        assert (
            f"BACnet device {DEVICE_3456789}" not in eq_labels
        ), f"BACnet device should be gone: {eq_labels}"
        print(f"    OK — {eq_labels}\n")

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
        "  Health, BACnet proxy (server_hello, whois_range, discovery-to-rdf, import_into_data_model),"
    )
    print(
        "  CRUD (sites, equipment, points), data model (TTL, export, SPARQL), merged BACnet+BRICK graph,"
    )
    print("  download (CSV, faults), lifecycle (create → import → delete → SPARQL).")
    print(
        "  config/brick_model.ttl is updated on every CRUD and import (watch it change on create/update/delete).\n"
    )


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
        help="Skip discovery-to-rdf (don’t send BACnet request through Open-FDD)",
    )
    args = parser.parse_args()

    global BASE_URL, BACNET_URL
    BASE_URL = (os.environ.get("BASE_URL") or args.base_url).strip().rstrip("/")
    if args.skip_bacnet:
        BACNET_URL = ""
    else:
        BACNET_URL = (
            (os.environ.get("BACNET_URL") or args.bacnet_url).strip().rstrip("/")
        )

    run()


if __name__ == "__main__":
    main()
