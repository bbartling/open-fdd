#!/usr/bin/env python3
"""Smoke battery: BACnet + Modbus + JSON API → feather → BRICK → FDD + agent + browser setup views.

Run from repo root (bridge at http://127.0.0.1:8765):
  python3 scripts/smoke_multi_driver_stack.py
  python3 scripts/smoke_multi_driver_stack.py --skip-modbus-server
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
API = REPO / "workspace" / "api"
if str(API) not in sys.path:
    sys.path.insert(0, str(API))

os.environ.setdefault("OPENFDD_REPO_ROOT", str(REPO))
os.environ.setdefault("OPENFDD_WORKSPACE_DIR", str(REPO / "workspace"))
os.environ.setdefault("OFDD_DESKTOP_DATA_DIR", str(REPO / "workspace" / "data"))

BASE = os.environ.get("OPENFDD_BASE_URL", "http://127.0.0.1:8765").rstrip("/")
AUTH_ENV = REPO / "workspace" / "auth.env.local"
FAILURES = 0
MODBUS_PORT = 5502


def ok(msg: str) -> None:
    print(f"  OK   {msg}")


def fail(msg: str) -> None:
    global FAILURES
    FAILURES += 1
    print(f"  FAIL {msg}", file=sys.stderr)


def _load_auth() -> tuple[str, str, str, str]:
    if AUTH_ENV.is_file():
        for line in AUTH_ENV.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())
    op_u = os.environ.get("OFDD_OPERATOR_USER", "operator")
    op_p = os.environ.get("OFDD_OPERATOR_PASSWORD", "changeme")
    int_u = os.environ.get("OFDD_INTEGRATOR_USER", op_u)
    int_p = os.environ.get("OFDD_INTEGRATOR_PASSWORD", op_p)
    return op_u, op_p, int_u, int_p


def _fetch(
    method: str,
    path: str,
    *,
    token: str | None = None,
    body: dict | None = None,
    timeout: float = 30.0,
) -> tuple[int, dict | str]:
    url = f"{BASE}{path}"
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(raw)
            except json.JSONDecodeError:
                return resp.status, raw
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, raw
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        return 0, {"error": str(exc)}


def login(user: str, password: str) -> str:
    status, body = _fetch("POST", "/api/auth/login", body={"username": user, "password": password})
    if status != 200 or not isinstance(body, dict) or not body.get("token"):
        fail(f"login failed for {user}: HTTP {status}")
        return ""
    return str(body["token"])


def _driver_tree(token: str, path: str, label: str) -> int:
    status, body = _fetch("GET", path, token=token)
    if status != 200 or not isinstance(body, dict):
        fail(f"{label} driver tree HTTP {status}")
        return 0
    devices = body.get("devices") or []
    pts = sum(len(d.get("points") or []) for d in devices)
    ok(f"{label} driver tree — {len(devices)} device(s), {pts} point(s)")
    return pts


def _ingest_modbus(token: str) -> bool:
    status, body = _fetch(
        "POST",
        "/api/modbus/read_and_store",
        token=token,
        body={
            "host": "127.0.0.1",
            "port": MODBUS_PORT,
            "unit_id": 1,
            "registers": [
                {
                    "address": 100,
                    "count": 1,
                    "function": "holding",
                    "decode": "uint16",
                    "scale": 0.1,
                    "label": "fake-temp",
                }
            ],
            "site_id": "demo",
        },
        timeout=15.0,
    )
    ingest = (body.get("ingest") or {}) if isinstance(body, dict) else {}
    readings = (body.get("readings") or []) if isinstance(body, dict) else []
    read_ok = any(r.get("success") for r in readings if isinstance(r, dict))
    if status != 200 or not read_ok or not ingest.get("ok"):
        fail(f"Modbus read_and_store: HTTP {status} {body}")
        return False
    ok(f"Modbus ingest — PV={body.get('present_value')} feather={ingest.get('feather_source')}")
    return True


def _ingest_json_api(token: str) -> bool:
    status, body = _fetch(
        "POST",
        "/api/json-api/read_and_store",
        token=token,
        body={
            "url": "https://jsonplaceholder.typicode.com/todos/1",
            "method": "GET",
            "json_path": "title",
            "label": "todo-title",
        },
        timeout=20.0,
    )
    if status != 200 or not isinstance(body, dict) or not body.get("success"):
        fail(f"JSON API read_and_store: HTTP {status} {body}")
        return False
    ingest = body.get("ingest") or {}
    ok(f"JSON API ingest — PV={body.get('present_value')!r} feather={ingest.get('feather_source')}")
    return True


def _feather_source(source: str, site_id: str, column: str) -> bool:
    from openfdd_bridge.data_loader import load_site_frame

    df = load_site_frame(site_id, source=source, columns=[column, "timestamp", "site_id"])
    if df is None or df.empty or column not in df.columns:
        fail(f"feather {source}/{site_id} missing column {column}")
        return False
    n = int(df[column].notna().sum())
    if n < 1:
        fail(f"feather {source}/{site_id}.{column} has no values")
        return False
    ok(f"feather {source}/{site_id}.{column} — {n} sample(s)")
    return True


def _plot_source(token: str, source: str, site_id: str, column: str) -> bool:
    if source == "json_api":
        from openfdd_bridge.data_loader import load_site_frame

        df = load_site_frame(site_id, source=source, columns=[column, "timestamp"])
        if df is None or df.empty or column not in df.columns:
            fail(f"json_api string historian missing {column}")
            return False
        vals = [str(v) for v in df[column].dropna().tolist() if str(v).strip()]
        if not vals:
            fail(f"json_api string historian empty for {column}")
            return False
        ok(f"json_api string historian — {len(vals)} value(s), last={vals[-1]!r}")
        return True
    status, body = _fetch(
        "GET",
        f"/api/timeseries/plot?site_id={site_id}&source={source}&columns={column}&hours=48&limit=200",
        token=token,
    )
    if status != 200 or not isinstance(body, dict):
        fail(f"timeseries plot source={source} HTTP {status}")
        return False
    ts = body.get("timestamps") or []
    series = (body.get("series") or {}).get(column) or []
    if not ts or not any(v is not None for v in series):
        fail(f"timeseries plot source={source} empty for {column}")
        return False
    ok(f"timeseries plot source={source} — {len(ts)} point(s) for {column}")
    return True


def _brick_and_setup_views(token: str) -> None:
    for path, label, min_len in [
        ("/api/model/scope?site_id=demo", "BRICK scope", 50),
        ("/api/model/commissioning-export", "commissioning-export (browser JSON tab)", 200),
        ("/api/model/ttl", "TTL (browser View TTL tab)", 100),
        ("/api/model/graph?site_id=demo", "BRICK graph", 50),
    ]:
        status, body = _fetch("GET", path, token=token)
        if status != 200:
            fail(f"{label} HTTP {status}")
            continue
        if isinstance(body, dict):
            text = json.dumps(body)
        else:
            text = str(body)
        if len(text) < min_len:
            fail(f"{label} payload too small ({len(text)} bytes)")
        else:
            ok(f"{label} — {len(text)} bytes")


def _rule_source_view(token: str) -> None:
    status, body = _fetch("GET", "/api/rules/saved", token=token)
    if status != 200 or not isinstance(body, dict):
        fail(f"rules list HTTP {status}")
        return
    rules = body.get("rules") or body.get("saved") or []
    if not rules:
        fail("no saved rules for source view test")
        return
    rid = str(rules[0].get("id") or "")
    status2, src = _fetch("GET", f"/api/rules/saved/{rid}/source", token=token)
    if status2 != 200 or not isinstance(src, dict) or not str(src.get("code") or "").strip():
        fail(f"rule source view for {rid} HTTP {status2}")
        return
    path = str(src.get("path") or "")
    ok(f"rule .py source view — {rid} ({len(src.get('code', ''))} chars, path={path or 'inline'})")


def _agent_assist(token_op: str, token_int: str) -> None:
    status, ctx_op = _fetch("GET", "/openfdd-agent/context", token=token_op)
    if status != 200 or not isinstance(ctx_op, dict):
        fail(f"agent context (operator) HTTP {status}")
    else:
        tools = ctx_op.get("tools") or []
        ok(f"agent context (operator) — {len(tools)} read-only tool(s)")

    status, ctx = _fetch("GET", "/openfdd-agent/context", token=token_int)
    if status != 200 or not isinstance(ctx, dict):
        fail(f"agent context (integrator) HTTP {status}")
        return
    tools = ctx.get("tools") or []
    brick = ctx.get("brick_model") or {}
    pipeline = ctx.get("data_pipeline") or []
    ok(
        f"agent context (integrator) — {len(tools)} tool(s), "
        f"brick equipment={brick.get('equipment_count')}, pipeline steps={len(pipeline)}"
    )

    for tool, args in [
        ("model.graph", {"site_id": "demo"}),
        ("timeseries.snapshot", {"site_id": "demo", "columns": ["stat_zn-t"], "hours": 48}),
        ("faults.lookup", {"code": "VAV-C"}),
    ]:
        status, body = _fetch(
            "POST",
            "/openfdd-agent/tool",
            token=token_int,
            body={"tool": tool, "args": args},
        )
        if status != 200 or not isinstance(body, dict) or body.get("error"):
            fail(f"agent tool {tool}: HTTP {status} {body}")
        else:
            result = body.get("result") or body
            preview = json.dumps(result)[:80]
            ok(f"agent tool {tool} — {preview}…")


def _fdd_batch(token: str) -> None:
    status, body = _fetch("POST", "/api/rules/batch", token=token, body={"limit": 5}, timeout=120.0)
    if status != 200 or not isinstance(body, dict):
        fail(f"FDD batch HTTP {status}")
        return
    runs = body.get("runs") or []
    rules_run = int(body.get("rules_run") or len(runs))
    flagged = sum(int(r.get("flagged") or 0) for r in runs if isinstance(r, dict))
    if rules_run < 1:
        fail("FDD batch returned no rule runs")
        return
    ok(f"FDD batch — {rules_run} rule(s), {flagged} flagged row(s), source={runs[0].get('source') if runs else 'n/a'}")


def _bacnet_driver_live(token: str) -> None:
    status, tree = _fetch("GET", "/api/bacnet/driver/tree", token=token)
    if status != 200 or not isinstance(tree, dict):
        fail(f"BACnet tree HTTP {status}")
        return
    point = None
    for dev in tree.get("devices") or []:
        for pt in dev.get("points") or []:
            if str(pt.get("present_value") or "").strip():
                point = pt
                break
        if point:
            break
    if not point:
        fail("BACnet driver — no point with present_value")
        return
    ok(
        f"BACnet driver live — {point.get('point_id')} PV={point.get('present_value')!r} "
        f"poll={point.get('poll_label') or 'off'}"
    )


def _start_modbus_server() -> subprocess.Popen | None:
    import socket

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.connect(("127.0.0.1", MODBUS_PORT))
        sock.close()
        ok(f"fake Modbus server already listening on {MODBUS_PORT}")
        return None
    except OSError:
        sock.close()
    proc = subprocess.Popen(
        [sys.executable, str(REPO / "scripts" / "fake_modbus_temp_server.py"), "--port", str(MODBUS_PORT), "--flatline", "72.5"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(0.7)
    if proc.poll() is not None:
        fail("could not start fake Modbus server")
        return None
    ok(f"started fake Modbus server on {MODBUS_PORT}")
    return proc


def main() -> int:
    parser = argparse.ArgumentParser(description="Multi-driver smoke battery")
    parser.add_argument("--skip-modbus-server", action="store_true")
    args = parser.parse_args()

    print("\n==> Health")
    status, body = _fetch("GET", "/health")
    if status == 200 and isinstance(body, dict) and body.get("ok"):
        ok(f"bridge health @ {BASE}")
    else:
        fail(f"bridge health HTTP {status}")

    op_u, op_p, int_u, int_p = _load_auth()
    print("\n==> Auth")
    token_op = login(op_u, op_p)
    token_int = login(int_u, int_p)
    if not token_op or not token_int:
        print(f"\nSMOKE FAILED ({FAILURES} step(s))")
        return 1

    print("\n==> Driver trees (human commissioning tabs)")
    _driver_tree(token_op, "/api/bacnet/driver/tree", "BACnet")
    _driver_tree(token_op, "/api/modbus/driver/tree", "Modbus")
    _driver_tree(token_op, "/api/json-api/driver/tree", "JSON API")

    modbus_proc = None
    try:
        if not args.skip_modbus_server:
            print("\n==> Modbus fake OT device")
            modbus_proc = _start_modbus_server()

        print("\n==> Live ingest (all three sources)")
        _bacnet_driver_live(token_op)
        if modbus_proc is not None or not args.skip_modbus_server:
            _ingest_modbus(token_op)
        _ingest_json_api(token_op)

        print("\n==> Feather historian (source isolation)")
        _feather_source("bacnet", "demo", "stat_zn-t")
        _feather_source("modbus", "demo", "fake-temp")
        _feather_source("json_api", "demo", "todo-title")

        print("\n==> Timeseries plot API (per source)")
        _plot_source(token_op, "bacnet", "demo", "stat_zn-t")
        _plot_source(token_op, "modbus", "demo", "fake-temp")
        _plot_source(token_op, "json_api", "demo", "todo-title")

        print("\n==> BRICK + browser setup views (TTL, commissioning JSON, rule .py)")
        _brick_and_setup_views(token_op)
        _rule_source_view(token_op)

        print("\n==> AI agent assistance (integrator context + read-only tools)")
        _agent_assist(token_op, token_int)

        print("\n==> FDD equations (batch on BRICK-bound rules + feather data)")
        _fdd_batch(token_int)
    finally:
        if modbus_proc is not None and modbus_proc.poll() is None:
            modbus_proc.terminate()

    print("")
    if FAILURES:
        print(f"SMOKE FAILED ({FAILURES} step(s))", file=sys.stderr)
        return 1
    print("SMOKE OK — BACnet + Modbus + JSON API → feather → BRICK → FDD + agent + browser setup views")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
