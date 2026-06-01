#!/usr/bin/env python3
"""Push RTU-01 duct static + discharge-air setpoints to Acme edge (BACnet tab + poll)."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
POINTS_CSV = REPO / "edge_backup/local/acme/vm-bbartling/points.csv"

RTU01_EXTRA_PIDS = {
    "1100-analog-value-3",
    "1100-analog-value-4",
    "1100-analog-value-12",
    "1100-analog-value-15",
}


def _login(base: str, user: str, password: str) -> str:
    body = json.dumps({"username": user, "password": password}).encode()
    req = urllib.request.Request(
        f"{base.rstrip('/')}/api/auth/login",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())["token"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=os.environ.get("ACME_HOST", "100.122.106.124"))
    ap.add_argument("--user", default=os.environ.get("OFDD_INTEGRATOR_USER", "integrator"))
    ap.add_argument("--password", default=os.environ.get("OFDD_INTEGRATOR_PASSWORD", ""))
    args = ap.parse_args()

    if not args.password:
        auth = REPO / "workspace/auth.env.local"
        if auth.is_file():
            for line in auth.read_text(encoding="utf-8").splitlines():
                if line.startswith("OFDD_INTEGRATOR_PASSWORD="):
                    args.password = line.split("=", 1)[1].strip()
                    break
    if not args.password:
        print("Set OFDD_INTEGRATOR_PASSWORD or pass --password", file=sys.stderr)
        return 1

    rows = list(csv.DictReader(POINTS_CSV.open(newline="", encoding="utf-8")))
    extra = [r for r in rows if r.get("point_id") in RTU01_EXTRA_PIDS]
    if len(extra) != len(RTU01_EXTRA_PIDS):
        print(f"Expected {len(RTU01_EXTRA_PIDS)} RTU rows in {POINTS_CSV}, got {len(extra)}", file=sys.stderr)
        return 1

    base = f"http://{args.host}"
    token = _login(base, args.user, args.password)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    body = json.dumps({"rows": extra, "enable_poll": True}).encode()
    req = urllib.request.Request(f"{base}/api/bacnet/driver/merge-rows", data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode()
        if exc.code == 404:
            print(
                "Edge bridge missing /api/bacnet/driver/merge-rows — deploy latest open-fdd to Acme, then re-run.",
                file=sys.stderr,
            )
        print(detail, file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2))
    for r in extra:
        print(f"  + {r['point_id']}: {r['object_name']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
