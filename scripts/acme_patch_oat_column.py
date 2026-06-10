#!/usr/bin/env python3
"""Ensure Acme local OAT historian column is ``oa-t`` for weather cross-check rules.

Sets ``external_id`` and ``fdd_input`` on the RTU local outdoor-air point
(``1100-unknown-2`` by default). Boiler-wired OAT can be substituted via
``--point-id`` when that BACnet object is commissioned instead.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
API = REPO / "workspace" / "api"
sys.path.insert(0, str(API))
sys.path.insert(0, str(REPO))

os.environ.setdefault("OPENFDD_REPO_ROOT", str(REPO))
os.environ.setdefault("OFDD_DESKTOP_DATA_DIR", str(REPO / "workspace" / "data"))


def _patch_local(model: dict, point_id: str, alias: str) -> bool:
    changed = False
    for pt in model.get("points") or []:
        if str(pt.get("id") or "") != point_id:
            continue
        if str(pt.get("external_id") or "") != alias:
            pt["external_id"] = alias
            changed = True
        if str(pt.get("fdd_input") or "") != alias:
            pt["fdd_input"] = alias
            changed = True
        break
    return changed


def _push_model(base: str, token: str, model: dict) -> None:
    body = json.dumps({"payload": model, "replace": False}).encode()
    req = urllib.request.Request(
        f"{base.rstrip('/')}/api/model/import",
        data=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        print(f"Model import HTTP {resp.status}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Patch Acme OAT point alias to oa-t")
    parser.add_argument("--point-id", default="1100-unknown-2", help="BACnet point id for local OAT")
    parser.add_argument("--alias", default="oa-t")
    parser.add_argument("--host", default="")
    parser.add_argument("--token", default="")
    args = parser.parse_args()

    from openfdd_bridge.model_service import ModelService  # noqa: E402

    svc = ModelService()
    model = svc.load()
    if not _patch_local(model, args.point_id, args.alias):
        print(f"No change needed for {args.point_id} (already {args.alias})")
        return 0
    svc.import_json(model, replace=True)
    print(f"Patched local model: {args.point_id} → external_id/fdd_input={args.alias}")
    if args.host and args.token:
        _push_model(f"http://{args.host}", args.token, model)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
