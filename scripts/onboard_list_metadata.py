#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _onboard_cli import fallback_api_key_from_env_files


def _request_json(base_url: str, api_key: str, path: str) -> list[dict]:
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        headers={"X-OB-Api": api_key, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data if isinstance(data, list) else []


def main() -> int:
    parser = argparse.ArgumentParser(description="List Onboard buildings + points metadata")
    parser.add_argument("--api-base-url", default=os.getenv("OFDD_ONBOARD_API_BASE_URL", "https://api.onboarddata.io"))
    parser.add_argument("--api-key", default=os.getenv("OFDD_ONBOARD_API_KEY", ""))
    parser.add_argument("--building", action="append", default=[])
    args = parser.parse_args()

    api_key = args.api_key.strip() or fallback_api_key_from_env_files()
    if not api_key:
        print("Missing API key. Set --api-key or OFDD_ONBOARD_API_KEY.", file=sys.stderr)
        return 1

    buildings = _request_json(args.api_base_url, api_key, "/buildings")
    filters = {str(v).strip() for v in args.building if str(v).strip()}
    if filters:
        buildings = [b for b in buildings if str(b.get("id", "")).strip() in filters or str(b.get("name", "")).strip() in filters]

    out: list[dict] = []
    for b in buildings:
        b_id = b.get("id")
        if b_id is None:
            continue
        points = _request_json(args.api_base_url, api_key, f"/buildings/{int(b_id)}/points")
        out.append({"building_id": b_id, "name": b.get("name"), "point_count": len(points), "sample_points": points[:5]})
    print(json.dumps({"buildings": out}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
