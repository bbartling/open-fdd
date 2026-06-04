#!/usr/bin/env python3
"""Build BRICK model JSON from a commissioned GL36 points CSV (any site)."""

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
API = REPO / "workspace" / "api"
sys.path.insert(0, str(API))
sys.path.insert(0, str(REPO / "scripts"))

os.environ.setdefault("OPENFDD_REPO_ROOT", str(REPO))
os.environ.setdefault("OFDD_DESKTOP_DATA_DIR", str(REPO / "workspace" / "data"))

from openfdd_bridge.model_service import ModelService  # noqa: E402
from openfdd_bridge.ttl_service import TtlService  # noqa: E402
from lib.site_pack_paths import equipment_id, model_json_path, points_csv  # noqa: E402


def _equip_type(system_id: str) -> str:
    s = system_id.lower()
    if "vav" in s or s.startswith("jci-vav") or s.startswith("trane-vav"):
        return "VAV"
    if "rtu" in s or "ahu" in s or s.startswith("pac"):
        return "AHU"
    if s == "hw-plant" or "hw" in s and "plant" in s:
        return "Hot_Water_Plant"
    if "tracer" in s or "supervisor" in s:
        return "Building_Supervisor"
    return "Equipment"


def _site_meta(rows: list[dict], site_id: str, building_id: str, site_name: str) -> tuple[str, str, str]:
    sid = site_id.strip() or (rows[0].get("site_id") or "").strip()
    bid = building_id.strip() or (rows[0].get("building_id") or "").strip()
    if not sid or not bid:
        raise SystemExit("site_id and building_id required (--site-id/--building-id or columns in CSV)")
    label = site_name.strip() or sid.replace("-", " ").title()
    return sid, bid, label


def build_model_from_csv(
    path: Path,
    *,
    site_id: str = "",
    building_id: str = "",
    site_name: str = "",
) -> dict:
    rows = list(csv.DictReader(path.open(newline="", encoding="utf-8")))
    if not rows:
        raise SystemExit(f"empty csv: {path}")

    sid, bid, label = _site_meta(rows, site_id, building_id, site_name)
    equipment: dict[str, dict] = {}
    points: list[dict] = []

    for r in rows:
        sys_id = r.get("system_id") or f"bacnet-{r.get('device_instance')}"
        eid = equipment_id(sid, bid, sys_id)
        if eid not in equipment:
            equipment[eid] = {
                "id": eid,
                "name": sys_id.replace("-", " ").title(),
                "brick_type": _equip_type(sys_id),
                "site_id": sid,
                "building_id": bid,
                "bacnet_device_instance": int(r["device_instance"]),
            }
        pid = (r.get("point_id") or "").strip()
        if not pid:
            continue
        points.append(
            {
                "id": pid,
                "name": r.get("object_name") or pid,
                "brick_type": r.get("brick_class") or "Point",
                "equipment_id": eid,
                "bacnet_object": f"{r.get('object_type')},{r.get('object_instance')}",
                "series_id": r.get("series_id") or "",
                "poll_interval_s": int(r.get("poll_interval_s") or 60),
                "units": r.get("units") or "",
                "brick_tag": r.get("brick_tag") or "",
            }
        )

    return {
        "site_id": sid,
        "building_id": bid,
        "sites": [{"id": sid, "name": label}],
        "equipment": list(equipment.values()),
        "points": points,
    }


def push_remote(base: str, token: str, payload: dict) -> dict:
    body = json.dumps({"payload": payload, "replace": True}).encode()
    req = urllib.request.Request(
        f"{base.rstrip('/')}/api/model/import",
        data=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())


def main() -> int:
    ap = argparse.ArgumentParser(description="Import GL36 points CSV into BRICK model.json")
    ap.add_argument("--site-id", default="")
    ap.add_argument("--building-id", default="")
    ap.add_argument("--site-name", default="", help="Display name for sites[] (default: title-case site id)")
    ap.add_argument("--csv", type=Path, default=None)
    ap.add_argument("--host", default="", help="Optional edge host to push model")
    ap.add_argument("--user", default="integrator")
    ap.add_argument("--password", default="")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    if args.csv and args.csv.is_file():
        csv_path = args.csv
    elif args.site_id and args.building_id:
        csv_path = points_csv(args.site_id, args.building_id)
    else:
        print("Provide --csv or --site-id and --building-id", file=sys.stderr)
        return 1

    if not csv_path.is_file():
        print(f"Points CSV not found: {csv_path}", file=sys.stderr)
        return 1

    sid = args.site_id or ""
    bid = args.building_id or ""
    payload = build_model_from_csv(csv_path, site_id=sid, building_id=bid, site_name=args.site_name)
    out_path = args.out or model_json_path(payload["site_id"], payload["building_id"])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {out_path} equipment={len(payload['equipment'])} points={len(payload['points'])}")

    svc = ModelService()
    counts = svc.import_json(payload, replace=True)
    TtlService().sync()
    print(f"Local model import: {counts}")

    if args.host:
        pw = args.password or os.environ.get("OFDD_INTEGRATOR_PASSWORD", "")
        if not pw:
            print("Set --password or OFDD_INTEGRATOR_PASSWORD for remote push", file=sys.stderr)
            return 1
        login = json.dumps({"username": args.user, "password": pw}).encode()
        lr = urllib.request.Request(
            f"http://{args.host}/api/auth/login",
            data=login,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        token = json.loads(urllib.request.urlopen(lr, timeout=30).read())["token"]
        try:
            print("Remote import:", push_remote(f"http://{args.host}", token, payload))
            sync_req = urllib.request.Request(
                f"http://{args.host}/api/model/bacnet-sync",
                data=b"{}",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                method="POST",
            )
            print("Remote sync:", json.loads(urllib.request.urlopen(sync_req, timeout=120).read()))
        except urllib.error.HTTPError as exc:
            print("Remote push failed:", exc.read().decode(), file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
