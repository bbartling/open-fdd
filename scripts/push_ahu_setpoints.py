#!/usr/bin/env python3
"""Merge extra AHU setpoint BACnet rows into edge poll driver (any site pack)."""

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
sys.path.insert(0, str(REPO / "scripts"))

from lib.site_pack_paths import points_csv  # noqa: E402


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


def _load_password(explicit: str) -> str:
    if explicit:
        return explicit
    auth = REPO / "workspace/auth.env.local"
    if auth.is_file():
        for line in auth.read_text(encoding="utf-8").splitlines():
            if line.startswith("OFDD_INTEGRATOR_PASSWORD="):
                return line.split("=", 1)[1].strip()
    return os.environ.get("OFDD_INTEGRATOR_PASSWORD", "")


def main() -> int:
    ap = argparse.ArgumentParser(description="Push AHU setpoint rows to edge BACnet poll driver")
    ap.add_argument("--host", required=True, help="Edge host (LAN or Tailscale IP)")
    ap.add_argument("--site-id", default="")
    ap.add_argument("--building-id", default="")
    ap.add_argument("--csv", type=Path, default=None)
    ap.add_argument(
        "--point-ids",
        default="",
        help="Comma-separated point_id values to merge (required unless --point-ids-file)",
    )
    ap.add_argument("--point-ids-file", type=Path, default=None, help="One point_id per line")
    ap.add_argument("--user", default=os.environ.get("OFDD_INTEGRATOR_USER", "integrator"))
    ap.add_argument("--password", default="")
    args = ap.parse_args()

    password = _load_password(args.password)
    if not password:
        print("Set OFDD_INTEGRATOR_PASSWORD or pass --password", file=sys.stderr)
        return 1

    if args.csv and args.csv.is_file():
        csv_path = args.csv
    elif args.site_id and args.building_id:
        csv_path = points_csv(args.site_id, args.building_id, prefer_gl36_poll=False)
    else:
        print("Provide --csv or --site-id and --building-id", file=sys.stderr)
        return 1

    if not csv_path.is_file():
        print(f"Points CSV not found: {csv_path}", file=sys.stderr)
        return 1

    wanted: set[str] = set()
    if args.point_ids_file and args.point_ids_file.is_file():
        wanted |= {ln.strip() for ln in args.point_ids_file.read_text(encoding="utf-8").splitlines() if ln.strip()}
    if args.point_ids.strip():
        wanted |= {p.strip() for p in args.point_ids.split(",") if p.strip()}
    if not wanted:
        print("Provide --point-ids or --point-ids-file", file=sys.stderr)
        return 1

    rows = list(csv.DictReader(csv_path.open(newline="", encoding="utf-8")))
    extra = [r for r in rows if r.get("point_id") in wanted]
    if len(extra) != len(wanted):
        found = {r.get("point_id") for r in extra}
        missing = sorted(wanted - found)
        print(f"Expected {len(wanted)} rows in {csv_path}, matched {len(extra)}; missing: {missing}", file=sys.stderr)
        return 1

    base = f"http://{args.host}"
    token = _login(base, args.user, password)
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
                "Edge bridge missing /api/bacnet/driver/merge-rows — deploy latest open-fdd, then re-run.",
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
