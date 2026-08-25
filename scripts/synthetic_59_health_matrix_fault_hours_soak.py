#!/usr/bin/env python3
"""Synthetic-59 Overview health-matrix and fault-hour closeout soak.

Run after ``synthetic_59_target_pair_soak.py --side ofdd`` so the fixture and
FDD registry results are populated.

The soak exercises every Overview health endpoint introduced for the split
matrices, validates ``n/m`` scoring (and ``?/m`` when any flag is Unknown),
requires every matrix flag to carry its ``{flag}_fault_h`` field, and compares
known synthetic FAULT rows to ``expected_faults.csv``.
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

FIXTURE = synthetic_fixture_dir()
ARTIFACTS = synthetic_artifacts_dir()
EXPECTED = FIXTURE / "expected_faults.csv"
BUILDING_ID = "OPENFDD_SYNTHETIC_59_RULE_WEEK_V1"
HOURS_TOL = 0.05

# endpoint -> rule_id -> matrix flag key
MATRIX_RULES: dict[str, dict[str, str]] = {
    "/api/analytics/ahu-temperature-health": {
        "AHU-SATDEV": "sat_dev",
        "FC2": "mat_low",
        "FC3": "mat_high",
        "FC7": "sat_low_heating",
        "FC13-SAT-HIGH": "sat_high_cooling",
    },
    "/api/analytics/ahu-pressure-health": {
        "AHU-DUCTHI": "duct_high",
        "FC1": "duct_low",
        "CMD-1": "fan_mismatch",
        "TRIM-1": "static_trim",
    },
    "/api/analytics/ahu-economizer-health": {
        "ECON-1": "stuck_closed",
        "ECON-2": "unfavorable",
        "ECON-3": "mech_without_econ",
        "ECON-4": "low_oa_fraction",
        "ECON-5": "preheat_over",
        "ECON-6": "freeze_risk",
        "ECON-7": "not_economizing",
    },
    "/api/analytics/chiller-health": {
        "CHW-1": "low_delta_t",
        "CHW-2": "dp_low",
        "CHW-3": "supply_band",
        "CHW-4": "flow_high",
        "CHW-NOLOAD-1": "no_load",
        "TRIM-4": "chw_reset",
    },
    "/api/analytics/cooling-tower-health": {
        "CW-APR-1": "approach_high",
        "CW-FAN-1": "fan_energy",
        "CW-OPT-1": "cw_optimization",
    },
    "/api/analytics/pid-hunting": {
        "FC4": "operating_state_hunt",
        "PID-HUNT-1": "control_output_hunt",
    },
    "/api/analytics/sensor-faults": {
        "SV-FLATLINE": "flatline",
        "SV-RANGE": "range",
        "SV-RATE": "rate",
        "SV-SPIKE": "spike",
        "SV-STALE": "stale",
    },
}

VAV_BROKEN_RULES = frozenset(
    {"VAV-3", "VAV-4", "VAV-5", "VAV-7", "VAV-REHEAT", "VAV-AHU-LEAVE"}
)
VAV_RULE_FIELDS = {"VAV-1": ("poor_zone_performance", "comfort_fault_h")}


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
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        try:
            return json.loads(detail)
        except json.JSONDecodeError:
            return {"ok": False, "error": f"HTTP {exc.code}: {detail[:500]}"}


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
    nested = body.get("analytics") if isinstance(body, dict) else None
    return nested if isinstance(nested, dict) else body


def as_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out else None


def tri(value: object) -> bool | None:
    if value is True or value is False:
        return bool(value)
    if isinstance(value, str):
        value = value.strip().lower()
        if value == "true":
            return True
        if value == "false":
            return False
    return None


def check(name: str, ok: bool, detail: str, checks: list[dict]) -> None:
    checks.append({"name": name, "ok": bool(ok), "detail": detail})
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {detail}")


def fetch_matrix(base: str, token: str, path: str, building: str) -> dict:
    body = http_json(
        "POST",
        f"{base}{path}",
        token=token,
        body=json.dumps({"building_id": building}).encode(),
        content_type="application/json",
    )
    return unwrap_analytics(body)


def rows_by_equipment(env: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for row in env.get("rows") or []:
        if isinstance(row, dict):
            eid = str(row.get("equipment_id") or "").strip()
            if eid:
                out[eid] = row
    return out


def load_expected() -> list[dict]:
    return list(csv.DictReader(EXPECTED.open()))


def expected_faults(rows: list[dict]) -> dict[tuple[str, str], float]:
    out: dict[tuple[str, str], float] = {}
    for row in rows:
        if row.get("expected_status") != "FAULT":
            continue
        try:
            out[(row["rule_id"], row["equipment_id"])] = float(row["expected_fault_hours"])
        except (KeyError, TypeError, ValueError):
            continue
    return out


def expected_score_label(row: dict, flags: list[str]) -> str:
    """Match plant_health score_label: ?/n when any flag is Unknown (null)."""
    total = len(flags)
    values = [tri(row.get(flag)) for flag in flags]
    if any(v is None for v in values):
        return f"?/{total}"
    hit = sum(v is True for v in values)
    return f"{hit}/{total}"


def assert_score_contract(path: str, row: dict, flags: list[str], checks: list[dict]) -> None:
    label = str(row.get("score_label") or "")
    expected_label = expected_score_label(row, flags)
    check(
        f"{path}_score_{row.get('equipment_id')}",
        label == expected_label,
        f"score_label={label!r} expected={expected_label!r}",
        checks,
    )
    for flag in flags:
        key = f"{flag}_fault_h"
        check(
            f"{path}_{row.get('equipment_id')}_{key}_present",
            key in row,
            f"field_present={key in row} value={row.get(key)!r}",
            checks,
        )
        if tri(row.get(flag)) is True:
            check(
                f"{path}_{row.get('equipment_id')}_{key}_for_fault",
                as_float(row.get(key)) is not None,
                f"flag=true {key}={row.get(key)!r}",
                checks,
            )


def assert_new_matrices(
    base: str,
    token: str,
    building: str,
    expected_rows: list[dict],
    checks: list[dict],
) -> None:
    faults = expected_faults(expected_rows)
    all_expected_rules = {rule for rules in MATRIX_RULES.values() for rule in rules}
    expected_by_endpoint: dict[str, list[tuple[str, str, float]]] = {}
    for path, rules in MATRIX_RULES.items():
        expected_by_endpoint[path] = [
            (rule, eid, hours)
            for (rule, eid), hours in faults.items()
            if rule in rules
        ]

    for path, rule_map in MATRIX_RULES.items():
        print(f">> {path}")
        env = fetch_matrix(base, token, path, building)
        rows = list(env.get("rows") or [])
        qv = str(env.get("query_version") or "")
        check(
            f"endpoint_{path}",
            bool(env) and qv != "",
            f"query_version={qv!r} rows={len(rows)}",
            checks,
        )
        if path == "/api/analytics/sensor-faults" and not expected_by_endpoint[path]:
            check(
                "sensor_clean_rows_empty",
                rows == [],
                f"rows={len(rows)} (clean contract requires rows: [])",
                checks,
            )
        for row in rows:
            if isinstance(row, dict):
                assert_score_contract(path, row, list(rule_map.values()), checks)

        by_eid = rows_by_equipment(env)
        for rule_id, eid, want_h in expected_by_endpoint[path]:
            flag = rule_map[rule_id]
            row = by_eid.get(eid)
            check(
                f"{rule_id}_{eid}_row",
                row is not None,
                f"endpoint={path}",
                checks,
            )
            if row is None:
                continue
            observed = as_float(row.get(f"{flag}_fault_h"))
            check(
                f"{rule_id}_{eid}_flag",
                tri(row.get(flag)) is True,
                f"{flag}={row.get(flag)!r}",
                checks,
            )
            check(
                f"{rule_id}_{eid}_fault_h",
                observed is not None and abs(observed - want_h) <= HOURS_TOL,
                f"{flag}_fault_h={observed} expected≈{want_h}",
                checks,
            )

    covered = {rule for rules in MATRIX_RULES.values() for rule in rules}
    check(
        "matrix_rule_map_nonempty",
        bool(covered & all_expected_rules),
        f"mapped_rules={len(covered)}",
        checks,
    )


def fetch_fdd_results(base: str, token: str, building: str) -> dict[tuple[str, str], dict]:
    body = http_json(
        "GET",
        f"{base}/api/fdd/results?building_id={building}",
        token=token,
        timeout=60.0,
    )
    out: dict[tuple[str, str], dict] = {}
    for row in body.get("results") or []:
        if isinstance(row, dict):
            rid = str(row.get("rule_id") or "").strip()
            eid = str(row.get("equipment_id") or "").strip()
            if rid and eid:
                out[(rid, eid)] = row
    return out


def assert_vav_and_weather(
    base: str,
    token: str,
    building: str,
    expected_rows: list[dict],
    checks: list[dict],
) -> None:
    env = fetch_matrix(base, token, "/api/analytics/vav-health", building)
    vav = rows_by_equipment(env)
    fdd = fetch_fdd_results(base, token, building)
    for exp in expected_rows:
        if exp.get("expected_status") != "FAULT":
            continue
        rule_id = exp.get("rule_id", "")
        eid = exp.get("equipment_id", "")
        want_h = float(exp.get("expected_fault_hours") or 0)
        if rule_id in VAV_BROKEN_RULES:
            row = vav.get(eid)
            check(f"vav_{rule_id}_{eid}_row", row is not None, "VAV health row", checks)
            if row:
                ids = str(row.get("broken_rule_ids") or "").split(";")
                check(
                    f"vav_{rule_id}_{eid}_flag",
                    tri(row.get("broken_box")) is True and rule_id in ids,
                    f"broken_rule_ids={ids}",
                    checks,
                )
        elif rule_id in VAV_RULE_FIELDS:
            row = vav.get(eid)
            flag, hours_key = VAV_RULE_FIELDS[rule_id]
            check(f"vav_{rule_id}_{eid}_row", row is not None, "VAV health row", checks)
            if row:
                observed = as_float(row.get(hours_key))
                check(f"vav_{rule_id}_{eid}_flag", tri(row.get(flag)) is True, f"{flag}={row.get(flag)!r}", checks)
                check(
                    f"vav_{rule_id}_{eid}_fault_h",
                    observed is not None and abs(observed - want_h) <= HOURS_TOL,
                    f"{hours_key}={observed} expected≈{want_h}",
                    checks,
                )
        if rule_id == "OAT-METEO":
            row = fdd.get((rule_id, eid))
            observed = as_float(row.get("fault_hours")) if row else None
            check(f"weather_{eid}_row", row is not None, "FDD weather result", checks)
            check(
                f"weather_{eid}_fault_h",
                observed is not None and abs(observed - want_h) <= HOURS_TOL,
                f"fault_hours={observed} expected≈{want_h}",
                checks,
            )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default=os.environ.get("OPENFDD_API_BASE", "http://127.0.0.1:8080"))
    ap.add_argument("--user", default=os.environ.get("OPENFDD_ADMIN_USER", "admin"))
    ap.add_argument("--password", default=os.environ.get("OPENFDD_ADMIN_PASSWORD", "bensbench-local-admin"))
    ap.add_argument("--building-id", default=BUILDING_ID)
    args = ap.parse_args()

    if not EXPECTED.is_file():
        raise SystemExit(f"missing fixture: {EXPECTED}")

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    expected_rows = load_expected()
    token = login(args.base, args.user, args.password)
    checks: list[dict] = []

    assert_new_matrices(args.base, token, args.building_id, expected_rows, checks)
    print(">> VAV/weather compatibility")
    assert_vav_and_weather(args.base, token, args.building_id, expected_rows, checks)

    failed = [item for item in checks if not item["ok"]]
    summary = {
        "ok": not failed,
        "generated_at": utc_now(),
        "building_id": args.building_id,
        "checks": checks,
        "failed": [item["name"] for item in failed],
        "hours_tol": HOURS_TOL,
        "endpoints": list(MATRIX_RULES),
    }
    out = ARTIFACTS / "ofdd_health_matrix_fault_hours_checks.json"
    out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out} ({'PASS' if summary['ok'] else 'FAIL'} {len(failed)} fails)")
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
