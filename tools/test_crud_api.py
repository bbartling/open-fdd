#!/usr/bin/env python3
"""
End-to-end CRUD API test against localhost:8000.

Creates: site → equipment → points, then deletes in reverse order.
Deletes cascade: point → timeseries; equipment → points; site → equipment, points,
  fault_results, fault_events. See docs/howto/danger_zone.md.

Usage:
  python tools/test_crud_api.py
  BASE_URL=http://localhost:8000 python tools/test_crud_api.py
"""

import json
import os
import sys
from uuid import UUID

try:
    import httpx
except ImportError:
    import urllib.request
    import urllib.error

    httpx = None

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000")


def _request(
    method: str, path: str, *, json_body: dict | None = None
) -> tuple[int, dict | list | str | None]:
    """Send HTTP request, return (status_code, parsed_json or raw text for CSV)."""
    url = f"{BASE_URL.rstrip('/')}{path}"
    if httpx:
        with httpx.Client(timeout=30.0) as client:
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
        with urllib.request.urlopen(req) as res:
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


def run():
    print(f"\n=== Open-FDD CRUD API Test ===\nBase URL: {BASE_URL}\n")

    # --- Health ---
    print("[1] GET /health")
    code, data = _request("GET", "/health")
    assert ok(code), f"Expected 200, got {code}"
    assert data.get("status") == "ok"
    print("    OK\n")

    # --- Create site ---
    print("[2] POST /sites")
    code, site = _request(
        "POST",
        "/sites",
        json_body={"name": "test-crud-site", "description": "Script test site"},
    )
    assert ok(code), f"Expected 201/200, got {code}: {site}"
    site_id = site["id"]
    print(f"    OK → site_id={site_id}\n")

    # --- Get site ---
    print("[3] GET /sites/{id}")
    code, got = _request("GET", f"/sites/{site_id}")
    assert ok(code)
    assert got["name"] == "test-crud-site"
    print("    OK\n")

    # --- List sites ---
    print("[4] GET /sites")
    code, sites = _request("GET", "/sites")
    assert ok(code)
    assert any(s["id"] == site_id for s in sites)
    print(f"    OK ({len(sites)} sites)\n")

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

    # --- Delete point 2 ---
    print("[18] DELETE /points/{id} (OAT)")
    code, _ = _request("DELETE", f"/points/{point2_id}")
    assert ok(code)
    code, _ = _request("GET", f"/points/{point2_id}")
    assert code == 404
    print("    OK (verified 404)\n")

    # --- Delete equipment ---
    print("[19] DELETE /equipment/{id}")
    code, _ = _request("DELETE", f"/equipment/{equipment_id}")
    assert ok(code)
    code, _ = _request("GET", f"/equipment/{equipment_id}")
    assert code == 404
    print("    OK (verified 404)\n")

    # --- Delete site ---
    print("[20] DELETE /sites/{id}")
    code, _ = _request("DELETE", f"/sites/{site_id}")
    assert ok(code)
    code, _ = _request("GET", f"/sites/{site_id}")
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
    # Empty faults = minimal CSV (header only or empty); non-empty has ts, site_id, etc.
    if isinstance(body, str) and body.strip():
        assert "ts" in body or "site_id" in body or "," in body
    print("    OK\n")

    print("=== All 24 checks passed ===\n")


if __name__ == "__main__":
    run()
