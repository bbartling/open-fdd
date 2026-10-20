#!/usr/bin/env python3
"""Post-deploy check for the Building 50 hub UI P0s.

Hits the deployed web or central API. Credentials come from the environment.
Nothing in this file is a password.

    export OPENFDD_BASE_URL=https://<web-or-central>
    export OPENFDD_ADMIN_USER=admin
    export OPENFDD_ADMIN_PASSWORD=...
    python3 scripts/validate/ui_timescale_smoke.py

OPENFDD_CENTRAL_URL is accepted as an alias of OPENFDD_BASE_URL.
OPENFDD_BUILDING_ID defaults to BUILDING_50.
OPENFDD_PROVIDER_BUILDING_ID defaults to BOSSPI.

Checks:
- GET /api/health reports historian=timescale and timescale_ok
- Building 50 inspect trends return sample rows
- starter rule results are not all NOT_APPLICABLE
- BOSSPI has at least one sample timestamp in the last 2 hours
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

STARTER = (
    "FC1",
    "AHU-SATDEV",
    "AHU-DUCTHI",
    "FAN-RUNTIME-HOURS",
    "FC10",
    "FC12",
    "CHW-1",
)
UA = "openfdd-ui-timescale-smoke/1.0"


def die(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def request_json(url: str, method: str, body: dict | None, headers: dict[str, str]) -> dict:
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, **headers}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", errors="replace")[:500]
        die(f"{method} {url} -> HTTP {err.code}: {detail}")
    except urllib.error.URLError as err:
        die(f"{method} {url} failed: {err}")
    try:
        parsed = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        die(f"{method} {url} returned non-JSON")
    if not isinstance(parsed, dict):
        die(f"{method} {url} returned {type(parsed).__name__}, expected an object")
    return parsed


def login(base: str) -> str:
    user = os.environ.get("OPENFDD_ADMIN_USER", "admin").strip() or "admin"
    password = os.environ.get("OPENFDD_ADMIN_PASSWORD", "")
    if not password:
        die("OPENFDD_ADMIN_PASSWORD is required")
    body = request_json(
        f"{base}/api/auth/login",
        "POST",
        {"username": user, "password": password},
        {"Content-Type": "application/json"},
    )
    token = body.get("token") or body.get("access_token")
    if not token:
        die("login returned no token")
    return str(token)


def parse_ts(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def equipment_ids(base: str, auth: dict[str, str], building_id: str) -> list[str]:
    listed = request_json(
        f"{base}/api/fdd/equipment?building_id={building_id}",
        "GET",
        None,
        auth,
    )
    ids = [
        str(row.get("equipment_id"))
        for row in listed.get("equipment") or []
        if row.get("equipment_id")
    ]
    if ids:
        return ids
    mapped = request_json(
        f"{base}/api/csv/import/package/mapping?building_id={building_id}",
        "GET",
        None,
        auth,
    )
    return [
        str(row.get("equipment_id"))
        for row in mapped.get("equipment") or []
        if row.get("equipment_id")
    ]


def inspect(base: str, auth: dict[str, str], building_id: str, equipment_id: str) -> dict:
    return request_json(
        f"{base}/api/analytics/inspect",
        "POST",
        {
            "building_id": building_id,
            "equipment_ids": [equipment_id],
            "max_points": 500,
        },
        {**auth, "Content-Type": "application/json"},
    )


def point_count(env: dict) -> int:
    points = env.get("points")
    if isinstance(points, list):
        return len(points)
    coverage = env.get("coverage") if isinstance(env.get("coverage"), dict) else {}
    try:
        return int(coverage.get("point_count") or coverage.get("row_count") or 0)
    except (TypeError, ValueError):
        return 0


def newest_point(env: dict) -> datetime | None:
    newest: datetime | None = None
    coverage = env.get("coverage") if isinstance(env.get("coverage"), dict) else {}
    for value in (coverage.get("last_timestamp"),):
        parsed = parse_ts(value)
        if parsed and (newest is None or parsed > newest):
            newest = parsed
    for row in env.get("points") or []:
        if not isinstance(row, dict):
            continue
        parsed = parse_ts(row.get("timestamp_utc") or row.get("ts"))
        if parsed and (newest is None or parsed > newest):
            newest = parsed
    return newest


def check_health(base: str, auth: dict[str, str]) -> None:
    health = request_json(f"{base}/api/health", "GET", None, auth)
    historian = health.get("historian")
    timescale_ok = health.get("timescale_ok")
    print(f"health historian={historian} timescale_ok={timescale_ok}")
    if historian != "timescale" or timescale_ok is not True:
        die("health does not report the Timescale historian as connected")


def check_building_trends(base: str, auth: dict[str, str], building_id: str) -> None:
    ids = equipment_ids(base, auth, building_id)
    if not ids:
        die(f"{building_id} has no Timescale equipment to trend")
    env = inspect(base, auth, building_id, ids[0])
    count = point_count(env)
    print(f"{building_id} inspect {ids[0]} points={count}")
    if count <= 0:
        die(f"{building_id} trend data returned no rows")


def check_rules(base: str, auth: dict[str, str], building_id: str) -> None:
    body = request_json(
        f"{base}/api/fdd/results?building_id={building_id}",
        "GET",
        None,
        auth,
    )
    rows = [
        row
        for row in body.get("results") or []
        if str(row.get("rule_id")) in STARTER
    ]
    if not rows:
        die(f"{building_id} has no starter-rule results")
    na = [
        row
        for row in rows
        if "NOT_APPLICABLE" in str(row.get("status") or "").upper()
    ]
    real = [
        row
        for row in rows
        if str(row.get("status") or "").upper() in {"PASS", "FAULT", "METRIC"}
    ]
    print(
        f"{building_id} starter results={len(rows)} "
        f"pass_fault_metric={len(real)} not_applicable={len(na)}"
    )
    if len(na) == len(rows) or not real:
        die("starter rule results are all NOT_APPLICABLE")


def check_provider_recent(base: str, auth: dict[str, str], building_id: str) -> None:
    ids = equipment_ids(base, auth, building_id)
    if not ids:
        die(f"{building_id} has no equipment after the hourly pull")
    cutoff = datetime.now(timezone.utc) - timedelta(hours=2)
    newest: datetime | None = None
    for equipment_id in ids:
        env = inspect(base, auth, building_id, equipment_id)
        stamp = newest_point(env)
        if stamp and (newest is None or stamp > newest):
            newest = stamp
        if stamp and stamp >= cutoff:
            print(f"{building_id} {equipment_id} newest={stamp.isoformat()}")
            return
    die(
        f"{building_id} has no sample in the last 2 hours "
        f"(newest={newest.isoformat() if newest else 'none'})"
    )


def main() -> int:
    base = (
        os.environ.get("OPENFDD_BASE_URL")
        or os.environ.get("OPENFDD_CENTRAL_URL")
        or os.environ.get("OPENFDD_WEB_URL")
        or ""
    ).strip().rstrip("/")
    if not base:
        die("OPENFDD_BASE_URL (or OPENFDD_CENTRAL_URL) is required")
    token = login(base)
    auth = {"Authorization": f"Bearer {token}"}
    building_id = os.environ.get("OPENFDD_BUILDING_ID", "BUILDING_50").strip() or "BUILDING_50"
    provider_id = os.environ.get("OPENFDD_PROVIDER_BUILDING_ID", "BOSSPI").strip() or "BOSSPI"
    check_health(base, auth)
    check_building_trends(base, auth, building_id)
    check_rules(base, auth, building_id)
    check_provider_recent(base, auth, provider_id)
    print("OK ui timescale smoke")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
