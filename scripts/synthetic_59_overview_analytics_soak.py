#!/usr/bin/env python3
"""Synthetic-59 Overview analytics envelope soak (Track D).

Asserts motor/runtime + mechanical-cooling OAT bin envelopes for the
synthetic fixture building already imported on OpenFDD central. Does **not**
change FDD target_match scores — run after synthetic_59_target_pair_soak.py
`--side ofdd` (or any tip stack with the fixture loaded).

  python3 scripts/synthetic_59_overview_analytics_soak.py
  OPENFDD_ADMIN_PASSWORD=... python3 scripts/synthetic_59_overview_analytics_soak.py \\
      --building-id OPENFDD_SYNTHETIC_59_RULE_WEEK_V1
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from eplus_paths import synthetic_artifacts_dir, synthetic_fixture_dir

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = synthetic_fixture_dir()
ARTIFACTS = synthetic_artifacts_dir()
BUILDING_ID = "OPENFDD_SYNTHETIC_59_RULE_WEEK_V1"
RUNTIME_LEGEND = (
    FIXTURE / "OPENFDD_SYNTHETIC_59_RULE_WEEK_V1" / "runtime_legend.csv"
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def http_json(
    method: str,
    url: str,
    token: str | None = None,
    body: bytes | None = None,
    content_type: str | None = None,
    timeout: float = 120.0,
) -> dict:
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if content_type:
        headers["Content-Type"] = content_type
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        try:
            return json.loads(detail)
        except json.JSONDecodeError:
            return {"ok": False, "error": f"HTTP {e.code}: {detail[:500]}"}


def login(base: str, user: str, password: str) -> str:
    out = http_json(
        "POST",
        f"{base}/api/auth/login",
        body=json.dumps({"username": user, "password": password}).encode(),
        content_type="application/json",
        timeout=30.0,
    )
    token = out.get("token") or out.get("access_token")
    if not token:
        raise SystemExit(f"login failed: {out}")
    return str(token)


def unwrap_analytics(body: dict) -> dict:
    if not isinstance(body, dict):
        return {}
    if isinstance(body.get("analytics"), dict):
        return body["analytics"]
    return body


def load_runtime_legend() -> dict[str, float]:
    """equipment_id → expected_typical_hours from fixture legend."""
    out: dict[str, float] = {}
    if not RUNTIME_LEGEND.is_file():
        return out
    for row in csv.DictReader(RUNTIME_LEGEND.open()):
        eid = str(row.get("equipment_id") or "").strip()
        if not eid:
            continue
        raw = row.get("expected_typical_hours") or row.get("runtime_hours")
        try:
            out[eid] = float(raw)
        except (TypeError, ValueError):
            continue
    return out


def check(
    name: str,
    ok: bool,
    detail: str,
    checks: list[dict],
) -> None:
    checks.append({"name": name, "ok": bool(ok), "detail": detail})
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {name}: {detail}")


def assert_runtime(base: str, token: str, building: str, checks: list[dict]) -> dict:
    body = http_json(
        "POST",
        f"{base}/api/analytics/runtime",
        token=token,
        body=json.dumps({"building_id": building}).encode(),
        content_type="application/json",
    )
    env = unwrap_analytics(body)
    engine = str(env.get("engine") or "")
    qv = str(env.get("query_version") or "")
    rows = list(env.get("rows") or env.get("equipment") or [])
    check(
        "runtime_envelope",
        bool(env) and ("datafusion" in engine.lower() or qv.startswith("runtime")),
        f"engine={engine!r} query_version={qv!r} n_rows={len(rows)}",
        checks,
    )
    positive = [
        r
        for r in rows
        if float(r.get("run_hours") or r.get("hours") or 0) > 0
    ]
    check(
        "runtime_positive_hours",
        len(positive) >= 1,
        f"n_positive={len(positive)}",
        checks,
    )
    legend = load_runtime_legend()
    for eid, expected in (
        ("AHU_CASE_FC1", legend.get("AHU_CASE_FC1", 40.0)),
        ("AHU_CASE_SCHED_247", legend.get("AHU_CASE_SCHED_247", 168.0)),
    ):
        hits = [
            r
            for r in rows
            if str(r.get("equipment_id") or "") == eid
            and str(r.get("kind") or "") not in ("weekly_plant", "weekly_equipment")
        ]
        if not hits:
            # weekly rows only — accept any row for that equipment
            hits = [r for r in rows if str(r.get("equipment_id") or "") == eid]
        hours = max(
            (float(r.get("run_hours") or r.get("hours") or 0) for r in hits),
            default=None,
        )
        if hours is None:
            check(f"runtime_{eid}", False, "missing equipment row", checks)
            continue
        tol = max(2.0, 0.10 * expected)
        ok = abs(hours - expected) <= tol
        check(
            f"runtime_{eid}",
            ok,
            f"hours={hours:.3f} expected≈{expected} tol±{tol:.1f}",
            checks,
        )
    weekly = [
        r
        for r in rows
        if str(r.get("kind") or "") in ("weekly_plant", "weekly_equipment")
        and float(r.get("run_hours") or r.get("hours") or 0) > 0
    ]
    if weekly:
        plants = {str(r.get("plant_group") or "") for r in weekly}
        check(
            "runtime_weekly_presence",
            bool(plants & {"air", "chiller", "boiler"}),
            f"plants={sorted(plants)}",
            checks,
        )
    return env


def assert_mech_cooling(
    base: str, token: str, building: str, checks: list[dict]
) -> dict:
    body = http_json(
        "POST",
        f"{base}/api/analytics/mechanical-cooling",
        token=token,
        body=json.dumps({"building_id": building}).encode(),
        content_type="application/json",
    )
    env = unwrap_analytics(body)
    engine = str(env.get("engine") or "")
    rows = list(env.get("rows") or env.get("equipment") or [])
    oat_bins = [r for r in rows if str(r.get("kind") or "") == "oat_bin"]
    check(
        "mech_envelope",
        bool(env) and ("datafusion" in engine.lower() or len(oat_bins) > 0),
        f"engine={engine!r} n_oat_bins={len(oat_bins)}",
        checks,
    )
    check("mech_oat_bins_present", len(oat_bins) >= 1, f"n={len(oat_bins)}", checks)
    individual = [
        r
        for r in oat_bins
        if str(r.get("series_kind") or "") == "individual_device"
        and "CHILLER" in str(r.get("equipment_id") or "").upper()
    ]
    check(
        "mech_chiller_device_bins",
        len(individual) >= 1,
        f"n_chiller_bins={len(individual)}",
        checks,
    )
    agg = [
        r
        for r in oat_bins
        if str(r.get("series_kind") or "")
        in ("aggregate_device_hours", "aggregate_active_hours")
    ]
    check("mech_aggregate_bins", len(agg) >= 1, f"n_agg={len(agg)}", checks)
    total_indiv = sum(float(r.get("hours") or 0) for r in individual)
    # Synthetic fixture has several CHILLER_CASE_* units (~40h each) → hundreds OK.
    check(
        "mech_individual_hours_envelope",
        1.0 <= total_indiv <= 800.0,
        f"sum_individual_device_hours={total_indiv:.3f}",
        checks,
    )
    return env


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--base",
        default=os.environ.get("OPENFDD_API_BASE", "http://127.0.0.1:8080"),
    )
    ap.add_argument("--user", default=os.environ.get("OPENFDD_ADMIN_USER", "admin"))
    ap.add_argument(
        "--password",
        default=os.environ.get("OPENFDD_ADMIN_PASSWORD", "bensbench-local-admin"),
    )
    ap.add_argument("--building-id", default=BUILDING_ID)
    args = ap.parse_args()

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    token = login(args.base, args.user, args.password)
    checks: list[dict] = []
    print(f">> runtime analytics ({args.building_id})")
    runtime_env = assert_runtime(args.base, token, args.building_id, checks)
    print(f">> mechanical-cooling analytics ({args.building_id})")
    mech_env = assert_mech_cooling(args.base, token, args.building_id, checks)

    failed = [c for c in checks if not c["ok"]]
    summary = {
        "ok": not failed,
        "generated_at": utc_now(),
        "building_id": args.building_id,
        "checks": checks,
        "failed": [c["name"] for c in failed],
        "runtime_query_version": runtime_env.get("query_version"),
        "mech_query_version": mech_env.get("query_version"),
        "mech_coverage": mech_env.get("coverage"),
    }
    out = ARTIFACTS / "ofdd_overview_analytics_checks.json"
    out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out} ({'PASS' if summary['ok'] else 'FAIL'} {len(failed)} fails)")
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
