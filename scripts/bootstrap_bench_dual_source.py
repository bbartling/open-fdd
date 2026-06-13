#!/usr/bin/env python3
"""Bootstrap local bench: native BACnet 5007 + Niagara baskStream (read-only).

Run from repo root on benserver:
  export OPENFDD_NIAGARA_ADMIN_PASSWORD='…'
  python3 scripts/bootstrap_bench_dual_source.py
  python3 scripts/bootstrap_bench_dual_source.py --skip-bacnet-discover
  python3 scripts/bootstrap_bench_dual_source.py --api http://127.0.0.1:8765
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
API = REPO / "workspace" / "api"
if str(API) not in sys.path:
    sys.path.insert(0, str(API))

os.environ.setdefault("OPENFDD_REPO_ROOT", str(REPO))
os.environ.setdefault("OPENFDD_WORKSPACE_DIR", str(REPO / "workspace"))
os.environ.setdefault("OFDD_DESKTOP_DATA_DIR", str(REPO / "workspace" / "data"))

NIAGARA_STATION = {
    "id": "bench9065",
    "name": "Bench Station 9065",
    "station_url": "https://192.168.204.11",
    "username": "admin",
    "password_env": "OPENFDD_NIAGARA_ADMIN_PASSWORD",
    "verify_tls": False,
    "enabled": True,
    "root_ord": "slot:/Drivers",
    "default_points_root": "slot:/Drivers/BacnetNetwork/BENS$20BENCHTEST$20BOX/points",
    "poll_interval_seconds": 60,
    "read_batch_size": 50,
    "include_proxy_ext": False,
    "follow_external": False,
}


def _fetch(method: str, base: str, path: str, token: str | None = None, body: dict | None = None) -> tuple[int, dict]:
    url = f"{base.rstrip('/')}{path}"
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, json.loads(raw)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"detail": raw}


def _login(base: str) -> str:
    auth = REPO / "workspace" / "auth.env.local"
    if auth.is_file():
        for line in auth.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    user = os.environ.get("OFDD_INTEGRATOR_USER", os.environ.get("OFDD_OPERATOR_USER", "operator"))
    password = os.environ.get("OFDD_INTEGRATOR_PASSWORD", os.environ.get("OFDD_OPERATOR_PASSWORD", "changeme"))
    status, body = _fetch("POST", base, "/api/auth/login", body={"username": user, "password": password})
    if status != 200:
        print(f"login failed HTTP {status}: {body}", file=sys.stderr)
        return ""
    return str(body.get("token") or "")


def bootstrap_direct(*, skip_bacnet_discover: bool) -> dict:
    """Configure BACnet bench via existing scripts + model import."""
    results: dict = {"bacnet": {}, "model": {}}
    if not skip_bacnet_discover:
        script = REPO / "scripts" / "apply_bench_four_points.sh"
        if script.is_file():
            subprocess.run([str(script), "--import-model"], check=False, cwd=REPO)
            results["bacnet"]["apply_bench_four_points"] = "ran"
        else:
            setup = REPO / "scripts" / "setup_local_testbench.sh"
            if setup.is_file():
                subprocess.run([str(setup), "--skip-discover"], check=False, cwd=REPO)
                results["bacnet"]["setup_local_testbench"] = "ran --skip-discover"
    from openfdd_bridge.model_service import ModelService  # noqa: E402
    from openfdd_bridge.ttl_service import TtlService  # noqa: E402

    model_path = REPO / "workspace" / "data" / "bench_dual_source_model.json"
    if model_path.is_file():
        payload = json.loads(model_path.read_text(encoding="utf-8"))
        results["model"] = ModelService().import_json(payload, replace=False)
        TtlService().sync()
    return results


def bootstrap_niagara_direct() -> dict:
    from openfdd_bridge.niagara_store import set_poll_running, upsert_station  # noqa: E402
    from openfdd_bridge.niagara_service import discover_points, test_station  # noqa: E402
    import asyncio

    if not os.environ.get("OPENFDD_NIAGARA_ADMIN_PASSWORD"):
        return {"error": "OPENFDD_NIAGARA_ADMIN_PASSWORD not set"}

    station = upsert_station(NIAGARA_STATION)

    async def run():
        test = await test_station(station["id"])
        disc = await discover_points(station["id"])
        return {"test": test, "discover": {"count": disc.get("count"), "base": disc.get("base")}}

    out = asyncio.run(run())
    set_poll_running(station["id"], True)
    out["poll_started"] = True
    out["station_id"] = station["id"]
    return out


def bootstrap_via_api(base: str, token: str) -> dict:
    out: dict = {}
    status, body = _fetch("PUT", base, f"/api/niagara/stations/{NIAGARA_STATION['id']}", token, NIAGARA_STATION)
    out["niagara_upsert"] = {"status": status, "body": body}
    status, body = _fetch("POST", base, f"/api/niagara/stations/{NIAGARA_STATION['id']}/test", token)
    out["niagara_test"] = {"status": status, "ok": body.get("ok")}
    status, body = _fetch(
        "POST",
        base,
        f"/api/niagara/stations/{NIAGARA_STATION['id']}/discover",
        token,
        {"base": NIAGARA_STATION["default_points_root"]},
    )
    out["niagara_discover"] = {"status": status, "count": body.get("count")}
    status, body = _fetch("POST", base, f"/api/niagara/stations/{NIAGARA_STATION['id']}/poll/start", token)
    out["niagara_poll"] = {"status": status, "running": body.get("running")}
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap bench BACnet + Niagara (read-only)")
    parser.add_argument("--skip-bacnet-discover", action="store_true")
    parser.add_argument("--api", default="", help="Bridge base URL; if set, use REST for Niagara")
    parser.add_argument("--niagara-only", action="store_true")
    args = parser.parse_args()

    report: dict = {"ok": True, "steps": {}}
    if not args.niagara_only:
        report["steps"]["bacnet_model"] = bootstrap_direct(skip_bacnet_discover=args.skip_bacnet_discover)

    if args.api:
        token = _login(args.api)
        if not token:
            return 1
        report["steps"]["niagara_api"] = bootstrap_via_api(args.api, token)
    else:
        report["steps"]["niagara_direct"] = bootstrap_niagara_direct()

    print(json.dumps(report, indent=2))
    if report["steps"].get("niagara_direct", {}).get("error"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
