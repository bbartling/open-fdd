#!/usr/bin/env python3
"""Benserver bench smoke — BACnet 5007 + Niagara bench9065 on one physical box.

Validates:
  - BRICK model lists two separate driver devices (bacnet-5007, niagara-bench9065)
  - Cross-source BACnet vs Niagara value alignment (bench validator)
  - Four data-source-agnostic FDD rules (no Niagara/BACnet in rule names)
  - Rules-by-data-source preset shows both drivers per rule
  - FDD batch runs against live feather data

Run from repo root with stack up (./scripts/run_local.sh start):
  python3 scripts/smoke_benserver_bench.py
  python3 scripts/smoke_benserver_bench.py --skip-cross-source
"""

from __future__ import annotations

import argparse
import json
import os
import sys
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

from openfdd_bridge.bench_contract import (  # noqa: E402
    AGNOSTIC_RULE_IDS,
    BACNET_DEVICE_ID,
    NIAGARA_DEVICE_ID,
    validate_bench_contract,
)

BASE = os.environ.get("OPENFDD_BASE_URL", "http://127.0.0.1:8765").rstrip("/")
AUTH_ENV = REPO / "workspace" / "auth.env.local"
FAILURES = 0


def ok(msg: str) -> None:
    print(f"  OK   {msg}")


def fail(msg: str) -> None:
    global FAILURES
    FAILURES += 1
    print(f"  FAIL {msg}", file=sys.stderr)


def _load_auth() -> tuple[str, str]:
    if AUTH_ENV.is_file():
        for line in AUTH_ENV.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip("'\""))
    user = os.environ.get("OFDD_INTEGRATOR_USER", os.environ.get("OFDD_OPERATOR_USER", "operator"))
    password = os.environ.get("OFDD_INTEGRATOR_PASSWORD", os.environ.get("OFDD_OPERATOR_PASSWORD", "changeme"))
    return user, password


def _fetch(
    method: str,
    path: str,
    *,
    token: str | None = None,
    body: dict | None = None,
    timeout: float = 90.0,
) -> tuple[int, Any]:
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
            return exc.code, {"detail": raw}
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        return 0, {"error": str(exc)}


def _login() -> str:
    user, password = _load_auth()
    status, body = _fetch("POST", "/api/auth/login", body={"username": user, "password": password})
    if status != 200 or not isinstance(body, dict) or not body.get("token"):
        fail(f"login failed: HTTP {status}")
        return ""
    return str(body["token"])


def _model_and_rules(token: str) -> tuple[dict, list[dict]]:
    status, tree = _fetch("GET", "/api/model/tree", token=token)
    if status != 200 or not isinstance(tree, dict):
        fail(f"model tree HTTP {status}")
        return {}, []
    model = {
        "sites": [{"id": "demo"}],
        "equipment": tree.get("equipment") or [],
        "points": tree.get("points") or [],
    }
    status2, rules_body = _fetch("GET", "/api/rules/saved", token=token)
    if status2 != 200 or not isinstance(rules_body, dict):
        fail(f"rules list HTTP {status2}")
        return model, []
    rules = rules_body.get("rules") or []
    return model, rules


def _contract(token: str) -> None:
    model, rules = _model_and_rules(token)
    if not model.get("equipment"):
        fail("model tree empty — import bench_dual_source_model.json or run bootstrap")
        return
    report = validate_bench_contract(model, rules, require_four_rules=True)
    if not report["ok"]:
        for issue in report["issues"]:
            fail(f"bench contract: {issue}")
        return
    dev = report["devices"]
    ok(
        f"dual driver devices — {dev['devices'][BACNET_DEVICE_ID]['name']!r} "
        f"({dev['bacnet_point_count']} pts) + {dev['devices'][NIAGARA_DEVICE_ID]['name']!r} "
        f"({dev['niagara_point_count']} pts)"
    )
    ok(f"source-agnostic rules — {report['rules']['rule_count']} rules, ids={report['rules']['rule_ids']}")


def _try_niagara_poll(token: str) -> bool:
    if not os.environ.get("OPENFDD_NIAGARA_ADMIN_PASSWORD", "").strip():
        return False
    status, body = _fetch(
        "POST",
        "/api/niagara/stations/bench9065/poll/once",
        token=token,
        timeout=120.0,
    )
    if status == 200 and isinstance(body, dict) and body.get("ok"):
        pts = int(body.get("points_read") or body.get("point_count") or 0)
        ok(f"Niagara bench9065 poll once — {pts} point(s)")
        return True
    fail(f"Niagara poll once failed: HTTP {status} {body if isinstance(body, dict) else body}")
    return False


def _cross_source(token: str, *, tolerate_stale: bool) -> None:
    if os.environ.get("OPENFDD_NIAGARA_ADMIN_PASSWORD", "").strip():
        _try_niagara_poll(token)

    status, body = _fetch("POST", "/api/bench/validate/bacnet-vs-niagara", token=token, body={})
    if status != 200 or not isinstance(body, dict):
        fail(f"bacnet-vs-niagara HTTP {status}")
        return
    summary = body.get("summary") or {}
    passed = int(summary.get("passed") or 0)
    total = int(summary.get("total") or 0)
    score = summary.get("score_pct")
    points = body.get("points") or []

    if passed >= 4:
        ok(f"BACnet 5007 ↔ Niagara bench9065 — {passed}/{total} mapped points align (score={score}%)")
        return

    stale_fails = [
        p
        for p in points
        if not p.get("pass") and (p.get("stale_niagara") or p.get("stale_bacnet"))
    ]
    mismatch_fails = [
        p
        for p in points
        if not p.get("pass")
        and not p.get("stale_niagara")
        and not p.get("stale_bacnet")
        and not p.get("missing_bacnet")
        and not p.get("missing_niagara")
    ]

    if tolerate_stale and stale_fails and not mismatch_fails:
        ok(
            f"cross-source stale only — {len(stale_fails)} point(s) need fresh Niagara poll "
            f"(set OPENFDD_NIAGARA_ADMIN_PASSWORD in workspace/niagara.env.local)"
        )
        return

    reasons = [
        f"{p.get('semantic_point_id')}:{p.get('reason')}"
        for p in points
        if not p.get("pass")
    ][:4]
    fail(f"cross-source match weak — {passed}/{total} passed (score={score}); {reasons}")


def _rules_by_data_source(token: str) -> None:
    status, body = _fetch("GET", "/api/model/fdd-query-presets/rules_by_data_source", token=token)
    if status != 200 or not isinstance(body, dict):
        fail(f"rules_by_data_source preset HTTP {status}")
        return
    rows = body.get("rows") or []
    sources = {str(r.get("data_source") or "") for r in rows}
    if not any("5007" in s for s in sources):
        fail(f"preset missing BACnet source rows: {sources}")
        return
    if not any("bench9065" in s for s in sources):
        fail(f"preset missing Niagara source rows: {sources}")
        return
    rule_ids = {str(r.get("rule_id") or "") for r in rows}
    if not set(AGNOSTIC_RULE_IDS) <= rule_ids:
        fail(f"preset missing bench rules: {rule_ids}")
        return
    ok(f"rules by data source — {len(rows)} row(s), drivers={sorted(sources)}")


def _fdd_batch(token: str) -> None:
    status, body = _fetch("POST", "/api/rules/batch", token=token, body={"limit": 10}, timeout=120.0)
    if status != 200 or not isinstance(body, dict):
        fail(f"FDD batch HTTP {status}")
        return
    runs = body.get("runs") or []
    if len(runs) < 4:
        fail(f"FDD batch expected 4+ runs, got {len(runs)}")
        return
    errors = [str(r.get("error") or "") for r in runs if r.get("status") == "error"]
    if errors:
        fail(f"FDD batch errors: {errors[:3]}")
        return
    flagged = sum(int(r.get("flagged") or 0) for r in runs)
    ok(f"FDD batch — {len(runs)} rules, {flagged} flagged sample(s)")


def _bacnet_device_5007_live(token: str) -> None:
    status, tree = _fetch("GET", "/api/bacnet/driver/tree", token=token)
    if status != 200 or not isinstance(tree, dict):
        fail(f"BACnet driver tree HTTP {status}")
        return
    dev5007 = None
    for dev in tree.get("devices") or []:
        inst = dev.get("device_instance") or dev.get("bacnet_device_id")
        if str(inst) == "5007" or int(inst or -1) == 5007:
            dev5007 = dev
            break
    if not dev5007:
        fail("BACnet driver tree — device 5007 not found")
        return
    pts = dev5007.get("points") or []
    live = [p for p in pts if str(p.get("present_value") or "").strip()]
    ok(f"BACnet device 5007 — {len(pts)} point(s), {len(live)} with present_value")


def main() -> int:
    parser = argparse.ArgumentParser(description="Benserver dual-source bench smoke")
    parser.add_argument("--skip-cross-source", action="store_true", help="skip BACnet↔Niagara value compare")
    parser.add_argument(
        "--strict-cross-source",
        action="store_true",
        help="require live BACnet↔Niagara match (fail on stale Niagara samples)",
    )
    args = parser.parse_args()
    tolerate_stale = not args.strict_cross_source

    print("\n==> Health")
    status, body = _fetch("GET", "/health")
    if status == 200 and isinstance(body, dict) and body.get("ok"):
        ok(f"bridge @ {BASE}")
    else:
        fail(f"bridge health HTTP {status}")
        print(f"\nSMOKE FAILED ({FAILURES} step(s))")
        return 1

    print("\n==> Auth")
    token = _login()
    if not token:
        print(f"\nSMOKE FAILED ({FAILURES} step(s))")
        return 1
    ok("integrator login")

    print("\n==> Dual driver BRICK model + agnostic rules")
    _contract(token)

    print("\n==> BACnet device 5007 live poll")
    _bacnet_device_5007_live(token)

    if not args.skip_cross_source:
        print("\n==> BACnet 5007 vs Niagara bench9065 cross-source")
        _cross_source(token, tolerate_stale=tolerate_stale)

    print("\n==> SPARQL preset — rules by data source")
    _rules_by_data_source(token)

    print("\n==> FDD batch (4 agnostic rules)")
    _fdd_batch(token)

    print("")
    if FAILURES:
        print(f"SMOKE FAILED ({FAILURES} step(s))", file=sys.stderr)
        return 1
    print("SMOKE OK — benserver bench: 2 driver devices, agnostic rules, dual-source bindings")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
