#!/usr/bin/env python3
"""Health-matrix fault-hour parity vs synthetic golden `expected_faults.csv`.

Run after `synthetic_59_target_pair_soak.py --side ofdd` (FDD registry populated).

  OPENFDD_ADMIN_PASSWORD=... python3 scripts/synthetic_59_health_matrix_fault_hours_soak.py
  OPENFDD_ADMIN_PASSWORD=... python3 scripts/synthetic_59_health_matrix_fault_hours_soak.py \\
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
EXPECTED = FIXTURE / "expected_faults.csv"
BUILDING_ID = "OPENFDD_SYNTHETIC_59_RULE_WEEK_V1"
HOURS_TOL = 0.05

# Broken-box rules aggregated into `broken_fault_hours` on VAV health rows.
VAV_BROKEN_RULES = frozenset(
    {"VAV-3", "VAV-4", "VAV-5", "VAV-7", "VAV-REHEAT", "VAV-AHU-LEAVE"}
)

# Plant / VAV matrix: rule_id → (endpoint path, flag bool key, fault_h key)
PLANT_RULE_FIELDS: dict[str, tuple[str, str, str]] = {
    "AHU-SATDEV": ("/api/analytics/ahu-health", "sat_dev", "sat_dev_fault_h"),
    "AHU-DUCTHI": ("/api/analytics/ahu-health", "duct_high", "duct_high_fault_h"),
    "ECON-1": ("/api/analytics/ahu-health", "economizer", "economizer_fault_h"),
    "CHW-1": ("/api/analytics/chiller-health", "chw_1", "chw_1_fault_h"),
    "CHW-2": ("/api/analytics/chiller-health", "chw_2", "chw_2_fault_h"),
    "CHW-3": ("/api/analytics/chiller-health", "chw_3", "chw_3_fault_h"),
}

VAV_RULE_FIELDS: dict[str, tuple[str, str]] = {
    "VAV-1": ("poor_zone_performance", "comfort_fault_h"),
}


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
    if isinstance(body.get("analytics"), dict):
        return body["analytics"]
    return body


def load_expected(path: Path) -> list[dict]:
    return list(csv.DictReader(path.open()))


def hours_match(observed: float | None, expected: float) -> bool:
    if observed is None:
        return False
    return abs(float(observed) - float(expected)) <= HOURS_TOL


def tri_true(v: object) -> bool | None:
    if v is True:
        return True
    if v is False:
        return False
    if isinstance(v, str):
        s = v.strip().lower()
        if s == "true":
            return True
        if s == "false":
            return False
    return None


def as_float(v: object) -> float | None:
    if v is None or v == "":
        return None
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    if not (n == n):  # NaN
        return None
    return n


def check(
    name: str,
    ok: bool,
    detail: str,
    checks: list[dict],
) -> None:
    checks.append({"name": name, "ok": bool(ok), "detail": detail})
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {name}: {detail}")


def fetch_matrix(
    base: str,
    token: str,
    path: str,
    building: str,
) -> dict[str, dict]:
    body = http_json(
        "POST",
        f"{base}{path}",
        token=token,
        body=json.dumps({"building_id": building}).encode(),
        content_type="application/json",
    )
    env = unwrap_analytics(body)
    rows = env.get("rows") or []
    out: dict[str, dict] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        eid = str(row.get("equipment_id") or "").strip()
        if eid:
            out[eid] = row
    return out


def fetch_fdd_results(base: str, token: str, building: str) -> dict[tuple[str, str], dict]:
    body = http_json(
        "GET",
        f"{base}/api/fdd/results?building_id={building}",
        token=token,
        timeout=60.0,
    )
    out: dict[tuple[str, str], dict] = {}
    for row in body.get("results") or []:
        if not isinstance(row, dict):
            continue
        rid = str(row.get("rule_id") or "").strip()
        eid = str(row.get("equipment_id") or "").strip()
        if rid and eid:
            out[(rid, eid)] = row
    return out


def fdd_fault_hours(fdd: dict[tuple[str, str], dict], rule_id: str, eid: str) -> float | None:
    row = fdd.get((rule_id, eid))
    if not row:
        return None
    return as_float(row.get("fault_hours"))


def assert_plant_matrix_checks(
    base: str,
    token: str,
    building: str,
    expected_rows: list[dict],
    fdd: dict[tuple[str, str], dict],
    checks: list[dict],
) -> None:
    cache: dict[str, dict[str, dict]] = {}
    for exp in expected_rows:
        rule_id = exp["rule_id"]
        if rule_id not in PLANT_RULE_FIELDS:
            continue
        if exp.get("expected_status") != "FAULT":
            continue
        path, flag_key, fh_key = PLANT_RULE_FIELDS[rule_id]
        eid = exp["equipment_id"]
        want_h = float(exp["expected_fault_hours"])

        if path not in cache:
            cache[path] = fetch_matrix(base, token, path, building)
        row = cache[path].get(eid)
        if not row:
            check(
                f"plant_{rule_id}_{eid}_row",
                False,
                f"missing equipment row on {path}",
                checks,
            )
            continue

        flag = tri_true(row.get(flag_key))
        obs_h = as_float(row.get(fh_key))
        fdd_h = fdd_fault_hours(fdd, rule_id, eid)
        hours_src = obs_h if obs_h is not None else fdd_h
        hours_note = fh_key if obs_h is not None else "fdd.fault_hours"
        check(
            f"plant_{rule_id}_{eid}_flag",
            flag is True,
            f"{flag_key}={flag!r}",
            checks,
        )
        check(
            f"plant_{rule_id}_{eid}_fault_h",
            hours_match(hours_src, want_h),
            f"{hours_note}={hours_src} expected≈{want_h}"
            + (f" (matrix {fh_key} missing — redeploy central nightly)" if obs_h is None else ""),
            checks,
        )
        if obs_h is None and flag is True:
            check(
                f"plant_{rule_id}_{eid}_matrix_field_present",
                False,
                f"matrix {fh_key} is null but flag true — UI will show em-dash until central nightly redeploy",
                checks,
            )
        total = as_float(row.get("total_fault_h"))
        if total is not None and obs_h is not None:
            check(
                f"plant_{rule_id}_{eid}_total_ge_flag",
                total + 1e-9 >= (obs_h or 0.0),
                f"total_fault_h={total} flag_h={obs_h}",
                checks,
            )


def assert_vav_matrix_checks(
    base: str,
    token: str,
    building: str,
    expected_rows: list[dict],
    fdd: dict[tuple[str, str], dict],
    checks: list[dict],
) -> None:
    vav_rows = fetch_matrix(base, token, "/api/analytics/vav-health", building)

    for exp in expected_rows:
        if exp.get("expected_status") != "FAULT":
            continue
        rule_id = exp["rule_id"]
        eid = exp["equipment_id"]
        want_h = float(exp["expected_fault_hours"])
        row = vav_rows.get(eid)
        fdd_h = fdd_fault_hours(fdd, rule_id, eid)

        if rule_id in VAV_BROKEN_RULES:
            if not row:
                check(f"vav_{rule_id}_{eid}_row", False, "missing VAV health row", checks)
                continue
            broken_flag = tri_true(row.get("broken_box"))
            ids = str(row.get("broken_rule_ids") or "")
            check(
                f"vav_{rule_id}_{eid}_broken_flag",
                broken_flag is True and rule_id in ids.split(";"),
                f"broken_box={broken_flag!r} broken_rule_ids={ids!r}",
                checks,
            )
            check(
                f"vav_{rule_id}_{eid}_fault_h",
                hours_match(fdd_h, want_h),
                f"fdd.fault_hours={fdd_h} expected≈{want_h} (broken_box aggregate may include correlated rules)",
                checks,
            )
            matrix_h = as_float(row.get("broken_fault_hours"))
            if matrix_h is not None and fdd_h is not None:
                check(
                    f"vav_{rule_id}_{eid}_matrix_broken_h_ge_rule",
                    matrix_h + 1e-9 >= fdd_h,
                    f"broken_fault_hours={matrix_h} rule_h={fdd_h}",
                    checks,
                )
            continue

        if rule_id not in VAV_RULE_FIELDS:
            continue
        flag_key, fh_key = VAV_RULE_FIELDS[rule_id]
        if not row:
            check(f"vav_{rule_id}_{eid}_row", False, "missing VAV health row", checks)
            continue
        flag = tri_true(row.get(flag_key))
        obs_h = as_float(row.get(fh_key))
        hours_src = obs_h if obs_h is not None else fdd_h
        hours_note = fh_key if obs_h is not None else "fdd.fault_hours"
        check(
            f"vav_{rule_id}_{eid}_flag",
            flag is True,
            f"{flag_key}={flag!r}",
            checks,
        )
        check(
            f"vav_{rule_id}_{eid}_fault_h",
            hours_match(hours_src, want_h),
            f"{hours_note}={hours_src} expected≈{want_h}"
            + (f" (matrix {fh_key} missing — redeploy central nightly)" if obs_h is None else ""),
            checks,
        )


def assert_weather_oat_meteo(
    base: str,
    token: str,
    building: str,
    expected_rows: list[dict],
    checks: list[dict],
) -> None:
    meteo = [
        e
        for e in expected_rows
        if e.get("rule_id") == "OAT-METEO" and e.get("expected_status") == "FAULT"
    ]
    if not meteo:
        return
    body = http_json(
        "GET",
        f"{base}/api/fdd/results?building_id={building}",
        token=token,
        timeout=60.0,
    )
    results = body.get("results") or []
    for exp in meteo:
        eid = exp["equipment_id"]
        want_h = float(exp["expected_fault_hours"])
        hit = next(
            (
                r
                for r in results
                if str(r.get("rule_id") or "") == "OAT-METEO"
                and str(r.get("equipment_id") or "") == eid
            ),
            None,
        )
        if not hit:
            check(
                f"weather_OAT-METEO_{eid}",
                False,
                "missing FDD result row",
                checks,
            )
            continue
        st = str(hit.get("status") or "")
        obs_h = as_float(hit.get("fault_hours"))
        check(
            f"weather_OAT-METEO_{eid}_status",
            st == "FAULT",
            f"status={st!r}",
            checks,
        )
        check(
            f"weather_OAT-METEO_{eid}_fault_h",
            hours_match(obs_h, want_h),
            f"fault_hours={obs_h} expected≈{want_h}",
            checks,
        )


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

    if not EXPECTED.is_file():
        raise SystemExit(f"missing fixture: {EXPECTED}")

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    expected_rows = load_expected(EXPECTED)
    token = login(args.base, args.user, args.password)
    fdd = fetch_fdd_results(args.base, token, args.building_id)
    checks: list[dict] = []

    print(f">> plant health matrix fault hours ({args.building_id})")
    assert_plant_matrix_checks(
        args.base, token, args.building_id, expected_rows, fdd, checks
    )
    print(f">> VAV health matrix fault hours ({args.building_id})")
    assert_vav_matrix_checks(
        args.base, token, args.building_id, expected_rows, fdd, checks
    )
    print(f">> weather OAT-METEO fault hours ({args.building_id})")
    assert_weather_oat_meteo(
        args.base, token, args.building_id, expected_rows, checks
    )

    failed = [c for c in checks if not c["ok"]]
    summary = {
        "ok": not failed,
        "generated_at": utc_now(),
        "building_id": args.building_id,
        "checks": checks,
        "failed": [c["name"] for c in failed],
        "hours_tol": HOURS_TOL,
    }
    out = ARTIFACTS / "ofdd_health_matrix_fault_hours_checks.json"
    out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out} ({'PASS' if summary['ok'] else 'FAIL'} {len(failed)} fails)")
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
