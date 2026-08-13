#!/usr/bin/env python3
"""Target-pair soak for the synthetic 59-rule golden fixture.

Compares expected_faults.csv pairs only (ignore correlated detections).

  --side vibe19   Run agent_afdd inside vibe19 container (or host) against package ZIP
  --side ofdd     Upload package to OpenFDD central, run registry, compare results
  --side both     Default

Writes reports/wattlab-parity/artifacts/synthetic_59/*.csv + *.json
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = (
    ROOT
    / "reports/wattlab-parity/fixtures/synthetic_59/openfdd_synthetic_59_rule_fixture_v1"
)
ARTIFACTS = ROOT / "reports/wattlab-parity/artifacts/synthetic_59"
PKG_ZIP = FIXTURE / "OPENFDD_SYNTHETIC_59_RULE_WEEK_V1.zip"
EXPECTED = FIXTURE / "expected_faults.csv"
BUILDING_ID = "OPENFDD_SYNTHETIC_59_RULE_WEEK_V1"

HOURS_TOL = 0.05

# SQL registry primary ids that differ from pandas rule_id (aliases).
SQL_RULE_ALIASES: dict[str, list[str]] = {
    "FC13": ["FC13-SAT-HIGH", "FC13"],
}


def load_shared_fault_params() -> dict:
    """Same rule tuning blob for Vibe19 --params and OpenFDD session + /api/fdd/run.

    Source of truth: package session_config.json (confirm_min=0 equation-isolation).
    Also mirrors params onto SQL primary ids (e.g. FC13 → FC13-SAT-HIGH).
    """
    sess = FIXTURE / "OPENFDD_SYNTHETIC_59_RULE_WEEK_V1" / "session_config.json"
    params: dict = {}
    if sess.is_file():
        params = dict((json.loads(sess.read_text()).get("params")) or {})
    # Mirror alias keys so SQL registry primary ids get the same confirm_min.
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
    # PASS with 0h when expecting FAULT is a clear miss
    hours_ok = hours_match(fault_hours, want_h) if status_ok else False
    # Allow FAULT with matching hours even if samples unavailable
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


# ---- Vibe19 -----------------------------------------------------------------


def run_vibe19(
    package_zip: Path,
    expected: list[dict],
    host_workspace: Path,
) -> dict:
    """Copy package into vibe19 /data bind and run agent_afdd --run-rules."""
    host_workspace.mkdir(parents=True, exist_ok=True)
    dest_zip = host_workspace / package_zip.name
    shutil.copy2(package_zip, dest_zip)
    out_host = host_workspace / "synthetic_59_agent_out"
    summary_csv = out_host / "fdd_summary.csv"
    force = os.environ.get("SYNTH59_FORCE_VIBE19") == "1"
    reuse = (
        not force
        and summary_csv.is_file()
        and summary_csv.stat().st_size > 1000
    )
    if force and out_host.exists():
        shutil.rmtree(out_host)
    out_host.mkdir(parents=True, exist_ok=True)

    # Shared fault tuning (identical blob for Vibe19 --params).
    params_path = host_workspace / "synthetic_59_params.json"
    params_obj = load_shared_fault_params()
    params_path.write_text(json.dumps(params_obj, indent=2))

    container_pkg = f"/data/{package_zip.name}"
    container_out = "/data/synthetic_59_agent_out"
    container_params = "/data/synthetic_59_params.json"

    cmd = [
        "docker",
        "exec",
        "vibe19",
        "python",
        "scripts/agent_afdd.py",
        "--package",
        container_pkg,
        "--out",
        container_out,
        "--params",
        container_params,
        "--run-rules",
        "--no-bootstrap",
        "--export-profile",
        "summary",
    ]
    proc = None
    t0 = time.time()
    if reuse:
        print(f">> reusing existing {summary_csv} (set SYNTH59_FORCE_VIBE19=1 to rerun)")
        elapsed = 0.0
    else:
        print(">>", " ".join(cmd))
        proc = subprocess.run(cmd, capture_output=True, text=True)
        elapsed = time.time() - t0
        print(proc.stdout[-2000:] if proc.stdout else "")
        if proc.returncode != 0:
            print(proc.stderr[-2000:] if proc.stderr else "")
            # Export may crash after fdd_summary.csv is written (pandas quantile on bool).
            if not summary_csv.is_file():
                raise SystemExit(f"vibe19 agent_afdd failed rc={proc.returncode}")
            print(
                f"WARN: agent_afdd rc={proc.returncode} but {summary_csv.name} present; "
                "continuing with target-pair compare"
            )

    # Find results summary table
    summary_candidates = list(out_host.rglob("*summary*.csv")) + list(
        out_host.rglob("fdd_findings*.csv")
    )
    results_by_key: dict[tuple[str, str], dict] = {}
    # Also try JSON results
    for jf in out_host.rglob("*.json"):
        if jf.name in ("session_bootstrap.json", "session_config.json"):
            continue
        try:
            data = json.loads(jf.read_text())
        except Exception:
            continue
        rows = data if isinstance(data, list) else data.get("results") or data.get("rows")
        if not isinstance(rows, list):
            continue
        for r in rows:
            if not isinstance(r, dict):
                continue
            rid = str(r.get("rule_id") or "")
            eid = str(r.get("equipment_id") or "")
            if rid and eid:
                results_by_key[(rid, eid)] = r

    for csv_path in summary_candidates:
        try:
            for r in csv.DictReader(csv_path.open()):
                rid = str(r.get("rule_id") or "")
                eid = str(r.get("equipment_id") or "")
                if rid and eid:
                    results_by_key[(rid, eid)] = r
        except Exception:
            continue

    # Fallback: parse run_report / agent meta
    for p in out_host.rglob("run_report.json"):
        data = json.loads(p.read_text())
        for r in data.get("results") or []:
            rid = str(r.get("rule_id") or "")
            eid = str(r.get("equipment_id") or "")
            if rid and eid:
                results_by_key[(rid, eid)] = r

    pairs = []
    for exp in expected:
        key = (exp["rule_id"], exp["equipment_id"])
        obs = results_by_key.get(key)
        if not obs:
            pairs.append(
                {
                    **compare_pair(exp, "MISSING", None),
                    "notes": "no result row for target pair",
                }
            )
            continue
        status = str(obs.get("status") or "")
        fh = obs.get("fault_hours")
        if fh in ("", None):
            fh = obs.get("confirmed_fault_hours")
        try:
            fh_f = float(fh) if fh is not None and fh != "" else None
        except (TypeError, ValueError):
            fh_f = None
        row = compare_pair(exp, status, fh_f)
        row["notes"] = obs.get("notes") or ""
        pairs.append(row)

    matched = sum(1 for p in pairs if p["contract_match"])
    summary = {
        "side": "vibe19",
        "building_id": BUILDING_ID,
        "elapsed_s": round(elapsed, 1),
        "target_total": len(expected),
        "target_match": matched,
        "target_mismatch": len(expected) - matched,
        "mismatches": [
            {
                "rule_id": p["rule_id"],
                "equipment_id": p["equipment_id"],
                "observed_status": p["observed_status"],
                "observed_fault_hours": p["observed_fault_hours"],
            }
            for p in pairs
            if not p["contract_match"]
        ],
        "agent_stdout_tail": ((proc.stdout if proc else "") or "")[-500:],
        "agent_rc": None if proc is None else proc.returncode,
        "reused_existing_summary": reuse and proc is None,
        "result_keys_found": len(results_by_key),
        "generated_at": utc_now(),
    }
    write_csv(ARTIFACTS / "vibe19_target_pairs.csv", pairs)
    (ARTIFACTS / "vibe19_target_pairs_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n"
    )
    return summary


# ---- OpenFDD ----------------------------------------------------------------


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
    # Raw zip body (central accepts multipart, JSON base64, or raw zip)
    imp = http_json(
        "POST",
        f"{base}/api/csv/import/package",
        token=token,
        body=zip_bytes,
        content_type="application/zip",
        timeout=900.0,
    )
    if not imp.get("ok"):
        # try multipart via curl for robustness
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

    # Same fault tuning as Vibe19: PUT session-config then pass identical params to run.
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
        # fetch separately
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

    # Series overlay spot-checks
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
    ap.add_argument("--side", choices=("vibe19", "ofdd", "both"), default="both")
    ap.add_argument("--package", type=Path, default=PKG_ZIP)
    ap.add_argument("--expected", type=Path, default=EXPECTED)
    ap.add_argument("--api-base", default=os.environ.get("OPENFDD_API_BASE", "http://127.0.0.1:8080"))
    ap.add_argument("--user", default=os.environ.get("OPENFDD_USER", "admin"))
    ap.add_argument(
        "--password",
        default=os.environ.get("OPENFDD_ADMIN_PASSWORD", "bensbench-local-admin"),
    )
    ap.add_argument(
        "--workspace",
        type=Path,
        default=Path.home() / "wattlab_workspace",
        help="Host path bind-mounted to vibe19 /data",
    )
    ap.add_argument(
        "--skip-vibe19-rerun",
        action="store_true",
        help="Reuse handoff vibe19_integration_observed.csv instead of re-running agent",
    )
    args = ap.parse_args()
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    if not args.package.is_file():
        raise SystemExit(f"package zip missing: {args.package} (run synthetic_59_stage.py)")
    expected = load_expected(args.expected)
    print(f"expected target pairs: {len(expected)}")

    summaries = {}
    if args.side in ("vibe19", "both"):
        if args.skip_vibe19_rerun:
            obs_path = FIXTURE / "vibe19_integration_observed.csv"
            rows = list(csv.DictReader(obs_path.open()))
            pairs = []
            for exp in expected:
                o = next(
                    (
                        r
                        for r in rows
                        if r["rule_id"] == exp["rule_id"]
                        and r["equipment_id"] == exp["equipment_id"]
                    ),
                    None,
                )
                if not o:
                    pairs.append(compare_pair(exp, "MISSING", None))
                    continue
                fh = o.get("observed_fault_hours")
                try:
                    fh_f = float(fh) if fh not in (None, "") else None
                except ValueError:
                    fh_f = None
                row = compare_pair(exp, o.get("observed_status") or "", fh_f)
                row["contract_match"] = str(o.get("contract_match")).lower() in (
                    "true",
                    "1",
                )
                pairs.append(row)
            matched = sum(1 for p in pairs if p["contract_match"])
            summaries["vibe19"] = {
                "side": "vibe19",
                "source": "handoff vibe19_integration_observed.csv",
                "target_total": len(expected),
                "target_match": matched,
                "target_mismatch": len(expected) - matched,
                "mismatches": [
                    p for p in pairs if not p["contract_match"]
                ],
                "generated_at": utc_now(),
            }
            write_csv(ARTIFACTS / "vibe19_target_pairs.csv", pairs)
            (ARTIFACTS / "vibe19_target_pairs_summary.json").write_text(
                json.dumps(summaries["vibe19"], indent=2) + "\n"
            )
        else:
            summaries["vibe19"] = run_vibe19(args.package, expected, args.workspace)
        print(
            f"Vibe19 target match {summaries['vibe19']['target_match']}/"
            f"{summaries['vibe19']['target_total']}"
        )

    if args.side in ("ofdd", "both"):
        summaries["ofdd"] = run_ofdd(
            args.package, expected, args.api_base.rstrip("/"), args.user, args.password
        )
        print(
            f"OpenFDD SQL target match {summaries['ofdd']['target_match']}/"
            f"{summaries['ofdd']['target_total']}"
        )

    (ARTIFACTS / "soak_summary.json").write_text(
        json.dumps({"generated_at": utc_now(), "sides": summaries}, indent=2) + "\n"
    )
    print(f"artifacts → {ARTIFACTS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
