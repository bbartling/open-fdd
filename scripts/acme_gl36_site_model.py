#!/usr/bin/env python3
"""Import full Acme site BRICK model from commissioned GL36 points CSV."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
API = REPO / "workspace" / "api"
if str(API) not in sys.path:
    sys.path.insert(0, str(API))

os.environ.setdefault("OPENFDD_REPO_ROOT", str(REPO))
os.environ.setdefault("OFDD_DESKTOP_DATA_DIR", str(REPO / "workspace" / "data"))

from openfdd_bridge.model_service import ModelService  # noqa: E402
from openfdd_bridge.ttl_service import TtlService  # noqa: E402

POINTS_CSV = REPO / "edge_backup/local/acme/vm-bbartling/points.gl36_poll.csv"
FALLBACK_CSV = REPO / "edge_backup/local/acme/vm-bbartling/points.csv"


def _equip_type(system_id: str) -> str:
    s = system_id.lower()
    if "vav" in s or s.startswith("jci-vav") or s.startswith("trane-vav"):
        return "VAV"
    if s == "rtu-01":
        return "AHU"
    if s == "hw-plant":
        return "Hot_Water_Plant"
    if s == "tracer-sc":
        return "Building_Supervisor"
    return "Equipment"


def build_model_from_csv(path: Path) -> dict:
    rows = list(csv.DictReader(path.open(newline="", encoding="utf-8")))
    if not rows:
        raise SystemExit(f"empty csv: {path}")

    equipment: dict[str, dict] = {}
    points: list[dict] = []

    for r in rows:
        sid = r.get("system_id") or f"bacnet-{r.get('device_instance')}"
        eid = f"acme-vm-bbartling-{sid}"
        if eid not in equipment:
            equipment[eid] = {
                "id": eid,
                "name": sid.replace("-", " ").title(),
                "brick_type": _equip_type(sid),
                "site_id": r.get("site_id") or "acme",
                "building_id": r.get("building_id") or "vm-bbartling",
                "bacnet_device_instance": int(r["device_instance"]),
            }
        pid = r.get("point_id") or ""
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
        "site_id": "acme",
        "building_id": "vm-bbartling",
        "sites": [{"id": "acme", "name": "Acme Building"}],
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
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", type=Path, default=POINTS_CSV)
    ap.add_argument("--host", default="", help="optional edge host to push model")
    ap.add_argument("--user", default="integrator")
    ap.add_argument("--password", default="")
    ap.add_argument("--out", type=Path, default=REPO / "workspace/data/acme_gl36_model.json")
    args = ap.parse_args()

    csv_path = args.csv if args.csv.is_file() else FALLBACK_CSV
    payload = build_model_from_csv(csv_path)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {args.out} equipment={len(payload['equipment'])} points={len(payload['points'])}")

    svc = ModelService()
    counts = svc.import_json(payload, replace=True)
    TtlService().sync()
    print(f"Local model import: {counts}")

    if args.host:
        pw = args.password or os.environ.get("OFDD_INTEGRATOR_PASSWORD", "")
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
