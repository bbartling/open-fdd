#!/usr/bin/env python3
"""Live NF portal check. GET history only. Never POST /api/v1/point/data.

The owner's machine runs this after the GHCR refresh. This agent does not have
the portal credentials.

Portal read (required):

    export NFURL=https://<portal>
    export NF_CLIENT_ID=...
    export NF_CLIENT_SECRET=...
    python3 scripts/nf/validate_live.py

``NF_POINT_UUIDS`` (comma-separated) is required unless ``--sites`` supplies UUIDs
from a provider site file. The read is the last
completed hour: ``GET /api/v1/point/data?from.seconds=&to.seconds=&uuids=``.

Central check (optional, after the hourly worker has run):

    export OPENFDD_CENTRAL_URL=http://127.0.0.1:8080
    export OPENFDD_ADMIN_USER=admin
    export OPENFDD_ADMIN_PASSWORD=...
    export OPENFDD_PROVIDER_BUILDING_ID=<building_id>
    python3 scripts/nf/validate_live.py

That logs in, reads ``GET /api/providers/health``, and requires
``last_success_at``, ``last_ingested_points`` > 0, and no ``last`` error on
that building. It also requires the building on
``GET /api/csv/import/package/buildings``.

Fast lab tick (central process only, not this script):

    OPENFDD_PROVIDER_POLL=1
    OPENFDD_PROVIDER_TICK_SECS=15
    OPENFDD_HOURLY_WINDOW_SECS=60

Production leaves the window at 3600 seconds. Shorten it only while validating.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UA = "openfdd-nf-validate-live/1.0"


def die(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def default_uuids() -> list[str]:
    raw = os.environ.get("NF_POINT_UUIDS", "").strip()
    if raw:
        return [part.strip() for part in raw.split(",") if part.strip()]
    sites_path = os.environ.get("NF_SITES_PATH", "").strip()
    if not sites_path:
        die("set NF_POINT_UUIDS or NF_SITES_PATH to a provider site JSON file")
    path = Path(sites_path).expanduser()
    if not path.is_file():
        die(f"NF_SITES_PATH not found: {path}")
    sites = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(sites, dict):
        sites = [sites]
    uuids = []
    for site in sites:
        for point in site.get("point_map") or []:
            uuid = str(point.get("provider_point_id") or "").strip()
            if uuid and uuid not in uuids:
                uuids.append(uuid)
    if not uuids:
        die(f"no provider_point_id entries in {path}")
    return uuids


def request_json(url: str, method: str, body: dict | None, headers: dict[str, str]) -> dict:
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method, headers={"User-Agent": UA, **headers})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = resp.read().decode("utf-8")
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", errors="replace")[:300]
        die(f"{method} {url} failed HTTP {err.code}: {detail}")
    return json.loads(payload) if payload else {}


def completed_hour(now: datetime) -> tuple[datetime, datetime]:
    window = int(os.environ.get("OPENFDD_HOURLY_WINDOW_SECS", "3600"))
    window = min(3600, max(60, window))
    end_epoch = int(now.timestamp()) - (int(now.timestamp()) % window)
    end = datetime.fromtimestamp(end_epoch, tz=timezone.utc)
    return end - timedelta(seconds=window), end


def read_portal(base: str, uuids: list[str]) -> int:
    client_id = os.environ.get("NF_CLIENT_ID", "").strip()
    secret = os.environ.get("NF_CLIENT_SECRET", "").strip()
    if not client_id or not secret:
        die("NF_CLIENT_ID and NF_CLIENT_SECRET are required")
    token_body = request_json(
        f"{base}/api/v1/auth/token",
        "POST",
        {
            "client_id": client_id,
            "client_secret": secret,
            "grant_type": "client_credentials",
        },
        {"Content-Type": "application/json"},
    )
    token = token_body.get("accessToken") or token_body.get("access_token")
    if not token:
        die("token response had no accessToken")
    start, end = completed_hour(datetime.now(timezone.utc))
    query = urllib.parse.urlencode(
        {
            "from.seconds": str(int(start.timestamp())),
            "to.seconds": str(int(end.timestamp())),
        }
    )
    for uuid in uuids:
        query += "&uuids=" + urllib.parse.quote(uuid)
    url = f"{base}/api/v1/point/data?{query}"
    if "point/data" in url and url.startswith("POST"):
        die("refusing to POST point/data")
    body = request_json(
        url,
        "GET",
        None,
        {"Authorization": f"Bearer {token}"},
    )
    series = body.get("data") or body.get("series") or []
    points = 0
    for item in series:
        points += len(item.get("values") or [])
    print(
        f"portal GET {start.isoformat()} .. {end.isoformat()} "
        f"uuids={len(uuids)} values={points}"
    )
    if points <= 0:
        die("portal returned no values for the last completed hour")
    return points


def central_token(base: str) -> str:
    user = os.environ.get("OPENFDD_ADMIN_USER", "admin")
    password = os.environ.get("OPENFDD_ADMIN_PASSWORD", "")
    if not password:
        die("OPENFDD_ADMIN_PASSWORD is required when OPENFDD_CENTRAL_URL is set")
    body = request_json(
        f"{base}/api/auth/login",
        "POST",
        {"username": user, "password": password},
        {"Content-Type": "application/json"},
    )
    token = body.get("token") or body.get("access_token")
    if not token:
        die("central login returned no token")
    return token


def check_central(base: str, building_id: str) -> None:
    token = central_token(base)
    auth = {"Authorization": f"Bearer {token}"}
    health = request_json(f"{base}/api/providers/health", "GET", None, auth)
    sites = health.get("sites") or []
    match = next((site for site in sites if site.get("building_id") == building_id), None)
    if match is None:
        die(f"central provider health has no site {building_id}")
    ingested = int(match.get("last_ingested_points") or 0)
    success = (match.get("health") or {}).get("last_success_at")
    error = (match.get("health") or {}).get("message")
    print(
        f"central {building_id} last_success_at={success} "
        f"last_ingested_points={ingested} last_error={error}"
    )
    if not success or ingested <= 0 or error:
        die("central has not recorded a clean hourly pull for this site yet")
    buildings = request_json(
        f"{base}/api/csv/import/package/buildings", "GET", None, auth
    )
    listed = buildings.get("buildings") or []
    if building_id not in listed:
        die(f"{building_id} is missing from package buildings: {listed}")
    print(f"central lists {building_id}")


def main() -> int:
    base = os.environ.get("NFURL", "").strip().rstrip("/")
    if not base:
        die("NFURL is required")
    uuids = default_uuids()
    read_portal(base, uuids)
    central = os.environ.get("OPENFDD_CENTRAL_URL", "").strip().rstrip("/")
    if central:
        building_id = os.environ.get("OPENFDD_PROVIDER_BUILDING_ID", "BOSSPI").strip()
        check_central(central, building_id)
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
