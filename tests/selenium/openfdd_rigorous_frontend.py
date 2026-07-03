#!/usr/bin/env python3
"""
Rigorous frontend + agent bootstrap + PCAP validation for Open-FDD bench.

Phases:
  1. Agent bootstrap (API) — commission OT model, FDD SQL, poll drivers
  2. TLS bootstrap (optional) — caddy-tls self-signed certs + MCP docs clarity
  3. Selenium UI — routes, SQL buttons, Host stats, plot render
  4. PCAP capture (optional) — BACnet/Modbus wire traffic during poll window
  5. PCAP analyze via existing bash scripts

No git push — pull GHCR containers + iterate test scripts only.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from openfdd_agent_bootstrap import run_bootstrap
from openfdd_test_lib import Check, RunResult, bench_root, log, utc_now
from openfdd_tls_bootstrap import run_tls_bootstrap
from openfdd_ui_selenium import run_ui_validation


def run_pcap_phase(root: Path, out_dir: Path, duration_sec: int) -> tuple[RunResult, Path | None]:
    result = RunResult(artifact_dir=str(out_dir / "pcap"), started_at=utc_now(), meta={"phase": "pcap"})
    pcap_dir = out_dir / "pcap"
    env = os.environ.copy()
    env["OPENFDD_PCAP_DURATION_SEC"] = str(duration_sec)
    env["OPENFDD_PCAP_DIR"] = str(pcap_dir)

    capture_sh = root / "scripts/openfdd_ot_pcap_capture.sh"
    analyze_sh = root / "scripts/openfdd_ot_pcap_analyze.sh"
    minute_sh = root / "scripts/openfdd_pcap_minute_validate.sh"

    if not capture_sh.exists():
        result.add(Check("pcap-capture", "SKIP", "openfdd_ot_pcap_capture.sh missing"))
        result.finalize()
        return result, None

    log(f"pcap capture {duration_sec}s → {pcap_dir}")
    try:
        subprocess.run([str(capture_sh)], cwd=str(root), env=env, check=False, capture_output=True, text=True, timeout=duration_sec + 120)
    except subprocess.TimeoutExpired:
        result.add(Check("pcap-capture", "FAIL", "capture script timed out"))
        result.finalize()
        return result, None

    pcap_file = pcap_dir / "openfdd_ot.pcap"
    if not pcap_file.exists():
        latest = root / "workspace/logs/pcap_latest.dir"
        if latest.exists():
            alt = Path(latest.read_text().strip()) / "openfdd_ot.pcap"
            if alt.exists():
                pcap_file = alt
                pcap_dir = pcap_file.parent

    if pcap_file.exists() and pcap_file.stat().st_size > 24:
        result.add(Check("pcap-capture", "PASS", f"{pcap_file.name} size={pcap_file.stat().st_size}"))
    else:
        result.add(Check("pcap-capture", "FAIL", f"missing or empty pcap at {pcap_file}"))
        result.finalize()
        return result, pcap_dir if pcap_file.parent.exists() else None

    if analyze_sh.exists():
        proc = subprocess.run([str(analyze_sh), str(pcap_dir)], cwd=str(root), capture_output=True, text=True)
        (pcap_dir / "analyze_stdout.txt").write_text(proc.stdout + proc.stderr, encoding="utf-8")
        bacnet_ok = "47808" in proc.stdout or "bacnet" in proc.stdout.lower()
        modbus_ok = "1502" in proc.stdout or "modbus" in proc.stdout.lower()
        if bacnet_ok:
            result.add(Check("pcap-bacnet", "PASS", "BACnet UDP 47808 traffic seen in pcap analysis"))
        else:
            result.add(Check("pcap-bacnet", "FAIL", "no BACnet 47808 in pcap — commission poll may be down", product_bug=True))
        if modbus_ok:
            result.add(Check("pcap-modbus", "PASS", "Modbus TCP 1502 traffic seen in pcap analysis"))
        else:
            result.add(Check("pcap-modbus", "FAIL", "no Modbus 1502 in pcap — trigger /api/modbus/read during capture", product_bug=True))

    if minute_sh.exists():
        proc = subprocess.run([str(minute_sh), str(pcap_dir)], cwd=str(root), capture_output=True, text=True)
        (pcap_dir / "minute_validate_stdout.txt").write_text(proc.stdout + proc.stderr, encoding="utf-8")
        minute_json = pcap_dir / "minute_validate.json"
        if minute_json.exists():
            data = json.loads(minute_json.read_text())
            if data.get("passed"):
                result.add(Check("pcap-minute-buckets", "PASS", "minute bucket validation passed"))
            else:
                result.add(Check("pcap-minute-buckets", "FAIL", "minute buckets below threshold", product_bug=True))

    result.finalize()
    result.write(pcap_dir)
    return result, pcap_dir


def merge_results(out_dir: Path, parts: list[RunResult]) -> RunResult:
    merged = RunResult(artifact_dir=str(out_dir), started_at=parts[0].started_at if parts else utc_now())
    merged.meta = {"phases": [p.meta.get("phase") for p in parts]}
    for part in parts:
        for c in part.checks:
            merged.add(c)
    merged.finalize()
    merged.write(out_dir)

    product_bugs = [c for c in merged.checks if c.status == "FAIL" and c.product_bug]
    (out_dir / "product_bugs.txt").write_text(
        "\n".join(f"{c.name}: {c.detail}" for c in product_bugs) or "none",
        encoding="utf-8",
    )
    return merged


def trigger_ot_traffic(root: Path, duration_sec: int) -> None:
    """Drive Modbus/BACnet reads during PCAP window."""
    env = os.environ.copy()
    env["OPENFDD_PCAP_OT_POLL_SEC"] = str(min(duration_sec, 120))
    poll_sh = root / "scripts/openfdd_bacnet_poll_daemon.sh"
    if poll_sh.exists():
        subprocess.run([str(poll_sh), "start"], cwd=str(root), capture_output=True)
    bench_lib = root / "scripts/openfdd_bench_lib.sh"
    auth_lib = root / "scripts/openfdd_auth_lib.sh"
    if not bench_lib.exists():
        return
    script = f"""
set -euo pipefail
source "{auth_lib}"
source "{bench_lib}"
BASE="${{OPENFDD_API_BASE:-http://127.0.0.1:8080}}"
COM="${{OPENFDD_COMMISSION_BASE:-http://127.0.0.1:9091}}"
AUTH="{root}/workspace/auth.env.local"
TOKEN=$(openfdd_auth_login_token "$BASE" "$AUTH" integrator)
end=$((SECONDS + {min(duration_sec, 90)}))
while [[ $SECONDS -lt $end ]]; do
  curl -fsS -H "Authorization: Bearer $TOKEN" -X POST "$BASE/api/modbus/read" \\
    -H 'Content-Type: application/json' \\
    -d '{{"register":30001,"function":"input_register","scale":0.1}}' >/dev/null || true
  curl -fsS -H "Authorization: Bearer $TOKEN" -X POST "$COM/api/bacnet/whois" \\
    -H 'Content-Type: application/json' \\
    -d '{{"low_limit":0,"high_limit":4194303}}' >/dev/null || true
  curl -fsS -H "Authorization: Bearer $TOKEN" -X POST "$COM/api/bacnet/read" \\
    -H 'Content-Type: application/json' \\
    -d '{{"point_id":"bacnet:5007:analog-input:1173"}}' >/dev/null || true
  sleep 10
done
"""
    subprocess.Popen(["bash", "-c", script], cwd=str(root), env=env)


def main() -> int:
    parser = argparse.ArgumentParser(description="Open-FDD rigorous frontend validation")
    parser.add_argument("--out", default="")
    parser.add_argument("--skip-pcap", action="store_true")
    parser.add_argument("--skip-selenium", action="store_true")
    parser.add_argument("--skip-bootstrap", action="store_true")
    parser.add_argument("--skip-tls", action="store_true")
    parser.add_argument("--tls-docs-only", action="store_true", help="MCP README clarity only (no caddy-tls)")
    parser.add_argument("--pcap-sec", type=int, default=int(os.environ.get("OPENFDD_FRONTEND_PCAP_SEC", "90")))
    args = parser.parse_args()

    root = bench_root()
    out = Path(args.out) if args.out else root / f"workspace/logs/frontend_rigorous_{utc_now().replace(':', '').replace('-', '')}"
    out.mkdir(parents=True, exist_ok=True)
    log(f"frontend rigorous → {out}")

    parts: list[RunResult] = []

    if not args.skip_bootstrap:
        boot_dir = out / "bootstrap"
        parts.append(run_bootstrap(boot_dir))

    skip_tls = args.skip_tls or os.environ.get("OPENFDD_FRONTEND_SKIP_TLS", "0") == "1"
    tls_docs_only = args.tls_docs_only or os.environ.get("OPENFDD_TLS_DOCS_ONLY", "0") == "1"
    if not skip_tls:
        tls_dir = out / "tls_bootstrap"
        parts.append(run_tls_bootstrap(tls_dir, skip_caddy=tls_docs_only))

    pcap_dir = None
    if not args.skip_pcap:
        trigger_ot_traffic(root, args.pcap_sec)
        pcap_result, pcap_dir = run_pcap_phase(root, out, args.pcap_sec)
        parts.append(pcap_result)

    if not args.skip_selenium:
        ui_dir = out / "selenium"
        os.environ["OPENFDD_FRONTEND_ARTIFACT_DIR"] = str(ui_dir)
        parts.append(run_ui_validation(ui_dir))

    merged = merge_results(out, parts)
    log(f"FINAL pass={merged.pass_count} fail={merged.fail_count} skip={merged.skip_count} ok={merged.ok}")
    log(f"artifacts: {out}")
    log(f"agent SQL: {out / 'bootstrap' / 'agent_fdd_sql.sql'}")
    if pcap_dir:
        log(f"pcap: {pcap_dir / 'openfdd_ot.pcap'}")
    return 0 if merged.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
