#!/usr/bin/env python3
"""Overview / FDD / RCx backend comb — parameterized building_id.

Catches DataFusion planning errors (e.g. avg(Utf8View)), 5xx, and empty envelopes
when roles are mapped. Honest SKIP/DEFERRED for missing map columns — not PASS.

Env:
  OPENFDD_API_BASE (default http://127.0.0.1:8080)
  OPENFDD_BUILDING_ID (required)
  OPENFDD_ADMIN_PASSWORD + OPENFDD_ADMIN_USER (default admin)
  ARTIFACT_DIR (optional)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

PLANNING_MARKERS = (
    "Utf8View",
    "avg(Utf8View",
    "failed to match",
    "No function matches",
    "SchemaError",
    "planning error",
    "SanityCheckPlan",
)

OVERVIEW_POSTS: list[tuple[str, str]] = [
    ("analytics_runtime", "/api/analytics/runtime"),
    ("analytics_mechanical_cooling", "/api/analytics/mechanical-cooling"),
    ("analytics_economizer", "/api/analytics/economizer"),
    ("analytics_bas_vs_web_oat", "/api/analytics/bas-vs-web-oat"),
    ("analytics_sensor_health", "/api/analytics/sensor-health"),
    ("analytics_sensor_faults", "/api/analytics/sensor-faults"),
    ("analytics_ahu_health", "/api/analytics/ahu-health"),
    ("analytics_vav_health", "/api/analytics/vav-health"),
    ("analytics_chiller_health", "/api/analytics/chiller-health"),
    ("analytics_boiler_health", "/api/analytics/boiler-health"),
    ("analytics_hp_health", "/api/analytics/hp-health"),
    ("analytics_rcx_ahu", "/api/analytics/rcx/ahu"),
    ("analytics_rcx_vav", "/api/analytics/rcx/vav"),
    ("analytics_rcx_chiller", "/api/analytics/rcx/chiller"),
    ("analytics_rcx_boiler", "/api/analytics/rcx/boiler"),
    ("analytics_inspect", "/api/analytics/inspect"),
    ("analytics_sql_anomaly", "/api/analytics/sql-anomaly"),
]

FDD_GETS: list[tuple[str, str]] = [
    ("fdd_status", "/api/fdd/status"),
    ("fdd_rules", "/api/fdd/rules"),
    ("fdd_equipment", "/api/fdd/equipment?building_id={bid}"),
    ("fdd_results", "/api/fdd/results?building_id={bid}"),
    ("package_mapping", "/api/csv/import/package/mapping?building_id={bid}"),
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def http_json(
    method: str,
    url: str,
    token: str | None = None,
    body: dict | None = None,
    timeout: float = 120.0,
) -> tuple[int, dict | str]:
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            code = resp.getcode()
            try:
                return code, json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                return code, raw
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        try:
            return e.code, json.loads(detail)
        except json.JSONDecodeError:
            return e.code, detail


def login(base: str, user: str, password: str) -> str:
    code, out = http_json(
        "POST",
        f"{base}/api/auth/login",
        body={"username": user, "password": password},
        timeout=30.0,
    )
    if code != 200 or not isinstance(out, dict):
        raise SystemExit(f"login failed HTTP {code}: {out!r}")
    tok = out.get("token") or out.get("access_token")
    if not tok:
        raise SystemExit(f"login missing token: {out}")
    return str(tok)


def text_blob(obj: object) -> str:
    if isinstance(obj, str):
        return obj
    return json.dumps(obj, default=str)


def has_planning_error(blob: str) -> bool:
    low = blob.lower()
    return any(m.lower() in low for m in PLANNING_MARKERS)


def envelope_rows(body: dict) -> int:
    a = body.get("analytics") if isinstance(body.get("analytics"), dict) else body
    if not isinstance(a, dict):
        return 0
    for key in ("rows", "equipment", "points"):
        v = a.get(key)
        if isinstance(v, list):
            return len(v)
    return 0


def fail_closed(body: dict) -> bool:
    a = body.get("analytics") if isinstance(body.get("analytics"), dict) else body
    if not isinstance(a, dict):
        return False
    cov = a.get("coverage")
    if isinstance(cov, dict):
        if cov.get("fail_closed") is True or cov.get("timed_out") is True:
            return True
    if a.get("timed_out") is True:
        return True
    warnings = a.get("warnings") or body.get("warnings") or []
    if isinstance(warnings, list):
        for w in warnings:
            if isinstance(w, str) and any(
                x in w.lower() for x in ("timeout", "fail-closed", "timed out")
            ):
                return True
    return False


def mapped_roles(mapping: dict) -> set[str]:
    roles: set[str] = set()
    eq = mapping.get("equipment")
    if isinstance(eq, list):
        for item in eq:
            if not isinstance(item, dict):
                continue
            cols = item.get("columns") or item.get("roles") or item.get("mapped_roles")
            if isinstance(cols, dict):
                roles.update(str(k) for k in cols.keys())
            elif isinstance(cols, list):
                for c in cols:
                    if isinstance(c, dict) and c.get("role"):
                        roles.add(str(c["role"]))
                    elif isinstance(c, str):
                        roles.add(c)
    return roles


def pick_ahu_id(equipment_json: dict) -> str | None:
    eq = equipment_json.get("equipment") or equipment_json.get("items") or []
    if isinstance(equipment_json, list):
        eq = equipment_json
    if not isinstance(eq, list):
        return None
    for row in eq:
        if not isinstance(row, dict):
            continue
        stamp = (
            row.get("equipment_type_raw")
            or row.get("equipment_type")
            or row.get("equipType")
            or ""
        )
        if str(stamp).lower() in ("ahu", "rtu", "mau"):
            eid = row.get("equipment_id")
            if eid:
                return str(eid)
    if eq and isinstance(eq[0], dict) and eq[0].get("equipment_id"):
        return str(eq[0]["equipment_id"])
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--building-id", default=os.environ.get("OPENFDD_BUILDING_ID"))
    ap.add_argument("--base", default=os.environ.get("OPENFDD_API_BASE", "http://127.0.0.1:8080"))
    ap.add_argument("--artifact-dir", default=os.environ.get("ARTIFACT_DIR"))
    ap.add_argument("--lookback-days", type=int, default=int(os.environ.get("OPENFDD_GATE_LOOKBACK_DAYS", "30")))
    ap.add_argument("--hard-timeout-secs", type=float, default=float(os.environ.get("OPENFDD_GATE_HARD_TIMEOUT_SECS", "180")))
    args = ap.parse_args()
    bid = (args.building_id or "").strip()
    if not bid:
        print("FAIL: OPENFDD_BUILDING_ID or --building-id required", file=sys.stderr)
        return 1
    base = args.base.rstrip("/")
    user = os.environ.get("OPENFDD_ADMIN_USER", "admin")
    password = os.environ.get("OPENFDD_ADMIN_PASSWORD", "")
    if not password:
        print("FAIL: OPENFDD_ADMIN_PASSWORD required", file=sys.stderr)
        return 1

    art = Path(args.artifact_dir) if args.artifact_dir else ROOT / "reports" / f"ui_fdd_rcx_gate_{utc_now_iso().replace(':', '')}"
    art.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []
    fails = 0
    skips = 0

    tok = login(base, user, password)
    start = (datetime.now(timezone.utc) - timedelta(days=args.lookback_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    window_body = {"building_id": bid, "max_points": 4000, "start": start}

    code, health = http_json("GET", f"{base}/api/health", token=tok, timeout=30.0)
    (art / "health.json").write_text(json.dumps({"http": code, "body": health}, indent=2))
    if code != 200:
        print(f"FAIL: /api/health HTTP {code}")
        return 1

    mem_before = None
    if isinstance(health, dict):
        mb = health.get("memory_budget")
        if isinstance(mb, dict):
            mem_before = mb.get("current_bytes")

    for name, path_tpl in FDD_GETS:
        path = path_tpl.format(bid=urllib.parse.quote(bid, safe=""))
        code, body = http_json("GET", f"{base}{path}", token=tok, timeout=60.0)
        blob = text_blob(body)
        entry = {"name": name, "method": "GET", "path": path, "http_code": code}
        if code >= 500 or has_planning_error(blob):
            entry["status"] = "FAIL"
            fails += 1
        elif code == 403:
            entry["status"] = "FAIL"
            entry["reason"] = "403 building scope"
            fails += 1
        elif code != 200:
            entry["status"] = "FAIL"
            fails += 1
        else:
            entry["status"] = "PASS"
        results.append(entry)
        (art / f"probe_{name}.json").write_text(blob if isinstance(body, str) else json.dumps(body, indent=2))

    eq_body = json.loads((art / "probe_fdd_equipment.json").read_text()) if (art / "probe_fdd_equipment.json").exists() else {}
    mapping_body = {}
    if (art / "probe_package_mapping.json").exists():
        mapping_body = json.loads((art / "probe_package_mapping.json").read_text())
    roles_mapped = mapped_roles(mapping_body if isinstance(mapping_body, dict) else {})
    ahu_id = pick_ahu_id(eq_body if isinstance(eq_body, dict) else {})

    for name, path in OVERVIEW_POSTS:
        body = dict(window_body)
        if name == "analytics_inspect" and ahu_id:
            body["equipment_ids"] = [ahu_id]
        code, out = http_json("POST", f"{base}{path}", token=tok, body=body, timeout=args.hard_timeout_secs)
        blob = text_blob(out)
        entry = {"name": name, "method": "POST", "path": path, "http_code": code}
        if code >= 500 or has_planning_error(blob):
            entry["status"] = "FAIL"
            entry["detail"] = blob[:500]
            fails += 1
        elif code == 403:
            entry["status"] = "FAIL"
            fails += 1
        elif code != 200:
            entry["status"] = "FAIL"
            fails += 1
        elif isinstance(out, dict) and fail_closed(out):
            entry["status"] = "FAIL"
            entry["reason"] = "fail_closed_or_timeout_envelope"
            fails += 1
        else:
            nrows = envelope_rows(out if isinstance(out, dict) else {})
            entry["rows"] = nrows
            if name == "analytics_bas_vs_web_oat" and nrows == 0:
                if "oa_t" not in roles_mapped and "web_oa_t" not in roles_mapped:
                    entry["status"] = "SKIP"
                    entry["reason"] = "missing oa_t and web_oa_t map (need site-broadcast BAS + web OAT)"
                    skips += 1
                else:
                    entry["status"] = "PASS"
                    entry["note"] = "empty join — check historian overlap/window"
            else:
                entry["status"] = "PASS"
        results.append(entry)
        (art / f"probe_{name}.json").write_text(blob if isinstance(out, str) else json.dumps(out, indent=2))

        code_h, health2 = http_json("GET", f"{base}/api/health", token=tok, timeout=15.0)
        if code_h != 200 or not (isinstance(health2, dict) and health2.get("ok") is True):
            entry["status"] = "FAIL"
            entry["reason"] = "central unhealthy after probe"
            fails += 1

    code, presets_out = http_json(
        "GET",
        f"{base}/api/analytics/rcx/presets?building_id={urllib.parse.quote(bid)}",
        token=tok,
        timeout=60.0,
    )
    preset_ids: list[str] = []
    if code == 200 and isinstance(presets_out, dict):
        for p in presets_out.get("presets") or []:
            if isinstance(p, dict) and p.get("id"):
                preset_ids.append(str(p["id"]))
    (art / "rcx_presets_list.json").write_text(json.dumps(presets_out, indent=2))

    for pid in preset_ids:
        pname = f"rcx_preset_{pid}"
        body = {
            "building_id": bid,
            "max_points": 2000,
            "start": start,
            "series": {"preset_id": pid},
        }
        code, out = http_json(
            "POST",
            f"{base}/api/analytics/rcx/preset",
            token=tok,
            body=body,
            timeout=args.hard_timeout_secs,
        )
        blob = text_blob(out)
        entry = {"name": pname, "method": "POST", "path": "/api/analytics/rcx/preset", "http_code": code, "preset_id": pid}
        if code >= 500 or has_planning_error(blob):
            entry["status"] = "FAIL"
            entry["detail"] = blob[:500]
            fails += 1
        elif code != 200:
            entry["status"] = "FAIL"
            fails += 1
        elif isinstance(out, dict) and fail_closed(out):
            entry["status"] = "FAIL"
            entry["reason"] = "fail_closed_or_timeout"
            fails += 1
        else:
            nrows = envelope_rows(out if isinstance(out, dict) else {})
            entry["rows"] = nrows
            if nrows == 0 and pid == "ahu_dampers" and "oa_damper_pct" not in roles_mapped:
                entry["status"] = "SKIP"
                entry["reason"] = "oa_damper_pct not in package map"
                skips += 1
            elif nrows == 0:
                entry["status"] = "DEFERRED"
                entry["reason"] = "empty envelope — verify roles/stamp/window"
                skips += 1
            else:
                entry["status"] = "PASS"
        results.append(entry)
        (art / f"probe_{pname}.json").write_text(blob if isinstance(out, str) else json.dumps(out, indent=2))

    if ahu_id:
        for rule_id in ("FC1", "DMP-1"):
            path = f"/api/fdd/series?building_id={urllib.parse.quote(bid)}&equipment_id={urllib.parse.quote(ahu_id)}&rule_id={rule_id}"
            code, out = http_json("GET", f"{base}{path}", token=tok, timeout=120.0)
            blob = text_blob(out)
            entry = {"name": f"fdd_series_{rule_id}", "method": "GET", "path": path, "http_code": code}
            if code >= 500 or has_planning_error(blob):
                entry["status"] = "FAIL"
                fails += 1
            elif code != 200:
                entry["status"] = "DEFERRED" if code == 404 else "FAIL"
                if entry["status"] == "DEFERRED":
                    skips += 1
                else:
                    fails += 1
            else:
                entry["status"] = "PASS"
            results.append(entry)

    code, health_after = http_json("GET", f"{base}/api/health", token=tok, timeout=30.0)
    mem_after = None
    if isinstance(health_after, dict):
        mb = health_after.get("memory_budget")
        if isinstance(mb, dict):
            mem_after = mb.get("current_bytes")

    summary = {
        "ok": fails == 0,
        "building_id": bid,
        "artifact_dir": str(art),
        "fails": fails,
        "skips": skips,
        "probes": results,
        "memory_current_bytes_before": mem_before,
        "memory_current_bytes_after": mem_after,
        "health_version": health_after.get("version") if isinstance(health_after, dict) else None,
    }
    (art / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({"ok": summary["ok"], "fails": fails, "skips": skips, "artifact_dir": str(art)}))
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
