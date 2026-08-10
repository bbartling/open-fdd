#!/usr/bin/env python3
"""Capture Open-FDD *Rust* product surfaces for WattLab parity bug-hunting.

Does NOT call tools/wattlab_export or OPENFDD_WATTLAB_PYTHON_EXPORT.
Hits central JWT APIs: session-config, schedule analytics, runtime, FDD results.

Gate 0: PUT occupancy_schedule into session-config. If the running image still
strips the key (pre-patch nightly), restore it on the workspace bind-mount so
compare artifacts are still Gate-0-equal while BUG-C remains filed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCHED = ROOT / "reports/wattlab-parity/fixtures/schedule_b100_7to5.json"
DEFAULT_OUT = ROOT / "reports/wattlab-parity/artifacts/ofdd_rust"
DEFAULT_BASE = os.environ.get("OPENFDD_API_BASE", "http://127.0.0.1:8080")
DEFAULT_SESSION = ROOT / "workspace/data/session_config.json"


def _req(
    method: str,
    url: str,
    *,
    token: str | None,
    body: dict | None = None,
) -> tuple[int, dict | list | str]:
    data = None
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    r = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=120) as resp:
            raw = resp.read().decode("utf-8")
            try:
                return resp.status, json.loads(raw)
            except json.JSONDecodeError:
                return resp.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, raw


def login(base: str, password: str) -> str | None:
    st, body = _req(
        "POST",
        f"{base}/api/auth/login",
        token=None,
        body={"username": "admin", "password": password},
    )
    if st == 200 and isinstance(body, dict) and body.get("token"):
        return str(body["token"])
    return None


def _write_json(path: Path, obj: object) -> None:
    path.write_text(json.dumps(obj, indent=2), encoding="utf-8")


def restore_schedule_on_disk(session_path: Path, sched: dict) -> bool:
    """Nightly workaround: write occupancy_schedule into bind-mounted session file."""
    if not session_path.is_file():
        return False
    try:
        cfg = json.loads(session_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    if not isinstance(cfg, dict):
        return False
    cfg["occupancy_schedule"] = sched
    params = dict(cfg.get("params") or {})
    params["SCHED-1"] = {
        **(params.get("SCHED-1") or {}),
        "bare_min_occ_hours_week": float(sched.get("nominal_occ_hours_week") or 50),
    }
    cfg["params"] = params
    session_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return True


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base", default=DEFAULT_BASE)
    p.add_argument("--building-id", default="BUILDING_100")
    p.add_argument("--schedule", type=Path, default=DEFAULT_SCHED)
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    p.add_argument("--session-path", type=Path, default=DEFAULT_SESSION)
    p.add_argument(
        "--admin-password",
        default=os.environ.get("OPENFDD_ADMIN_PASSWORD", ""),
    )
    args = p.parse_args()

    if not args.schedule.is_file():
        print(f"schedule not found: {args.schedule}", file=sys.stderr)
        return 2

    sched = json.loads(args.schedule.read_text(encoding="utf-8"))
    args.out.mkdir(parents=True, exist_ok=True)

    token = None
    if args.admin_password:
        token = login(args.base, args.admin_password)

    st, health = _req("GET", f"{args.base}/api/health", token=token)
    _write_json(args.out / "health.json", {"status": st, "body": health})
    if st != 200:
        print(f"central not healthy at {args.base}: {st} {health}", file=sys.stderr)
        return 3

    st, prev = _req("GET", f"{args.base}/api/fdd/session-config", token=token)
    cfg = {}
    if isinstance(prev, dict) and isinstance(prev.get("config"), dict):
        cfg = dict(prev["config"])
    cfg["schema_version"] = cfg.get("schema_version") or "openfdd_session_v1"
    cfg["unit_system"] = cfg.get("unit_system") or "imperial"
    cfg["occupancy_schedule"] = sched
    params = dict(cfg.get("params") or {})
    params["SCHED-1"] = {
        **(params.get("SCHED-1") or {}),
        "bare_min_occ_hours_week": float(sched.get("nominal_occ_hours_week") or 50),
    }
    cfg["params"] = params
    st, put_body = _req(
        "PUT",
        f"{args.base}/api/fdd/session-config",
        token=token,
        body={"config": cfg},
    )
    _write_json(args.out / "session_config_put.json", {"status": st, "body": put_body})
    st, got = _req("GET", f"{args.base}/api/fdd/session-config", token=token)
    _write_json(args.out / "session_config.json", {"status": st, "body": got})

    parity = None
    if isinstance(got, dict):
        parity = (got.get("config") or {}).get("occupancy_schedule")
    put_kept = bool(parity)
    disk_restored = False
    if not put_kept:
        disk_restored = restore_schedule_on_disk(args.session_path, sched)
        if disk_restored:
            st, got = _req("GET", f"{args.base}/api/fdd/session-config", token=token)
            _write_json(
                args.out / "session_config_after_disk_restore.json",
                {"status": st, "body": got},
            )
            if isinstance(got, dict):
                parity = (got.get("config") or {}).get("occupancy_schedule")

    _write_json(args.out / "parity_schedule.json", parity or {})

    for name, path, body in (
        (
            "schedule",
            "/api/analytics/schedule",
            {"building_id": args.building_id},
        ),
        (
            "runtime",
            "/api/analytics/runtime",
            {"building_id": args.building_id},
        ),
        (
            "sensor_health",
            "/api/analytics/sensor-health",
            {"building_id": args.building_id},
        ),
    ):
        st, env = _req("POST", f"{args.base}{path}", token=token, body=body)
        _write_json(args.out / f"{name}.json", {"status": st, "body": env})

    st, fdd = _req(
        "GET",
        f"{args.base}/api/fdd/results?building_id={args.building_id}",
        token=token,
    )
    _write_json(args.out / "fdd_results.json", {"status": st, "body": fdd})

    meta = {
        "side": "ofdd_rust",
        "base": args.base,
        "building_id": args.building_id,
        "schedule": str(args.schedule),
        "note": "Rust APIs only — no Python WattLab export",
        "gate0_occupancy_schedule_persisted": bool(parity),
        "gate0_put_kept_occupancy_schedule": put_kept,
        "gate0_disk_restore_used": disk_restored,
        "health_version": (
            health.get("version") if isinstance(health, dict) else None
        ),
    }
    _write_json(args.out / "parity_meta.json", meta)
    print(f"ofdd rust capture -> {args.out}")
    print(f"gate0 schedule present: {bool(parity)} (put_kept={put_kept}, disk_restore={disk_restored})")
    return 0 if parity else 4


if __name__ == "__main__":
    raise SystemExit(main())
