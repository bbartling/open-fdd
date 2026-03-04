#!/usr/bin/env python3
"""
Test Caddy → API auth: prove X-Caddy-Auth is accepted and debug 401s.

Requires: requests (pip install requests).

Test on localhost (same machine as the stack):
  cd /path/to/open-fdd
  python3 scripts/test_caddy_auth.py

Test from a remote machine (replace 192.168.204.16 with your server IP):
  python3 scripts/test_caddy_auth.py --api-url http://192.168.204.16:8000 --caddy-url http://192.168.204.16
"""

import argparse
import sys

try:
    import requests
except ImportError:
    print("Need requests: pip install requests", file=sys.stderr)
    sys.exit(1)

SECRET = "openfdd-internal"
BASIC_USER = "openfdd"
BASIC_PASS = "xyz"

# GET routes the UI hits after one Basic login — we prove no re-auth per click.
API_ROUTES = [
    "/health",
    "/config",
    "/capabilities",
    "/sites",
    "/equipment",
    "/points",
    "/faults/active",
    "/faults/definitions",
    "/run-fdd/status",
    "/entities/suggested",
    "/data-model/export",
    "/openapi.json",
]


def main():
    p = argparse.ArgumentParser(
        description="Test API auth with X-Caddy-Auth and via Caddy",
        epilog=(
            "Localhost: python3 scripts/test_caddy_auth.py\n"
            "Remote:   python3 scripts/test_caddy_auth.py --api-url http://HOST:8000 --caddy-url http://HOST"
        ),
    )
    p.add_argument("--api-url", default="http://localhost:8000", help="API base (default: http://localhost:8000)")
    p.add_argument("--caddy-url", default="http://localhost:80", help="Caddy base (default: http://localhost:80)")
    args = p.parse_args()

    api = args.api_url.rstrip("/")
    caddy = args.caddy_url.rstrip("/")

    print("=== 0. (Optional) Verify API container has OFDD_CADDY_INTERNAL_SECRET ===")
    print("  Run: docker exec openfdd_api env | grep OFDD_CADDY")
    print("  Expected: OFDD_CADDY_INTERNAL_SECRET=openfdd-internal")
    print("")

    print("=== 1. Direct API with X-Caddy-Auth (simulates Caddy adding header) ===")
    try:
        r = requests.get(f"{api}/config", headers={"X-Caddy-Auth": SECRET}, timeout=10)
    except requests.exceptions.ConnectionError as e:
        print(f"  GET {api}/config  ->  Connection failed (is the stack running?)")
        print(f"  Error: {e}")
        r = None
    if r is not None:
        print(f"  GET {api}/config  X-Caddy-Auth: openfdd-internal  ->  {r.status_code}")
    if r is None:
        pass
    elif r.status_code == 200:
        print("  OK – API accepts X-Caddy-Auth when OFDD_CADDY_INTERNAL_SECRET is set.")
    else:
        print(f"  FAIL – Expected 200. Body: {r.text[:200]}")
        print("  Check: docker exec openfdd_api env | grep OFDD_CADDY  (should show OFDD_CADDY_INTERNAL_SECRET=openfdd-internal)")

    print("\n=== 2. Direct API without auth header (expect 401 if OFDD_API_KEY is set) ===")
    try:
        r2 = requests.get(f"{api}/config", timeout=10)
        print(f"  GET {api}/config  (no headers)  ->  {r2.status_code}")
    except requests.exceptions.ConnectionError:
        print(f"  GET {api}/config  ->  Connection failed")
        r2 = type("R", (), {"status_code": None})()
    if getattr(r2, "status_code", None) == 401:
        print("  OK – API requires auth when no X-Caddy-Auth and API key is set.")
    elif getattr(r2, "status_code", None) is not None:
        print(f"  Got {r2.status_code} (401 expected if OFDD_API_KEY is set).")

    print("\n=== 3. Browser mimic: auth once, then hit all API routes (no re-auth per request) ===")
    session = requests.Session()
    session.auth = (BASIC_USER, BASIC_PASS)
    session.timeout = 10
    # One "login" request — same as browser sending Basic on first request
    try:
        r3 = session.get(f"{caddy}/config", timeout=10)
        print(f"  Login: GET {caddy}/config  ->  {r3.status_code}")
    except requests.exceptions.ConnectionError:
        print(f"  Login: GET {caddy}/config  ->  Connection failed")
        r3 = type("R", (), {"status_code": None, "text": ""})()
    step3_ok = getattr(r3, "status_code", None) == 200
    if not step3_ok:
        print("  FAIL – Login request must return 200. Fix Caddy/API before testing routes.")
    else:
        print("  Using same session (no new auth) for all routes below:")
        route_ok = True
        for path in API_ROUTES:
            url = f"{caddy}{path}"
            try:
                r = session.get(url, timeout=10)
                # Success = we were authenticated (no 401). 200/204/404/400/422 are fine.
                ok = r.status_code != 401
                if not ok:
                    route_ok = False
                status = "OK" if ok else "FAIL (401)"
                print(f"    {path}  ->  {r.status_code}  {status}")
            except requests.exceptions.ConnectionError:
                print(f"    {path}  ->  Connection failed")
                route_ok = False
        step3_ok = route_ok
        if step3_ok:
            print("  OK – One Basic auth; all routes accepted (no 401). No re-auth needed per button/feature.")
        else:
            print("  FAIL – At least one route returned 401; check Caddy header_up X-Caddy-Auth and API OFDD_CADDY_INTERNAL_SECRET.")

    print("\n=== 4. Via Caddy without Basic auth (expect 401 from Caddy) ===")
    try:
        r4 = requests.get(f"{caddy}/config", timeout=10)
        print(f"  GET {caddy}/config  (no auth)  ->  {r4.status_code}")
    except requests.exceptions.ConnectionError:
        print(f"  GET {caddy}/config  ->  Connection failed")
        r4 = type("R", (), {"status_code": None})()
    if getattr(r4, "status_code", None) == 401:
        print("  OK – Caddy requires Basic auth.")
    elif getattr(r4, "status_code", None) is not None:
        print(f"  Got {r4.status_code}.")

    ok = (
        r is not None
        and r.status_code == 200
        and step3_ok
    )
    print("\n" + ("All critical checks passed." if ok else "Some checks failed – see above."))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
