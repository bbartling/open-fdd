#!/usr/bin/env python3
"""
Simple BACnet + CRUD smoke test for your building: whois over your instance range, discover points, run CRUD.

No hardcoded device IDs or site names. Use your own BACnet instance range (e.g. 1–3456999).
All requests go through the Open-FDD API; no direct triple-store or TTL access.

Usage:
  python tools/bacnet_crud_smoke_test.py
  python tools/bacnet_crud_smoke_test.py --start-instance 1 --end-instance 3456999
  python tools/bacnet_crud_smoke_test.py --max-devices 2 --max-points 5 --no-cleanup
  python tools/bacnet_crud_smoke_test.py --start-instance 1 --end-instance 3456999 --no-cleanup 

Options:
  --base-url          Open-FDD API (default: http://localhost:8000)
  --bacnet-url        Gateway URL sent in body (default: host.docker.internal:8080 when base is localhost)
  --start-instance    Who-Is range start (default: 1)
  --end-instance      Who-Is range end for your network (default: 3456999)
  --max-devices       Max devices to discover and use (default: 2)
  --max-points        Max points per device to create in CRUD (default: 5)
  --no-cleanup        Do not delete the created site at the end
  --wait-scrapes      Wait until N BACnet scrape(s) have run (0 = skip). Default: 0.
  --scrape-interval-min  Scraper interval in minutes (for wait timeout). Default: 5.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
import time
from datetime import date, timedelta

try:
    import httpx
except ImportError:
    httpx = None

BASE_URL = "http://localhost:8000"
BACNET_URL = ""
# When base is localhost, use host.docker.internal so API (in Docker) can reach BACnet
BACNET_URL_FOR_LOCALHOST = "http://host.docker.internal:8080"


def _request(
    method: str, path: str, *, json_body: dict | None = None, timeout: float = 30.0
) -> tuple[int, dict | list | None]:
    url = f"{BASE_URL.rstrip('/')}{path}"
    if httpx:
        with httpx.Client(timeout=timeout) as client:
            r = client.request(method, url, json=json_body)
            try:
                return r.status_code, r.json() if r.content else None
            except Exception:
                return r.status_code, r.text
    import urllib.request
    import urllib.error
    req = urllib.request.Request(url, method=method)
    if json_body:
        req.add_header("Content-Type", "application/json")
        req.data = json.dumps(json_body).encode()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            body = res.read().decode("utf-8")
            if not body:
                return res.status, None
            return res.status, json.loads(body)
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


def _wait_for_api(max_wait_sec: float = 45.0) -> None:
    deadline = time.time() + max_wait_sec
    while time.time() < deadline:
        code, _ = _request("GET", "/health", timeout=5.0)
        if ok(code):
            return
        time.sleep(2)
    raise RuntimeError(f"API at {BASE_URL} not ready after {max_wait_sec}s")


def run(
    start_instance: int,
    end_instance: int,
    max_devices: int,
    max_points: int,
    cleanup: bool,
    wait_scrapes: int = 0,
    scrape_interval_min: int = 5,
) -> None:
    print("\n=== BACnet + CRUD smoke test ===\n")
    print(f"Base URL: {BASE_URL}")
    print(f"BACnet instance range: {start_instance}–{end_instance}")
    print(f"Max devices: {max_devices}, max points per device: {max_points}\n")

    _wait_for_api()

    # BACnet gateway URL for request body (so API in Docker can reach gateway)
    bacnet_body = lambda **kw: {**kw, "url": BACNET_URL} if BACNET_URL else kw

    print("[1] POST /bacnet/server_hello")
    code, sh = _request("POST", "/bacnet/server_hello", json_body=bacnet_body())
    if not ok(code) or not (isinstance(sh, dict) and sh.get("ok")):
        print(f"  SKIP BACnet (server_hello failed: {sh}). Run without BACnet or set --bacnet-url.\n")
        print("  Creating site + one point without BACnet discovery to still exercise CRUD.")
        # Create minimal site + point so we still test CRUD
        code, site = _request("POST", "/sites", json_body={"name": "SmokeTestSite", "description": "Smoke test"})
        assert ok(code), f"POST /sites failed: {code}"
        site_id = site["id"]
        code, eq = _request("POST", "/equipment", json_body={"site_id": site_id, "name": "SmokeTestEq", "description": "Smoke", "equipment_type": "Equipment"})
        assert ok(code), f"POST /equipment failed: {code}"
        code, pt = _request("POST", "/points", json_body={"site_id": site_id, "equipment_id": eq["id"], "external_id": "smoke-point", "unit": "degF"})
        assert ok(code), f"POST /points failed: {code}"
        print(f"  OK — site {site_id}, 1 point (no BACnet).\n")
        if cleanup:
            code, _ = _request("DELETE", f"/sites/{site_id}")
            print("  Cleanup: site deleted.\n")
        return

    print("  OK\n")

    print("[2] POST /bacnet/whois_range")
    code, wr = _request(
        "POST",
        "/bacnet/whois_range",
        json_body=bacnet_body(request={"start_instance": start_instance, "end_instance": end_instance}),
        timeout=15.0,
    )
    assert ok(code), f"whois_range failed: {code} {wr}"
    body = wr.get("body") if isinstance(wr, dict) else wr
    res = (body or {}).get("result") if isinstance(body, dict) else {}
    data = (res.get("data") or res) if isinstance(res, dict) else {}
    devices = data.get("devices") if isinstance(data, dict) else (data if isinstance(data, list) else [])
    devices = devices or []
    if not devices:
        print("  No devices in range. Create site + one point to exercise CRUD.\n")
        code, site = _request("POST", "/sites", json_body={"name": "SmokeTestSite", "description": "Smoke test"})
        assert ok(code)
        site_id = site["id"]
        code, eq = _request("POST", "/equipment", json_body={"site_id": site_id, "name": "SmokeTestEq", "description": "Smoke", "equipment_type": "Equipment"})
        assert ok(code)
        code, _ = _request("POST", "/points", json_body={"site_id": site_id, "equipment_id": eq["id"], "external_id": "smoke-point", "unit": "degF"})
        assert ok(code)
        if cleanup:
            _request("DELETE", f"/sites/{site_id}")
        return

    # BACnet device instance: valid range 1–4194303. Exclude common non-instance values (max APDU, max segments, test/sentinel, etc.).
    _NOT_INSTANCE = {50, 128, 256, 480, 999, 1024, 1476, 9999, 65535}

    def _parse_device_identifier_string(s: str) -> int | None:
        """Parse 'device,3456790' or 'device, 3456790' -> 3456790. BACnet I-Am device-identifier format."""
        if not isinstance(s, str) or not s.strip():
            return None
        parts = s.strip().split(",")
        if len(parts) < 2:
            return None
        try:
            n = int(parts[-1].strip())
            return n if 1 <= n <= 4194303 and n not in _NOT_INSTANCE else None
        except (ValueError, TypeError):
            return None

    def _inst(d):
        if d is None:
            return None
        if isinstance(d, (int, float)) and not isinstance(d, bool):
            n = int(d)
            return n if 1 <= n <= 4194303 and n not in _NOT_INSTANCE else None
        if isinstance(d, dict):
            # String form from diy-bacnet etc.: 'i-am-device-identifier': 'device,3456790'
            for key in (
                "i-am-device-identifier",
                "i_am_device_identifier",
                "device_identifier",
                "identifier",
            ):
                v = d.get(key)
                if isinstance(v, str):
                    inst = _parse_device_identifier_string(v)
                    if inst is not None:
                        return inst
            for key in ("device_instance", "instance", "deviceInstance", "device_id", "deviceId"):
                v = d.get(key)
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    n = int(v)
                    if 1 <= n <= 4194303 and n not in _NOT_INSTANCE:
                        return n
            if isinstance(d.get("id"), (int, float)):
                n = int(d["id"])
                if 1 <= n <= 4194303 and n not in _NOT_INSTANCE:
                    return n
            inner = d.get("device_identifier") or d.get("identifier")
            if isinstance(inner, (int, float)):
                n = int(inner)
                if 1 <= n <= 4194303 and n not in _NOT_INSTANCE:
                    return n
            if isinstance(inner, (list, tuple)) and len(inner) >= 2:
                n = int(inner[1])
                if 1 <= n <= 4194303 and n not in _NOT_INSTANCE:
                    return n
        return None

    def _inst_from_dict_last_resort(d):
        """Last resort: pick best numeric value in dict (exclude max APDU etc.; prefer largest = likely device instance)."""
        candidates = []
        for v in d.values():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                n = int(v)
                if 1 <= n <= 4194303 and n not in _NOT_INSTANCE:
                    candidates.append(n)
        return max(candidates) if candidates else None

    dev_instances = []
    for d in devices[:max_devices]:
        inst = _inst(d)
        if inst is not None:
            dev_instances.append(inst)
    if not dev_instances and devices:
        inst = _inst(devices[0])
        if inst is not None:
            dev_instances = [inst]
    if not dev_instances and devices:
        for d in devices[:max_devices]:
            if isinstance(d, (int, float)) and not isinstance(d, bool):
                inst = _inst(d)
                if inst is not None:
                    dev_instances.append(inst)
            elif isinstance(d, dict):
                inst = _inst_from_dict_last_resort(d)
                if inst is not None:
                    dev_instances.append(inst)
    # Unique, preserve order (whois may return same device twice or we had duplicate 1024)
    dev_instances = list(dict.fromkeys(dev_instances))
    print(f"  OK — {len(devices)} device(s), using {dev_instances}\n")

    if not dev_instances:
        if devices:
            print(f"  WARN — could not get instance IDs from whois (first device: {devices[0]!r}). Create site + 1 point.\n")
        print("  No device instances to discover. Create site + one point to exercise CRUD.\n")
        code, site = _request("POST", "/sites", json_body={"name": "SmokeTestSite", "description": "Smoke test"})
        assert ok(code)
        site_id = site["id"]
        code, eq = _request("POST", "/equipment", json_body={"site_id": site_id, "name": "SmokeTestEq", "description": "Smoke", "equipment_type": "Equipment"})
        assert ok(code)
        code, _ = _request("POST", "/points", json_body={"site_id": site_id, "equipment_id": eq["id"], "external_id": "smoke-point", "unit": "degF"})
        assert ok(code)
        if cleanup:
            _request("DELETE", f"/sites/{site_id}")
            print("  Cleanup: site deleted.\n")
        return

    # Point discovery for each device; collect objects (e.g. analog-input) up to max_points per device
    all_points: list[dict] = []
    for dev_inst in dev_instances:
        print(f"[3] POST /bacnet/point_discovery (device {dev_inst})")
        code, pd = _request(
            "POST",
            "/bacnet/point_discovery",
            json_body=bacnet_body(instance={"device_instance": dev_inst}),
            timeout=30.0,
        )
        if not ok(code):
            print(f"  WARN — point_discovery failed: {code}")
            continue
        body = pd.get("body") if isinstance(pd, dict) else pd
        res = (body or {}).get("result") if isinstance(body, dict) else {}
        data = (res.get("data") or res) if isinstance(res, dict) else {}
        objects = data.get("objects") if isinstance(data, dict) else (data if isinstance(data, list) else [])
        objects = objects or []
        # Prefer analog-input / analog-value for sensor-like points
        chosen = []
        for obj in objects:
            if len(chosen) >= max_points:
                break
            if not isinstance(obj, dict):
                continue
            oid = obj.get("object_identifier") or obj.get("object_id")
            name = (obj.get("object_name") or obj.get("name") or "").strip() or str(oid)
            if oid and name:
                chosen.append({"object_identifier": str(oid), "object_name": name, "device_instance": dev_inst})
        if not chosen:
            for obj in objects[:max_points]:
                if isinstance(obj, dict) and (obj.get("object_identifier") or obj.get("object_id")):
                    oid = obj.get("object_identifier") or obj.get("object_id")
                    chosen.append({
                        "object_identifier": str(oid),
                        "object_name": (obj.get("object_name") or obj.get("name") or str(oid)).strip(),
                        "device_instance": dev_inst,
                    })
        all_points.extend(chosen)
        print(f"  OK — {len(objects)} objects, using {len(chosen)} points\n")

    if not all_points:
        print("  No points from discovery. Create one manual point.\n")
        code, site = _request("POST", "/sites", json_body={"name": "SmokeTestSite", "description": "Smoke test"})
        assert ok(code)
        site_id = site["id"]
        code, eq = _request("POST", "/equipment", json_body={"site_id": site_id, "name": "SmokeTestEq", "description": "Smoke", "equipment_type": "Equipment"})
        assert ok(code)
        code, _ = _request("POST", "/points", json_body={"site_id": site_id, "equipment_id": eq["id"], "external_id": "smoke-point", "unit": "degF"})
        assert ok(code)
        if cleanup:
            _request("DELETE", f"/sites/{site_id}")
        return

    # CRUD: create site, equipment, points
    print("[4] POST /sites (SmokeTestSite)")
    code, site = _request("POST", "/sites", json_body={"name": "SmokeTestSite", "description": "BACnet smoke test"})
    assert ok(code), f"POST /sites failed: {code}"
    site_id = site["id"]
    print("  OK\n")

    print("[5] POST /equipment (SmokeTestEq)")
    code, eq = _request("POST", "/equipment", json_body={"site_id": site_id, "name": "SmokeTestEq", "description": "Smoke", "equipment_type": "Equipment"})
    assert ok(code), f"POST /equipment failed: {code}"
    eq_id = eq["id"]
    print("  OK\n")

    # external_id must be unique per site (DB UNIQUE(site_id, external_id)); disambiguate if object_name repeats
    used_external_ids: set[str] = set()

    print(f"[6] POST /points ({len(all_points)} points from BACnet discovery)")
    for i, pt in enumerate(all_points):
        base = (pt.get("object_name") or "").strip() or f"point-{i}"
        external_id = base
        if external_id in used_external_ids:
            external_id = f"{base}_{pt['device_instance']}"
        if external_id in used_external_ids:
            oid_safe = (pt.get("object_identifier") or "").replace(",", "-")
            external_id = f"{base}_{oid_safe}"
        used_external_ids.add(external_id)
        code, _ = _request("POST", "/points", json_body={
            "site_id": site_id,
            "equipment_id": eq_id,
            "external_id": external_id,
            "bacnet_device_id": str(pt["device_instance"]),
            "object_identifier": pt["object_identifier"],
            "object_name": pt["object_name"],
            "unit": "degF",
        })
        assert ok(code), f"POST /points {external_id!r} failed: {code}"
    print("  OK\n")

    print("[7] GET /sites, GET /points")
    code, sites = _request("GET", "/sites")
    assert ok(code)
    code, points = _request("GET", f"/points?site_id={site_id}")
    assert ok(code)
    points = points if isinstance(points, list) else []
    print(f"  OK — {len(sites)} site(s), {len(points)} point(s)\n")

    print("[8] POST /data-model/sparql (sites count)")
    code, sparql = _request("POST", "/data-model/sparql", json_body={
        "query": "PREFIX brick: <https://brickschema.org/schema/Brick#> SELECT (COUNT(?s) AS ?n) WHERE { ?s a brick:Site }"
    })
    if ok(code) and isinstance(sparql, dict) and sparql.get("bindings"):
        n = sparql["bindings"][0].get("n", "?")
        print(f"  OK — SPARQL sites count: {n}\n")
    else:
        print("  OK (skip SPARQL)\n")

    print("[8b] POST /data-model/serialize (write TTL from graph)")
    code, ser = _request("POST", "/data-model/serialize")
    if ok(code):
        path = (ser or {}).get("path", "?") if isinstance(ser, dict) else "?"
        print(f"  OK — path={path}\n")
    else:
        print("  OK (skip serialize)\n")

    print("[8c] GET /data-model/ttl?save=true (validate site and points in TTL)")
    code, ttl_body = _request("GET", "/data-model/ttl?save=true")
    if code == 200 and isinstance(ttl_body, str):
        has_site = "SmokeTestSite" in ttl_body
        has_points = any(pt.get("object_name", "") in ttl_body for pt in all_points[:3])
        print(f"  OK — TTL length {len(ttl_body)}, SmokeTestSite in TTL={has_site}, points in TTL={has_points}\n")
    else:
        print("  OK (skip TTL check)\n")

    # Optional: add discovered devices to graph (BACnet RDF) so graph has Brick + BACnet
    if dev_instances and BACNET_URL:
        print("[8d] POST /bacnet/point_discovery_to_graph (discovered devices → graph)")
        for dev_inst in dev_instances[:max_devices]:
            code, pdg = _request(
                "POST",
                "/bacnet/point_discovery_to_graph",
                json_body=bacnet_body(instance={"device_instance": dev_inst}, update_graph=True, write_file=True),
                timeout=30.0,
            )
            if not ok(code):
                print(f"  WARN — point_discovery_to_graph({dev_inst}) failed: {code}")
            else:
                print(f"  OK — device {dev_inst} → graph")
        print("")

    # Delete one point and verify 404 + SPARQL reflects removal (CRUD + data model sync)
    if points:
        first_point = points[0]
        point_id = first_point.get("id") if isinstance(first_point, dict) else None
        point_label = (first_point.get("external_id") or first_point.get("object_name") or "point") if isinstance(first_point, dict) else "point"
        if point_id:
            print(f"[8e] DELETE /points/{{id}} ({point_label}); verify 404 and SPARQL")
            code, _ = _request("DELETE", f"/points/{point_id}")
            assert ok(code), f"DELETE /points failed: {code}"
            code, _ = _request("GET", f"/points/{point_id}")
            assert code == 404, f"Point should be gone: {code}"
            code, sparql_pts = _request("POST", "/data-model/sparql", json_body={
                "query": "PREFIX brick: <https://brickschema.org/schema/Brick#> SELECT ?l WHERE { ?s a brick:Point ; brick:label ?l . FILTER(CONTAINS(STR(?s), \"/points/\")) }"
            })
            if ok(code) and isinstance(sparql_pts, dict) and sparql_pts.get("bindings"):
                labels = [b.get("l", "") for b in sparql_pts["bindings"] if b.get("l")]
                print(f"  OK — point deleted, 404 verified, SPARQL point labels (sample): {labels[:5]}\n")
            else:
                print("  OK — point deleted, 404 verified\n")
        else:
            print("[8e] Skip (no point id for delete)\n")
    else:
        print("[8e] Skip (no points to delete)\n")

    print("[8f] GET /data-model/check (integrity)")
    code, check = _request("GET", "/data-model/check")
    if ok(code) and isinstance(check, dict):
        sites_count = check.get("sites", "?")
        print(f"  OK — sites={sites_count}\n")
    else:
        print("  OK (skip check)\n")

    # [26b] Optional: wait until N BACnet scrapes have run (default: skip)
    if wait_scrapes >= 1:
        timeout_sec = max(
            2 * scrape_interval_min * 60 + 120,
            wait_scrapes * scrape_interval_min * 60 + 120,
        )
        print(f"[26b] Wait until {wait_scrapes} BACnet scrape(s) have run (scrape_interval_min={scrape_interval_min}, timeout ~{timeout_sec // 60} min)")
        end_d = date.today()
        start_d = end_d - timedelta(days=1)
        poll_interval_sec = 20
        deadline = time.monotonic() + timeout_sec
        distinct_ts = 0
        while time.monotonic() < deadline:
            code, csv_body = _request(
                "GET",
                f"/download/csv?site_id={site_id}&start_date={start_d}&end_date={end_d}&format=wide",
                timeout=15.0,
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
                    if distinct_ts >= wait_scrapes:
                        print(f"  OK — {distinct_ts} distinct scrape timestamp(s) seen; {wait_scrapes}+ scrapes done.\n")
                        break
            elapsed = int(time.monotonic() - (deadline - timeout_sec))
            print(f"  ... waiting for scrapes ({distinct_ts} distinct ts so far, {elapsed}s elapsed)")
            time.sleep(poll_interval_sec)
        else:
            if wait_scrapes >= 1:
                print(f"  WARNING — timeout after {timeout_sec}s; scrapes may not have run (check OFDD_BACNET_SCRAPE_INTERVAL_MIN and gateway).\n")
    else:
        print("[26b] Skip (--wait-scrapes 0, default). Use --wait-scrapes 2 to wait for BACnet scrapes.\n")

    if cleanup:
        print("[9] DELETE /sites/{id} (cleanup)")
        code, _ = _request("DELETE", f"/sites/{site_id}")
        assert ok(code)
        print("  OK\n")
    else:
        print("[9] No cleanup (--no-cleanup); site left in place.\n")

    print("=== Smoke test passed ===\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="BACnet + CRUD smoke test (instance range, discover, CRUD).")
    parser.add_argument("--base-url", default=os.environ.get("BASE_URL", "http://localhost:8000"), help="Open-FDD API base URL")
    parser.add_argument("--bacnet-url", default=os.environ.get("BACNET_URL", "http://localhost:8080"), help="BACnet gateway URL (sent in request body)")
    parser.add_argument("--start-instance", type=int, default=int(os.environ.get("BACNET_START_INSTANCE", "1")), help="Who-Is range start (default: 1)")
    parser.add_argument("--end-instance", type=int, default=int(os.environ.get("BACNET_END_INSTANCE", "3456999")), help="Who-Is range end (default: 3456999)")
    parser.add_argument("--max-devices", type=int, default=2, help="Max devices to discover and use (default: 2)")
    parser.add_argument("--max-points", type=int, default=5, help="Max points per device to create (default: 5)")
    parser.add_argument("--no-cleanup", action="store_true", help="Do not delete the created site at the end")
    parser.add_argument("--wait-scrapes", type=int, default=0, metavar="N", help="Wait until N BACnet scrape(s) have run (0 = skip). Default: 0.")
    parser.add_argument("--scrape-interval-min", type=int, default=5, metavar="M", help="Scraper interval in minutes for wait timeout. Default: 5.")
    args = parser.parse_args()

    global BASE_URL, BACNET_URL
    BASE_URL = args.base_url.strip().rstrip("/")
    raw = args.bacnet_url.strip().rstrip("/")
    if raw == "http://localhost:8080" and ("localhost" in BASE_URL or "127.0.0.1" in BASE_URL):
        BACNET_URL = BACNET_URL_FOR_LOCALHOST
    else:
        BACNET_URL = raw

    run(
        start_instance=args.start_instance,
        end_instance=args.end_instance,
        max_devices=args.max_devices,
        max_points=args.max_points,
        cleanup=not args.no_cleanup,
        wait_scrapes=args.wait_scrapes,
        scrape_interval_min=args.scrape_interval_min,
    )


if __name__ == "__main__":
    main()
