#!/usr/bin/env python3
"""
Delete all sites via the Open-FDD API (cascade removes equipment, points, timeseries, etc.),
then POST /data-model/reset so the in-memory graph and brick_model.ttl reflect the empty DB.

Usage:
  python tools/delete_all_sites_and_reset.py
  BASE_URL=http://192.168.204.16:8000 python tools/delete_all_sites_and_reset.py

Requires: requests or httpx (pip install httpx).
"""

import os
import sys

try:
    import httpx
except ImportError:
    try:
        import requests as _r

        httpx = None
    except ImportError:
        print("Install httpx or requests: pip install httpx", file=sys.stderr)
        sys.exit(1)

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000").rstrip("/")


def _request(method: str, path: str, **kwargs):
    url = f"{BASE_URL}{path}"
    if httpx:
        with httpx.Client(timeout=30.0) as client:
            r = client.request(method, url, **kwargs)
            try:
                return r.status_code, r.json() if r.content else None
            except Exception:
                return r.status_code, r.text
    r = _r.request(method, url, **kwargs)
    try:
        return r.status_code, r.json() if r.content else None
    except Exception:
        return r.status_code, r.text


def main():
    print(f"Base URL: {BASE_URL}\n")

    # 1. GET all sites
    code, data = _request("GET", "/sites")
    if code != 200:
        print(f"GET /sites failed: {code} {data}")
        sys.exit(1)
    sites = data if isinstance(data, list) else []
    if not sites:
        print("No sites. POST /data-model/reset to sync graph/file.")
        code, data = _request("POST", "/data-model/reset")
        if code == 200 and isinstance(data, dict):
            print("Reset OK:", data.get("message", data))
        return

    print(
        f"Deleting {len(sites)} site(s) (cascade: equipment, points, timeseries, faults)..."
    )
    for s in sites:
        sid = s.get("id")
        name = s.get("name", "?")
        if not sid:
            continue
        code, _ = _request("DELETE", f"/sites/{sid}")
        if 200 <= code < 300:
            print(f"  Deleted site {name!r} ({sid})")
        else:
            print(f"  Failed to delete {name!r} ({sid}): {code}")

    # 2. Reset graph to DB-only and write file (now empty Brick)
    print("\nPOST /data-model/reset...")
    code, data = _request("POST", "/data-model/reset")
    if code != 200:
        print(f"Reset failed: {code} {data}")
        sys.exit(1)
    if isinstance(data, dict):
        print("OK:", data.get("message", data.get("path", "")))
    else:
        print("OK:", data)
    print("\nData model is now empty (no sites, no Brick triples, no BACnet).")


if __name__ == "__main__":
    main()
