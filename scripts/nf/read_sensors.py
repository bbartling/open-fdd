#!/usr/bin/env python3
"""NF portal smoke: list latest values for explicit point UUIDs.

Wave-NF lab probe (Open-FDD ``scripts/nf/``). OAuth API key against ``NFURL``.
Selection is ``NF_POINT_UUIDS`` (comma-separated provider point ids). Display
names are not a selector.

Secrets from environment or ``.env`` next to this file (never commit).
Docs: https://docs.normal.dev/howto/auth/
Product path: Rust ``DataProvider`` NF driver — this script is smoke only.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import requests

UA = {"User-Agent": "openfdd-nf-point-smoke/1.0"}


def load_dotenv(directory: Path) -> None:
    for name in (".env", "api.env"):
        path = directory / name
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip().strip("'").strip('"'))


def bearer_token(base: str, client_id: str, client_secret: str) -> str:
    resp = requests.post(
        f"{base}/api/v1/auth/token",
        json={
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "client_credentials",
        },
        headers=UA,
        timeout=30,
    )
    if not resp.ok:
        raise SystemExit(f"token failed HTTP {resp.status_code}")
    body = resp.json()
    token = body.get("accessToken") or body.get("access_token")
    if not token:
        raise SystemExit("no accessToken in token response")
    return token


def query_points(base: str, token: str = "") -> list[dict]:
    headers = {**UA, "Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    resp = requests.post(
        f"{base}/api/v1/point/query",
        headers=headers,
        json={"pageSize": 200},
        timeout=60,
    )
    if not resp.ok:
        raise SystemExit(f"point/query failed HTTP {resp.status_code}")
    return list(resp.json().get("points") or [])


def selected_uuids() -> list[str]:
    raw = os.environ.get("NF_POINT_UUIDS", "")
    seen: set[str] = set()
    ordered: list[str] = []
    for part in raw.split(","):
        uuid = part.strip()
        if not uuid or uuid in seen:
            continue
        seen.add(uuid)
        ordered.append(uuid)
    return ordered


def main() -> int:
    here = Path(__file__).resolve().parent
    load_dotenv(here)

    base = os.environ.get("NFURL", "").rstrip("/")
    client_id = os.environ.get("NF_CLIENT_ID", "")
    client_secret = os.environ.get("NF_CLIENT_SECRET", "")
    if not base:
        print("Set NFURL (env or scripts/nf/.env).", file=sys.stderr)
        return 1

    want = selected_uuids()
    if not want:
        print(
            "Set NF_POINT_UUIDS to a comma-separated list of provider point UUIDs.",
            file=sys.stderr,
        )
        return 1

    token = ""
    if client_id and client_secret:
        token = bearer_token(base, client_id, client_secret)
    elif "normal-online.net" in base:
        print(
            "Cloudflare tunnel needs NF_CLIENT_ID + NF_CLIENT_SECRET.",
            file=sys.stderr,
        )
        return 1

    by_uuid: dict[str, dict] = {}
    for point in query_points(base, token):
        uuid = str(point.get("uuid") or point.get("id") or "").strip()
        if uuid:
            by_uuid[uuid] = point

    found = 0
    for uuid in want:
        point = by_uuid.get(uuid)
        if point is None:
            print(f"{uuid} missing", file=sys.stderr)
            continue
        attrs = point.get("attrs") or {}
        latest = point.get("latestValue") or {}
        units = point.get("units") or attrs.get("prop_units") or ""
        print(f"{uuid} {latest.get('double')} {units} @ {latest.get('ts')}")
        found += 1

    if found != len(want):
        print(f"matched {found} of {len(want)} point UUIDs", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
