#!/usr/bin/env python3
"""NF portal smoke: any internet host → Cloudflare tunnel → bosspi sensors.

Wave-NF lab probe (Open-FDD ``scripts/nf/``). OAuth API key against ``NFURL``
(bosspi ``*.normal-online.net``). Portal tunnel must be **Allow unauthenticated**;
NF still requires the API key for ``point/query``.

Secrets from environment or ``.env`` next to this file (never commit).
Docs: https://docs.normal.dev/howto/auth/
Product path: Rust ``DataProvider`` NF driver (Wave-NF mega plan) — this is smoke only.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import requests

# Bench policy: temp / humidity AI names on device 5007 (JCI FEC).
SENSORS = ("OA-T", "OA-H", "DUCT-T", "SSPLATE-T", "STAT ZN-T")
UA = {"User-Agent": "bldgts-part02-nf-sensors/1.0"}


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
        raise SystemExit(f"token failed HTTP {resp.status_code}: {resp.text[:400]}")
    body = resp.json()
    token = body.get("accessToken") or body.get("access_token")
    if not token:
        raise SystemExit(f"no accessToken in response: {body!r}")
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
        raise SystemExit(f"point/query failed HTTP {resp.status_code}: {resp.text[:400]}")
    return list(resp.json().get("points") or [])


def main() -> int:
    here = Path(__file__).resolve().parent
    load_dotenv(here)

    base = os.environ.get("NFURL", "").rstrip("/")
    client_id = os.environ.get("NF_CLIENT_ID", "")
    client_secret = os.environ.get("NF_CLIENT_SECRET", "")
    if not base:
        print("Set NFURL (env or checkpoint/.env).", file=sys.stderr)
        return 1

    # Tunnel / production: API key required. Lab LAN to bosspi often allows open query.
    token = ""
    if client_id and client_secret:
        token = bearer_token(base, client_id, client_secret)
    elif "normal-online.net" in base:
        print(
            "Cloudflare tunnel needs NF_CLIENT_ID + NF_CLIENT_SECRET "
            "(create on that NF site’s Settings → Authorization → API keys).",
            file=sys.stderr,
        )
        return 1

    want = set(SENSORS)
    found = 0
    for point in query_points(base, token):
        name = point.get("name") or ""
        if name not in want:
            continue
        attrs = point.get("attrs") or {}
        # Prefer physical AI sensors; still print if type missing after import quirks.
        ptype = attrs.get("type") or ""
        if ptype and ptype != "OBJECT_ANALOG_INPUT":
            continue
        latest = point.get("latestValue") or {}
        units = point.get("units") or attrs.get("prop_units") or ""
        print(f"{name:10} {latest.get('double')} {units} @ {latest.get('ts')}")
        found += 1

    if not found:
        print("no matching sensors — is NF polling those AIs?", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
