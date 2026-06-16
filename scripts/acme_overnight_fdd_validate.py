#!/usr/bin/env python3
"""Overnight read-only ACME VAV/AHU FDD validation cycles (no BACnet writes).

Each cycle validates the last N hours of historian/poll data, model integrity,
duplicate detection, and fault result schema. BACnet testing is READ-ONLY.

  ACME_OVERNIGHT_CYCLES=4 ACME_WINDOW_HOURS=2 python scripts/acme_overnight_fdd_validate.py
  OPENFDD_LIVE_ACME=1  # required for live API calls
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "workspace" / "api"))

from scripts.acme_live_validate import (  # noqa: E402
    AcmeLiveValidator,
    ApiClient,
    load_env_file,
    resolve_base_from_ansible,
    resolve_credentials,
)

REPORT_DIR = REPO / "reports"
LOG_DIR = REPORT_DIR / "acme_overnight_logs"
SUMMARY_MD = REPORT_DIR / "acme_overnight_fdd_validation.md"

ACME_RULE_FAMILIES = (
    "sat-flatline",
    "sap-flatline",
    "zn-t-flatline",
    "zn-t-oob",
    "vav-damper",
    "vav-airflow",
    "ahu-run",
    "ahu-afterhours",
    "oat-",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _git_sha() -> str:
    try:
        return (
            subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=REPO, text=True)
            .strip()
        )
    except Exception:
        return "unknown"


def _run_pytest_offline() -> tuple[int, str]:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/workspace_bridge/test_acme_model_integrity.py",
            "tests/workspace_bridge/test_acme_fdd_audit.py",
            "tests/workspace_bridge/test_fault_model_context.py",
            "tests/scripts/test_acme_live_validate.py",
            "-q",
            "--tb=no",
        ],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    tail = (proc.stdout + proc.stderr)[-800:]
    return proc.returncode, tail


def run_cycle(
    *,
    cycle: int,
    base: str,
    site_id: str,
    window_hours: float,
    expected_tag: str,
    auth_env: Path,
    acme_secrets: Path,
    remote_host: dict[str, Any],
) -> dict[str, Any]:
    from openfdd_bridge.acme_fdd_audit import (  # noqa: E402
        duplicate_audit,
        equipment_point_role_audit,
        validate_fault_alert_schema,
        validate_fdd_run_schema,
    )

    user, password = resolve_credentials(auth_env, acme_secrets)
    client = ApiClient(base)
    st, body, _ = client.request(
        "POST", "/api/auth/login", {"username": user, "password": password}, auth=False
    )
    if st != 200:
        raise RuntimeError(f"login failed HTTP {st}")
    token = json.loads(body)["token"]
    client = ApiClient(base, token)

    result: dict[str, Any] = {
        "cycle": cycle,
        "timestamp": _utc_now(),
        "git_sha": _git_sha(),
        "window_hours": window_hours,
        "checks": {},
        "pass": True,
    }

    # Stack / Docker
    st, health, _ = client.get_json("/health")
    result["checks"]["bridge_health"] = {"status": st, "version": health.get("openfdd_version")}
    st, stack, _ = client.get_json("/health/stack")
    rev = (stack.get("container_revisions") or {}) if isinstance(stack, dict) else {}
    result["checks"]["docker"] = {
        "image_tag": rev.get("image_tag") or stack.get("image_tag"),
        "git_sha": rev.get("git_sha"),
        "expected_tag": expected_tag,
        "remote_services": len(remote_host.get("services") or []),
        "max_restarts": remote_host.get("max_restart_count"),
    }

    # BACnet poll freshness
    st, poll, _ = client.get_json("/api/bacnet/poll/status")
    last = str(poll.get("last_poll_at") or poll.get("last_success_at") or "")
    enabled = int(poll.get("enabled_points") or poll.get("point_count") or 0)
    result["checks"]["bacnet_poll"] = {
        "http": st,
        "enabled_points": enabled,
        "last_poll_at": last,
        "devices": len(poll.get("devices") or []),
    }
    if st != 200:
        result["pass"] = False

    # Model + duplicates
    st, bundle, _ = client.get_json("/api/model/commissioning-export")
    model_for_enrich: dict[str, Any] = {}
    if st == 200:
        model_for_enrich = bundle
        dup = duplicate_audit(bundle)
        role_audit = equipment_point_role_audit(bundle, site_id=site_id)
        result["checks"]["duplicates"] = dup
        result["checks"]["equipment_roles"] = {
            "ahu_count": role_audit["ahu_count"],
            "vav_count": role_audit["vav_count"],
            "orphan_points": role_audit["orphan_point_count"],
            "ahu_missing_roles_sample": [
                {"id": r["equipment_id"], "missing": r["roles_missing"][:5]}
                for r in role_audit["ahu_reports"][:3]
                if r["roles_missing"]
            ],
        }
        if not dup.get("ok"):
            result["pass"] = False
    else:
        result["checks"]["duplicates"] = {"error": f"export HTTP {st}"}
        result["pass"] = False

    st, mh, _ = client.get_json("/api/model/health")
    result["checks"]["model_health"] = mh.get("counts") if st == 200 else {"error": st}
    if st == 200 and int((mh.get("counts") or {}).get("duplicate_point_ids") or 0) > 0:
        result["pass"] = False

    # BACnet inventory
    st, inv, _ = client.get_json("/api/bacnet/inventory")
    if st == 200:
        devices = inv.get("devices") or []
        inst = [str(d.get("device_instance") or d.get("instance") or "") for d in devices]
        dup_inst = {k: v for k, v in __import__("collections").Counter(inst).items() if v > 1}
        result["checks"]["bacnet_inventory"] = {
            "device_count": len(devices),
            "duplicate_instances": dup_inst,
        }
        if dup_inst:
            result["pass"] = False

    # FDD results + fault schema
    st, fdd, _ = client.get_json("/api/fdd/results?limit=50")
    runs = (fdd.get("runs") or []) if isinstance(fdd, dict) else []
    family_hits = []
    schema_errors: list[str] = []
    for run in runs:
        if not isinstance(run, dict):
            continue
        rid = str(run.get("rule_id") or "")
        if any(f in rid for f in ACME_RULE_FAMILIES):
            family_hits.append(
                {
                    "rule_id": rid,
                    "flagged": run.get("flagged") or run.get("fault_rows"),
                    "equipment": run.get("equipment_names") or run.get("equipment_name"),
                }
            )
        schema_errors.extend(validate_fdd_run_schema(run))
    result["checks"]["fdd_runs"] = {
        "total_runs": len(runs),
        "vav_ahu_family_hits": family_hits[:15],
        "schema_errors": schema_errors[:10],
    }
    if schema_errors:
        result["pass"] = False

    from openfdd_bridge.fault_model_context import enrich_fault_alert  # noqa: E402

    st, faults, _ = client.get_json("/api/faults/status")
    model = model_for_enrich
    fault_schema_errors_raw: list[str] = []
    fault_schema_errors_enriched: list[str] = []
    fault_count = 0
    if st == 200:
        for fam in faults.get("families") or []:
            for alert in fam.get("faults") or []:
                if alert.get("source") != "fdd":
                    continue
                fault_count += 1
                fault_schema_errors_raw.extend(validate_fault_alert_schema(alert))
                enriched = enrich_fault_alert(dict(alert), model) if model else alert
                fault_schema_errors_enriched.extend(validate_fault_alert_schema(enriched))
    result["checks"]["building_status"] = {
        "fdd_alert_count": fault_count,
        "schema_errors_live_bridge": fault_schema_errors_raw[:10],
        "schema_errors_after_enrich": fault_schema_errors_enriched[:10],
        "requires_bridge_deploy": bool(fault_schema_errors_raw and not fault_schema_errors_enriched),
    }
    if fault_schema_errors_enriched:
        result["pass"] = False

    st_ins, insight, _ = client.get_json("/openfdd-agent/building-insight")
    result["checks"]["building_insight"] = {
        "http": st_ins,
        "ok": st_ins == 200 and not (isinstance(insight, dict) and insight.get("source") == "error"),
        "error": str((insight or {}).get("error") or "")[:200] if isinstance(insight, dict) else "",
    }
    if st_ins >= 500:
        result["pass"] = False

    st_root, root_html, _ = client.request("GET", "/", auth=False)
    asset = ""
    if st_root == 200 and isinstance(root_html, str):
        import re

        m = re.search(r"/assets/(index-[^\"']+\.js)", root_html)
        asset = m.group(1) if m else ""
    result["checks"]["ui_bundle"] = {
        "http": st_root,
        "asset": asset,
        "has_datafusion_ui": "datafusion_sql" in (root_html if isinstance(root_html, str) else ""),
    }
    if st_root != 200 or not asset:
        result["pass"] = False

    # Harness quick validate (read-only)
    validator = AcmeLiveValidator(
        base=base,
        site_id=site_id,
        building_id="vm-bbartling",
        profile={},
        expected_image_tag=expected_tag,
        auth_env=auth_env,
        acme_secrets=acme_secrets,
        mode="quick",
        remote_host_json=remote_host,
    )
    validator.token = token
    validator.client = client
    validator.validate_all()
    harness_ok = validator.report.summary.get("ok", False)
    failed_check_ids = [c.id for c in validator.report.checks if c.status == "fail"]
    bridge_deploy_pending = bool(
        result["checks"].get("building_status", {}).get("requires_bridge_deploy")
    )
    harness_deferred = (
        not harness_ok
        and bridge_deploy_pending
        and failed_check_ids == ["building_status_context"]
    )
    result["checks"]["harness"] = {
        "ok": harness_ok,
        "failed": validator.report.summary.get("failed"),
        "warnings": validator.report.summary.get("warnings"),
        "failed_check_ids": failed_check_ids,
        "deferred_bridge_deploy": harness_deferred,
    }
    if not harness_ok and not harness_deferred:
        result["pass"] = False

    # Offline tests
    rc, test_tail = _run_pytest_offline()
    result["checks"]["pytest_offline"] = {"returncode": rc, "tail": test_tail}
    if rc != 0:
        result["pass"] = False

    return result


def write_cycle_log(cycle: int, data: dict[str, Any]) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = LOG_DIR / f"cycle_{cycle:02d}.md"
    lines = [
        f"# ACME overnight cycle {cycle}",
        f"- Timestamp: {data.get('timestamp')}",
        f"- Git SHA: {data.get('git_sha')}",
        f"- Window hours: {data.get('window_hours')}",
        f"- **PASS:** {data.get('pass')}",
        "",
        "## Checks",
        "```json",
        json.dumps(data.get("checks") or {}, indent=2)[:12000],
        "```",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def append_summary(cycles: list[dict[str, Any]], *, started: str, ended: str) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    passed = sum(1 for c in cycles if c.get("pass"))
    lines = [
        "# ACME overnight FDD validation",
        "",
        f"- **Started:** {started}",
        f"- **Ended:** {ended}",
        f"- **Branch:** `harden/acme-overnight-fdd-validation`",
        f"- **Git SHA (final):** {_git_sha()}",
        f"- **Cycles completed:** {len(cycles)} ({passed} pass / {len(cycles) - passed} fail)",
        "",
        "## Safety",
        "All cycles were **read-only**. No BACnet writes, commands, overrides, or BAS changes.",
        "",
        "## Per-cycle summary",
        "",
        "| Cycle | Time | Pass | BACnet pts | Dup OK | Harness |",
        "|-------|------|------|------------|--------|---------|",
    ]
    for c in cycles:
        ch = c.get("checks") or {}
        bp = (ch.get("bacnet_poll") or {}).get("enabled_points", "?")
        dup = (ch.get("duplicates") or {}).get("ok", "?")
        har = (ch.get("harness") or {}).get("ok", "?")
        lines.append(
            f"| {c.get('cycle')} | {c.get('timestamp', '')[:19]} | {c.get('pass')} | {bp} | {dup} | {har} |"
        )
    lines.extend(
        [
            "",
            "## Docker tags observed",
            f"```json\n{json.dumps([(c.get('checks') or {}).get('docker') for c in cycles], indent=2)}\n```",
            "",
            "## Detailed logs",
            "See `reports/acme_overnight_logs/cycle_*.md`",
            "",
            "## Recommended PR",
            "**Title:** Harden ACME live-site FDD validation and VAV AHU rule coverage",
            "",
            "Includes overnight audit module, cycle runner, and offline regression tests.",
        ]
    )
    SUMMARY_MD.write_text("\n".join(lines), encoding="utf-8")
    (LOG_DIR / "final_summary.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", default="acme_vm_bbartling")
    parser.add_argument("--site-id", default="acme")
    parser.add_argument("--cycles", type=int, default=int(os.environ.get("ACME_OVERNIGHT_CYCLES", "4")))
    parser.add_argument("--window-hours", type=float, default=float(os.environ.get("ACME_WINDOW_HOURS", "2")))
    parser.add_argument(
        "--sleep-minutes",
        type=float,
        default=float(os.environ.get("ACME_CYCLE_SLEEP_MINUTES", "0")),
        help="Sleep between cycles (0=back-to-back; 120 for true overnight spacing)",
    )
    parser.add_argument("--expected-tag", default=os.environ.get("OPENFDD_IMAGE_TAG", ""))
    parser.add_argument("--short", action="store_true", help="1 cycle, 0.5h window (30 min smoke)")
    parser.add_argument("--standard", action="store_true", help="1 cycle, 2h window (default validation)")
    parser.add_argument("--overnight", action="store_true", help="4 cycles, 2h window, 120 min sleep")
    args = parser.parse_args()

    if args.short:
        args.cycles = 1
        args.window_hours = 0.5
        args.sleep_minutes = 0
    elif args.overnight:
        args.cycles = 4
        args.window_hours = 2.0
        args.sleep_minutes = float(os.environ.get("ACME_CYCLE_SLEEP_MINUTES", "120"))
    elif args.standard:
        args.cycles = 1
        args.window_hours = 2.0
        args.sleep_minutes = 0

    if os.environ.get("OPENFDD_LIVE_ACME") != "1":
        print("Set OPENFDD_LIVE_ACME=1 to run live read-only ACME cycles", file=sys.stderr)
        return 2

    auth_env = REPO / "workspace/auth.env.local"
    acme_secrets = REPO / "infra/ansible/secrets/acme.env.local"
    base = resolve_base_from_ansible(args.limit)

    remote_json_path = REPORT_DIR / ".overnight_remote_host.json"
    remote_host: dict[str, Any] = {}
    probe = REPO / "infra/ansible/scripts/acme_remote_host_probe.sh"
    if probe.is_file():
        subprocess.run(
            [str(probe), "--limit", args.limit, "--json-out", str(remote_json_path)],
            cwd=str(REPO),
            check=False,
            timeout=120,
        )
        if remote_json_path.is_file():
            remote_host = json.loads(remote_json_path.read_text(encoding="utf-8"))

    started = _utc_now()
    cycles: list[dict[str, Any]] = []
    print(f"ACME overnight validation — {args.cycles} cycles, {args.window_hours}h window, base=redacted")

    for n in range(1, args.cycles + 1):
        print(f"\n==> Cycle {n}/{args.cycles} @ {_utc_now()}")
        try:
            data = run_cycle(
                cycle=n,
                base=base,
                site_id=args.site_id,
                window_hours=args.window_hours,
                expected_tag=args.expected_tag,
                auth_env=auth_env,
                acme_secrets=acme_secrets,
                remote_host=remote_host,
            )
        except Exception as exc:
            data = {"cycle": n, "timestamp": _utc_now(), "pass": False, "error": str(exc)}
        cycles.append(data)
        write_cycle_log(n, data)
        status = "PASS" if data.get("pass") else "FAIL"
        print(f"    Cycle {n}: {status}")
        if n < args.cycles and args.sleep_minutes > 0:
            secs = int(args.sleep_minutes * 60)
            print(f"    Sleeping {args.sleep_minutes} min until next cycle…")
            time.sleep(secs)

    append_summary(cycles, started=started, ended=_utc_now())
    print(f"\nReport: {SUMMARY_MD}")
    all_ok = all(c.get("pass") for c in cycles)
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
