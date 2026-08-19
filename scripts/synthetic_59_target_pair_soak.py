#!/usr/bin/env python3
"""Target-pair soak for the synthetic 59-rule golden fixture.

Compares expected_faults.csv pairs only (ignore correlated detections).

Uploads package to OpenFDD central, runs registry, compares results to golden.
(Vibe19 dual-parity retired — use ``--side ofdd`` only.)

Writes reports/eplus-dump/artifacts/synthetic_59/*.csv + *.json
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from eplus_paths import synthetic_artifacts_dir, synthetic_fixture_dir

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = synthetic_fixture_dir()
ARTIFACTS = synthetic_artifacts_dir()
PKG_ZIP = FIXTURE / "OPENFDD_SYNTHETIC_59_RULE_WEEK_V1.zip"
EXPECTED = FIXTURE / "expected_faults.csv"
BUILDING_ID = "OPENFDD_SYNTHETIC_59_RULE_WEEK_V1"

HOURS_TOL = 0.05

# SQL registry primary ids that differ from pandas rule_id (aliases).
SQL_RULE_ALIASES: dict[str, list[str]] = {
    "FC13": ["FC13-SAT-HIGH", "FC13"],
}


def load_shared_fault_params() -> dict:
    """Rule tuning blob for OpenFDD session + /api/fdd/run."""
    sess = FIXTURE / "OPENFDD_SYNTHETIC_59_RULE_WEEK_V1" / "session_config.json"
    params: dict = {}
    if sess.is_file():
        params = dict((json.loads(sess.read_text()).get("params")) or {})
    for pandas_id, aliases in SQL_RULE_ALIASES.items():
        if pandas_id not in params:
            continue
        for alias in aliases:
            params.setdefault(alias, dict(params[pandas_id]))
    return params


def load_expected(path: Path) -> list[dict]:
    return list(csv.DictReader(path.open()))


def lookup_result(
    by_key: dict[tuple[str, str], dict], rule_id: str, equipment_id: str
) -> dict | None:
    for rid in SQL_RULE_ALIASES.get(rule_id, [rule_id]):
        hit = by_key.get((rid, equipment_id))
        if hit:
            return hit
    return by_key.get((rule_id, equipment_id))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_csv(path: Path, rows: list[dict], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("")
        return
    fn = fieldnames or list(rows[0].keys())
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fn, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def http_json(
    method: str,
    url: str,
    token: str | None = None,
    body: bytes | None = None,
    content_type: str | None = None,
    timeout: float = 600.0,
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
        timeout=30,
    )
    tok = out.get("access_token") or out.get("token")
    if not tok:
        raise SystemExit(f"login failed: {out}")
    return str(tok)


def hours_match(observed: float | None, expected: float) -> bool:
    if observed is None:
        return False
    return abs(float(observed) - float(expected)) <= HOURS_TOL


def compare_pair(exp: dict, status: str, fault_hours: float | None) -> dict:
    want_status = exp["expected_status"]
    want_h = float(exp["expected_fault_hours"])
    status_ok = status == want_status
    hours_ok = hours_match(fault_hours, want_h) if status_ok else False
    contract = status_ok and hours_ok
    return {
        "rule_id": exp["rule_id"],
        "equipment_id": exp["equipment_id"],
        "expected_status": want_status,
        "observed_status": status,
        "expected_fault_hours": want_h,
        "observed_fault_hours": fault_hours if fault_hours is not None else "",
        "status_match": status_ok,
        "hours_match": hours_ok,
        "contract_match": contract,
        "expected_fault_start_utc": exp.get("expected_fault_start_utc", ""),
        "expected_fault_end_exclusive_utc": exp.get(
            "expected_fault_end_exclusive_utc", ""
        ),
        "expected_fault_samples": exp.get("expected_fault_samples", ""),
    }


def run_ofdd(
    package_zip: Path,
    expected: list[dict],
    base: str,
    user: str,
    password: str,
) -> dict:
    token = login(base, user, password)
    print(f"logged in → upload {package_zip.name}")
    zip_bytes = package_zip.read_bytes()
    t0 = time.time()
    imp = http_json(
        "POST",
        f"{base}/api/csv/import/package",
        token=token,
        body=zip_bytes,
        content_type="application/zip",
        timeout=900.0,
    )
    if not imp.get("ok"):
        print("raw zip import failed, trying curl multipart…", imp.get("error"))
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".json") as tf:
            cmd = [
                "curl",
                "-sf",
                "-X",
                "POST",
                f"{base}/api/csv/import/package",
                "-H",
                f"Authorization: Bearer {token}",
                "-F",
                f"file=@{package_zip}",
                "-o",
                tf.name,
            ]
            subprocess.run(cmd, check=False)
            imp = json.loads(Path(tf.name).read_text() or "{}")
    if not imp.get("ok"):
        raise SystemExit(f"package import failed: {imp}")
    building = imp.get("building_id") or BUILDING_ID
    print(
        f"imported building={building} equipment={imp.get('equipment_written')} "
        f"rows={imp.get('total_rows')} ms={imp.get('total_ms')}"
    )

    sess_path = FIXTURE / "OPENFDD_SYNTHETIC_59_RULE_WEEK_V1" / "session_config.json"
    sess_cfg = json.loads(sess_path.read_text()) if sess_path.is_file() else {}
    params = load_shared_fault_params()
    put_body = {
        **sess_cfg,
        "schema_version": sess_cfg.get("schema_version") or "openfdd_session_v1",
        "params": params,
    }
    put = http_json(
        "PUT",
        f"{base}/api/fdd/session-config",
        token=token,
        body=json.dumps(put_body).encode(),
        content_type="application/json",
        timeout=60.0,
    )
    if not put.get("ok"):
        print("WARN: session-config PUT failed:", put.get("error") or put)

    run_body = {
        "mode": "registry",
        "building_id": building,
        "params": params,
    }
    print(
        f">> POST /api/fdd/run (registry, shared confirm_min params "
        f"n_rules={len(params)})"
    )
    run = http_json(
        "POST",
        f"{base}/api/fdd/run",
        token=token,
        body=json.dumps(run_body).encode(),
        content_type="application/json",
        timeout=1200.0,
    )
    elapsed = time.time() - t0
    if not run.get("ok"):
        raise SystemExit(f"fdd run failed: {run}")
    print(
        f"run ok rules_succeeded={run.get('rules_succeeded')} "
        f"failed={run.get('rules_failed')} skipped={run.get('rules_skipped')} "
        f"total_ms={run.get('total_ms')}"
    )

    results = run.get("results") or []
    if not results:
        res = http_json(
            "GET",
            f"{base}/api/fdd/results?building_id={building}",
            token=token,
            timeout=60,
        )
        results = res.get("results") or res.get("rows") or []

    by_key: dict[tuple[str, str], dict] = {}
    for r in results:
        rid = str(r.get("rule_id") or "")
        eid = str(r.get("equipment_id") or "")
        if rid and eid:
            by_key[(rid, eid)] = r

    pairs = []
    for exp in expected:
        obs = lookup_result(by_key, exp["rule_id"], exp["equipment_id"])
        if not obs:
            pairs.append(
                {
                    **compare_pair(exp, "MISSING", None),
                    "notes": "no OFDD result for target pair",
                    "missing_roles": "",
                    "sql_rule_id": "",
                }
            )
            continue
        status = str(obs.get("status") or "")
        fh = obs.get("fault_hours")
        try:
            fh_f = float(fh) if fh is not None else None
        except (TypeError, ValueError):
            fh_f = None
        row = compare_pair(exp, status, fh_f)
        mr = obs.get("missing_roles")
        row["missing_roles"] = (
            ",".join(mr) if isinstance(mr, list) else (str(mr) if mr else "")
        )
        row["notes"] = str(obs.get("notes") or "")
        row["sql_rule_id"] = str(obs.get("rule_id") or "")
        pairs.append(row)

    spot = []
    for rule_id, equipment_id in (
        ("FC1", "AHU_CASE_FC1"),
        ("VAV-1", "VAV_CASE_VAV_1"),
        ("SCHED-1", "AHU_CASE_SCHED_1"),
    ):
        series = http_json(
            "GET",
            f"{base}/api/fdd/series?equipment_id={equipment_id}"
            f"&rule_id={rule_id}&building_id={building}",
            token=token,
            timeout=120,
        )
        rows = series.get("rows") or []
        cf = [
            r.get("confirmed_fault")
            for r in rows
            if isinstance(r, dict) and r.get("confirmed_fault") is not None
        ]
        spot.append(
            {
                "rule_id": rule_id,
                "equipment_id": equipment_id,
                "ok": series.get("ok"),
                "has_confirmed_fault": series.get("has_confirmed_fault"),
                "fault_overlay_source": series.get("fault_overlay_source"),
                "fault_overlay_hits": series.get("fault_overlay_hits"),
                "row_count": len(rows),
                "confirmed_fault_nonnull": len(cf),
                "error": series.get("error"),
            }
        )

    matched = sum(1 for p in pairs if p["contract_match"])
    summary = {
        "side": "ofdd_sql",
        "building_id": building,
        "elapsed_s": round(elapsed, 1),
        "import": {
            "equipment_written": imp.get("equipment_written"),
            "total_rows": imp.get("total_rows"),
            "warnings": imp.get("warnings") or [],
        },
        "run": {
            "rules_run": run.get("rules_run"),
            "rules_succeeded": run.get("rules_succeeded"),
            "rules_failed": run.get("rules_failed"),
            "rules_skipped": run.get("rules_skipped"),
            "total_ms": run.get("total_ms"),
            "result_count": len(results),
        },
        "target_total": len(expected),
        "target_match": matched,
        "target_mismatch": len(expected) - matched,
        "mismatches": [
            {
                "rule_id": p["rule_id"],
                "equipment_id": p["equipment_id"],
                "observed_status": p["observed_status"],
                "observed_fault_hours": p["observed_fault_hours"],
                "missing_roles": p.get("missing_roles"),
            }
            for p in pairs
            if not p["contract_match"]
        ],
        "series_spot_checks": spot,
        "generated_at": utc_now(),
        "central_health": http_json("GET", f"{base}/api/health", timeout=10),
    }
    write_csv(ARTIFACTS / "ofdd_sql_target_pairs.csv", pairs)
    (ARTIFACTS / "ofdd_sql_target_pairs_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n"
    )
    (ARTIFACTS / "ofdd_series_spot_checks.json").write_text(
        json.dumps(spot, indent=2) + "\n"
    )
    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--side",
        choices=("ofdd",),
        default="ofdd",
        help="OpenFDD central only (vibe19 retired)",
    )
    ap.add_argument("--package", type=Path, default=PKG_ZIP)
    ap.add_argument("--expected", type=Path, default=EXPECTED)
    ap.add_argument("--api-base", default=os.environ.get("OPENFDD_API_BASE", "http://127.0.0.1:8080"))
    ap.add_argument("--user", default=os.environ.get("OPENFDD_USER", "admin"))
    ap.add_argument(
        "--password",
        default=os.environ.get("OPENFDD_ADMIN_PASSWORD", "bensbench-local-admin"),
    )
    args = ap.parse_args()
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    if not args.package.is_file():
        raise SystemExit(f"package zip missing: {args.package} (run synthetic_59_stage.py)")
    expected = load_expected(args.expected)
    print(f"expected target pairs: {len(expected)}")

    summary = run_ofdd(
        args.package, expected, args.api_base.rstrip("/"), args.user, args.password
    )
    print(
        f"OpenFDD SQL target match {summary['target_match']}/"
        f"{summary['target_total']}"
    )

    (ARTIFACTS / "soak_summary.json").write_text(
        json.dumps({"generated_at": utc_now(), "sides": {"ofdd": summary}}, indent=2) + "\n"
    )
    print(f"artifacts → {ARTIFACTS}")
    return 0 if summary["target_mismatch"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
