#!/usr/bin/env python3
"""Disposable authenticated ZAP Automation Framework runner (Wave U U5).

Soft-OPEN until a real disposable scan produces High=0 evidence.
Never logs or embeds JWT / Authorization header values in argv-style
output or verdict artifacts.

Modes:
  --selftest
      Validate af_plan.yaml hygiene + verdict schema; write BLOCKED verdict; exit 2.
  OPENFDD_ZAP_AF_EXECUTE=1 + ZAP_TARGET_ORIGIN + ZAP_AUTH_HEADER_VALUE
      If ZAP (docker image or zap.sh) is available: run AF passive (+ optional
      active when OPENFDD_ZAP_AF_ACTIVE=1), assert High=0, write verdict.
      If ZAP missing: hygiene selftest + BLOCKED verdict; exit 2.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

try:
    import yaml
except ImportError as e:  # pragma: no cover
    raise SystemExit("ERROR: PyYAML required (pip/uv install pyyaml)") from e

ROOT = Path(__file__).resolve().parents[3]
PLAN_PATH = Path(__file__).resolve().parent / "af_plan.yaml"
DEFAULT_VERDICT = ROOT / "reports" / "security" / "zap_af_verdict.json"
DEFAULT_ZAP_IMAGE = os.environ.get(
    "OPENFDD_ZAP_IMAGE", "ghcr.io/zaproxy/zaproxy:stable"
)

# Hardcoded JWT / Bearer material must never appear in the committed plan.
_HARDCODED_BEARER = re.compile(
    r"Bearer\s+(?!\$\{)[A-Za-z0-9\-_\.=]+", re.IGNORECASE
)
_JWT_BLOB = re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}")
_REDACT_BEARER = re.compile(r"(Bearer\s+)(\S+)", re.IGNORECASE)


def redact(text: str) -> str:
    """Strip bearer token material from any string before logging/artifacts."""
    text = _REDACT_BEARER.sub(r"\1<redacted>", text)
    return _JWT_BLOB.sub("<redacted-jwt>", text)


def validate_af_plan(path: Path) -> list[str]:
    """Return human-readable hygiene errors (empty ⇒ OK)."""
    errors: list[str] = []
    if not path.is_file():
        return [f"missing plan: {path}"]
    raw = path.read_text(encoding="utf-8")
    if _HARDCODED_BEARER.search(raw):
        errors.append("plan contains hardcoded Bearer token (use env injection)")
    if _JWT_BLOB.search(raw):
        errors.append("plan contains JWT-like blob (never commit tokens)")
    if "${ZAP_AUTH_HEADER_VALUE}" not in raw:
        errors.append("plan must reference ${ZAP_AUTH_HEADER_VALUE} for Authorization")
    if "${ZAP_TARGET_ORIGIN}" not in raw:
        errors.append("plan must reference ${ZAP_TARGET_ORIGIN}")

    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        return errors + [f"invalid YAML: {e}"]

    if not isinstance(data, dict):
        return errors + ["plan root must be a mapping"]

    contexts = (data.get("env") or {}).get("contexts") or []
    if not isinstance(contexts, list) or not contexts:
        errors.append("env.contexts must be a nonempty list")
    else:
        for i, ctx in enumerate(contexts):
            if not isinstance(ctx, dict):
                errors.append(f"contexts[{i}] must be a mapping")
                continue
            urls = ctx.get("urls") or []
            if not isinstance(urls, list) or len(urls) == 0:
                errors.append(f"contexts[{i}].urls must be nonempty (site gate)")
            params = ((ctx.get("sessionManagement") or {}).get("parameters")) or {}
            auth = params.get("Authorization") if isinstance(params, dict) else None
            if auth != "${ZAP_AUTH_HEADER_VALUE}":
                errors.append(
                    f"contexts[{i}] Authorization must be exactly "
                    "'${ZAP_AUTH_HEADER_VALUE}'"
                )

    jobs = data.get("jobs") or []
    if not isinstance(jobs, list) or not jobs:
        errors.append("jobs must be a nonempty list")
    else:
        types = {j.get("type") for j in jobs if isinstance(j, dict)}
        for required in ("openapi", "spider", "passiveScan-wait", "report"):
            if required not in types:
                errors.append(f"jobs missing required type: {required}")
        for j in jobs:
            if isinstance(j, dict) and j.get("failOnError") is False:
                errors.append("failOnError=false must not swallow AF errors")

    return errors


def detect_zap() -> tuple[str | None, str]:
    """Return (mode, detail) where mode is 'zap.sh' | 'docker' | None."""
    zap_sh = shutil.which("zap.sh")
    if zap_sh:
        return "zap.sh", zap_sh
    if shutil.which("docker"):
        try:
            subprocess.run(
                ["docker", "info"],
                check=True,
                capture_output=True,
                timeout=30,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
            return None, "docker present but daemon unavailable"
        # Prefer a local/pullable zaproxy image; do not pull here unless execute.
        return "docker", DEFAULT_ZAP_IMAGE
    return None, "neither zap.sh nor docker available"


def summarize_zap_json(data: dict[str, Any]) -> dict[str, Any]:
    sites = data.get("site") or data.get("sites") or []
    if isinstance(sites, dict):
        sites = [sites]
    if not isinstance(sites, list):
        sites = []
    alerts: list[dict[str, Any]] = []
    site_names: list[str] = []
    malformed_sites = 0
    for site in sites:
        if not isinstance(site, dict):
            malformed_sites += 1
            continue
        name = str(site.get("@name") or site.get("name") or "").strip()
        if not name and not (site.get("alerts") or []):
            malformed_sites += 1
        if name:
            site_names.append(name)
        for a in site.get("alerts") or []:
            if isinstance(a, dict):
                alerts.append(a)
    for a in data.get("alerts") or []:
        if isinstance(a, dict):
            alerts.append(a)

    by_risk = {"High": 0, "Medium": 0, "Low": 0, "Informational": 0, "other": 0}
    high_names: list[str] = []
    medium_names: list[str] = []
    url_blob_parts: list[str] = []
    for a in alerts:
        risk = str(a.get("riskdesc") or a.get("risk") or "").split(" ", 1)[0]
        code = str(a.get("riskcode") or "")
        if risk not in by_risk:
            risk = {"3": "High", "2": "Medium", "1": "Low", "0": "Informational"}.get(
                code, "other"
            )
        by_risk[risk] = by_risk.get(risk, 0) + 1
        label = str(a.get("name") or a.get("alert") or "unknown")
        if risk == "High":
            high_names.append(label)
        if risk == "Medium":
            medium_names.append(label)
        for key in ("url", "uri", "instance", "param"):
            val = a.get(key)
            if isinstance(val, str):
                url_blob_parts.append(val)
            elif isinstance(val, list):
                for item in val:
                    if isinstance(item, dict):
                        url_blob_parts.append(str(item.get("uri") or item.get("url") or ""))
                    else:
                        url_blob_parts.append(str(item))
    for site in sites:
        if isinstance(site, dict):
            for key in ("@name", "name", "host"):
                if site.get(key):
                    url_blob_parts.append(str(site.get(key)))
            for u in site.get("urls") or []:
                url_blob_parts.append(str(u))
    url_blob = "\n".join(url_blob_parts).lower()
    auth_me_hit = "/api/auth/me" in url_blob
    return {
        "site_count": len(sites),
        "malformed_sites": malformed_sites,
        "site_names": site_names,
        "alert_count": len(alerts),
        "by_risk": by_risk,
        "high_alert_names": sorted(set(high_names)),
        "medium_alert_names": sorted(set(medium_names)),
        "auth_me_hit": auth_me_hit,
    }


def validate_report_sites(data: dict[str, Any], target_origin: str) -> list[str]:
    """Require nonempty site objects belonging to the configured target."""
    sites = data.get("site") or data.get("sites") or []
    if isinstance(sites, dict):
        sites = [sites]
    if not isinstance(sites, list) or not sites:
        return ["report has no site objects"]

    target = urlsplit(target_origin.rstrip("/"))
    target_key = (target.scheme.lower(), target.netloc.lower())
    errors: list[str] = []
    for index, site in enumerate(sites):
        if not isinstance(site, dict) or not site:
            errors.append(f"site[{index}] must be a nonempty object")
            continue
        raw_name = str(site.get("@name") or site.get("name") or "").strip()
        parsed = urlsplit(raw_name)
        if not raw_name or not parsed.scheme or not parsed.netloc:
            errors.append(f"site[{index}] missing valid target name")
        elif (parsed.scheme.lower(), parsed.netloc.lower()) != target_key:
            errors.append(
                f"site[{index}] target does not match configured target origin"
            )
    return errors


def verdict_schema_ok(verdict: dict[str, Any]) -> list[str]:
    """Validate verdict object shape; also reject embedded secrets."""
    errors: list[str] = []
    required = (
        "suite",
        "status",
        "mode",
        "plan_hygiene_ok",
        "high_alerts",
        "medium_alerts",
        "zap_available",
        "active_scan",
        "notes",
    )
    for k in required:
        if k not in verdict:
            errors.append(f"verdict missing key: {k}")
    if verdict.get("status") not in ("PASS", "FAIL", "BLOCKED", "ERROR"):
        errors.append(f"invalid status: {verdict.get('status')!r}")
    blob = json.dumps(verdict)
    if _JWT_BLOB.search(blob) or _HARDCODED_BEARER.search(blob):
        errors.append("verdict must not embed JWT / Bearer tokens")
    return errors


def write_verdict(path: Path, verdict: dict[str, Any]) -> None:
    errs = verdict_schema_ok(verdict)
    if errs:
        raise SystemExit("ERROR: refusing to write invalid verdict: " + "; ".join(errs))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(verdict, indent=2) + "\n", encoding="utf-8")


def build_verdict(**kwargs: Any) -> dict[str, Any]:
    base = {
        "suite": "zap_af_authenticated_v1",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "plan": str(PLAN_PATH.relative_to(ROOT)),
        "artifact_policy": "no_jwt_in_verdict_or_ci_logs",
    }
    base.update(kwargs)
    # Defense in depth: redact any accidental secret fields.
    return json.loads(redact(json.dumps(base)))


def materialize_plan(
    *,
    origin: str,
    report_dir: str,
    active: bool,
    dest: Path,
) -> None:
    """Write AF plan with origin/reportDir expanded; auth stays env-referenced."""
    raw = PLAN_PATH.read_text(encoding="utf-8")
    # Expand only non-secret placeholders for ZAP hosts that skip env expansion.
    rendered = raw.replace("${ZAP_TARGET_ORIGIN}", origin.rstrip("/"))
    rendered = rendered.replace("${ZAP_REPORT_DIR}", report_dir)
    data = yaml.safe_load(rendered)
    if active:
        jobs = list(data.get("jobs") or [])
        # Insert activeScan before the report job.
        active_job = {
            "type": "activeScan",
            "parameters": {
                "context": "openfdd-disposable",
                "policy": "Default Policy",
                "maxRuleDurationInMins": 5,
                "maxScanDurationInMins": 30,
            },
        }
        out_jobs: list[Any] = []
        inserted = False
        for j in jobs:
            if isinstance(j, dict) and j.get("type") == "report" and not inserted:
                out_jobs.append(active_job)
                inserted = True
            out_jobs.append(j)
        if not inserted:
            out_jobs.append(active_job)
        data["jobs"] = out_jobs
    # Ensure Authorization still env-only after round-trip.
    for ctx in (data.get("env") or {}).get("contexts") or []:
        if not isinstance(ctx, dict):
            continue
        sm = ctx.setdefault("sessionManagement", {})
        params = sm.setdefault("parameters", {})
        params["Authorization"] = "${ZAP_AUTH_HEADER_VALUE}"
    dest.write_text(
        yaml.safe_dump(data, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
    # Re-check only secret hygiene on rendered text (origin is expanded).
    text = dest.read_text(encoding="utf-8")
    if _HARDCODED_BEARER.search(text) or _JWT_BLOB.search(text):
        raise SystemExit("ERROR: rendered plan leaked auth material")
    if "${ZAP_AUTH_HEADER_VALUE}" not in text:
        raise SystemExit("ERROR: rendered plan lost auth env injection")


def _run_zap_docker(
    *,
    image: str,
    work_dir: Path,
    auth_header: str,
    origin: str,
) -> int:
    network = os.environ.get("ZAP_DOCKER_NETWORK", "").strip()
    cmd = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{work_dir}:/zap/wrk:rw",
        "-e",
        "ZAP_AUTH_HEADER_VALUE",  # value from caller env — not argv
        "-e",
        f"ZAP_TARGET_ORIGIN={origin}",
        "-e",
        "ZAP_REPORT_DIR=/zap/wrk",
        "-u",
        "0:0",
    ]
    # Host-reachable disposable targets vs shared docker network (mutually exclusive).
    if "127.0.0.1" in origin or "localhost" in origin:
        cmd.append("--network=host")
    elif network:
        cmd.extend(["--network", network])
    cmd.extend([image, "zap.sh", "-cmd", "-autorun", "/zap/wrk/af_plan.yaml"])
    env = os.environ.copy()
    env["ZAP_AUTH_HEADER_VALUE"] = auth_header
    # Do not print cmd with secrets; auth is env-pass only.
    print(
        "Running ZAP AF via docker "
        f"(image={image}, network={network or 'default/host'}, active check deferred to plan)",
        flush=True,
    )
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
    (work_dir / "zap_af.stdout.log").write_text(redact(proc.stdout or ""), encoding="utf-8")
    (work_dir / "zap_af.stderr.log").write_text(redact(proc.stderr or ""), encoding="utf-8")
    return int(proc.returncode)


def _run_zap_sh(*, zap_sh: str, work_dir: Path, auth_header: str, origin: str) -> int:
    env = os.environ.copy()
    env["ZAP_AUTH_HEADER_VALUE"] = auth_header
    env["ZAP_TARGET_ORIGIN"] = origin
    env["ZAP_REPORT_DIR"] = str(work_dir)
    plan = work_dir / "af_plan.yaml"
    print(f"Running ZAP AF via zap.sh ({zap_sh})", flush=True)
    proc = subprocess.run(
        [zap_sh, "-cmd", "-autorun", str(plan)],
        env=env,
        capture_output=True,
        text=True,
        cwd=str(work_dir),
    )
    (work_dir / "zap_af.stdout.log").write_text(redact(proc.stdout or ""), encoding="utf-8")
    (work_dir / "zap_af.stderr.log").write_text(redact(proc.stderr or ""), encoding="utf-8")
    return int(proc.returncode)


def run_selftest(verdict_path: Path) -> int:
    """Prove plan hygiene + verdict schema; never claim PASS without a scan."""
    hygiene = validate_af_plan(PLAN_PATH)
    mode, detail = detect_zap()
    plan_ok = not hygiene
    sample = build_verdict(
        status="BLOCKED",
        mode="selftest",
        plan_hygiene_ok=plan_ok,
        plan_hygiene_errors=hygiene,
        high_alerts=0,
        medium_alerts=0,
        site_count=0,
        zap_available=mode is not None,
        zap_detection=detail if mode is None else mode,
        active_scan=False,
        execute_requested=False,
        notes=(
            "Selftest only: plan hygiene + verdict schema. "
            "Not a scan PASS. Soft-OPEN until OPENFDD_ZAP_AF_EXECUTE=1 "
            "against a disposable target with ZAP produces High=0."
        ),
    )
    schema_errs = verdict_schema_ok(sample)
    if hygiene or schema_errs:
        sample["status"] = "ERROR"
        sample["notes"] = redact(
            "Selftest failed: "
            + "; ".join(hygiene + schema_errs)
        )
        write_verdict(verdict_path, sample)
        print(json.dumps(sample, indent=2))
        print("ERROR: selftest hygiene/schema failed", file=sys.stderr)
        return 1
    write_verdict(verdict_path, sample)
    print(json.dumps(sample, indent=2))
    print(
        f"BLOCKED: selftest OK (hygiene+schema); Soft-OPEN → {verdict_path}",
        file=sys.stderr,
    )
    return 2


def run_execute(verdict_path: Path) -> int:
    os.environ.setdefault("ZAP_AF_RUN_STARTED_EPOCH", str(time.time()))
    hygiene = validate_af_plan(PLAN_PATH)
    if hygiene:
        v = build_verdict(
            status="ERROR",
            mode="execute",
            plan_hygiene_ok=False,
            plan_hygiene_errors=hygiene,
            high_alerts=0,
            medium_alerts=0,
            site_count=0,
            zap_available=False,
            active_scan=False,
            execute_requested=True,
            notes="af_plan.yaml hygiene failed: " + "; ".join(hygiene),
        )
        write_verdict(verdict_path, v)
        print(json.dumps(v, indent=2))
        return 1

    origin = (os.environ.get("ZAP_TARGET_ORIGIN") or "").strip()
    auth = (os.environ.get("ZAP_AUTH_HEADER_VALUE") or "").strip()
    if not origin or not auth:
        v = build_verdict(
            status="BLOCKED",
            mode="execute",
            plan_hygiene_ok=True,
            high_alerts=0,
            medium_alerts=0,
            site_count=0,
            zap_available=False,
            active_scan=False,
            execute_requested=True,
            notes=(
                "BLOCKED: set ZAP_TARGET_ORIGIN and ZAP_AUTH_HEADER_VALUE in env "
                "(never argv). Disposable target only."
            ),
        )
        write_verdict(verdict_path, v)
        print(json.dumps(v, indent=2))
        return 2

    # Never echo auth. Confirm it looks like a header value without printing it.
    if not auth.lower().startswith("bearer "):
        print(
            "WARN: ZAP_AUTH_HEADER_VALUE does not start with 'Bearer ' "
            "(continuing; value not logged)",
            file=sys.stderr,
        )

    mode, detail = detect_zap()
    active = os.environ.get("OPENFDD_ZAP_AF_ACTIVE", "").strip() in ("1", "true", "yes")

    if mode is None:
        v = build_verdict(
            status="BLOCKED",
            mode="execute",
            plan_hygiene_ok=True,
            high_alerts=0,
            medium_alerts=0,
            site_count=0,
            zap_available=False,
            zap_detection=detail,
            active_scan=active,
            execute_requested=True,
            target_origin_configured=True,
            auth_header_configured=True,
            notes=(
                "BLOCKED: ZAP not installed/available. Plan hygiene OK. "
                "Not a fake High=0 PASS. Install zap.sh or docker+zaproxy image."
            ),
        )
        write_verdict(verdict_path, v)
        print(json.dumps(v, indent=2))
        return 2

    work_root = Path(
        os.environ.get("ZAP_AF_WORK_DIR")
        or tempfile.mkdtemp(prefix="openfdd_zap_af_")
    )
    work_root.mkdir(parents=True, exist_ok=True)
    # Docker mounts work_root at /zap/wrk
    report_dir_in_plan = "/zap/wrk" if mode == "docker" else str(work_root)
    plan_dest = work_root / "af_plan.yaml"
    materialize_plan(
        origin=origin,
        report_dir=report_dir_in_plan,
        active=active,
        dest=plan_dest,
    )

    scan_started_ns = time.time_ns()
    if mode == "docker":
        # Ensure image exists (pull if missing) — low-RAM hosts may already have it.
        try:
            inspect = subprocess.run(
                ["docker", "image", "inspect", detail],
                capture_output=True,
                timeout=60,
            )
            if inspect.returncode != 0:
                print(f"Pulling ZAP image {detail} …", flush=True)
                subprocess.run(["docker", "pull", detail], check=True, timeout=600)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            v = build_verdict(
                status="BLOCKED",
                mode="execute",
                plan_hygiene_ok=True,
                high_alerts=0,
                medium_alerts=0,
                site_count=0,
                zap_available=False,
                zap_detection=f"docker image unavailable: {redact(str(e))}",
                active_scan=active,
                execute_requested=True,
                notes="BLOCKED: could not pull/inspect ZAP image",
            )
            write_verdict(verdict_path, v)
            print(json.dumps(v, indent=2))
            return 2
        rc = _run_zap_docker(
            image=detail, work_dir=work_root, auth_header=auth, origin=origin
        )
    else:
        rc = _run_zap_sh(
            zap_sh=detail, work_dir=work_root, auth_header=auth, origin=origin
        )

    report_path = work_root / "zap-af-report.json"
    # ZAP traditional-json may append .json or write variants.
    if not report_path.is_file():
        candidates = sorted(work_root.glob("zap-af-report*.json"))
        report_path = candidates[0] if candidates else report_path

    if rc != 0:
        v = build_verdict(
            status="FAIL",
            mode="execute",
            plan_hygiene_ok=True,
            high_alerts=0,
            medium_alerts=0,
            site_count=0,
            zap_available=True,
            zap_detection=mode,
            zap_exit_code=rc,
            active_scan=active,
            execute_requested=True,
            notes=f"FAIL: ZAP scanner exited nonzero (rc={rc})",
        )
        write_verdict(verdict_path, v)
        print(json.dumps(v, indent=2))
        return 1

    if not report_path.is_file() or report_path.stat().st_size == 0:
        v = build_verdict(
            status="BLOCKED",
            mode="execute",
            plan_hygiene_ok=True,
            high_alerts=0,
            medium_alerts=0,
            site_count=0,
            zap_available=True,
            zap_detection=mode,
            zap_exit_code=rc,
            active_scan=active,
            execute_requested=True,
            work_dir=str(work_root),
            notes=(
                "BLOCKED: ZAP finished without usable JSON report "
                f"(rc={rc}). Not treating as High=0 PASS."
            ),
        )
        write_verdict(verdict_path, v)
        print(json.dumps(v, indent=2))
        return 2

    if report_path.stat().st_mtime_ns < scan_started_ns:
        v = build_verdict(
            status="ERROR",
            mode="execute",
            plan_hygiene_ok=True,
            high_alerts=0,
            medium_alerts=0,
            site_count=0,
            zap_available=True,
            zap_detection=mode,
            zap_exit_code=rc,
            active_scan=active,
            execute_requested=True,
            notes="ERROR: ZAP report predates this scan run; stale evidence rejected",
        )
        write_verdict(verdict_path, v)
        print(json.dumps(v, indent=2))
        return 1

    try:
        data = json.loads(report_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        v = build_verdict(
            status="ERROR",
            mode="execute",
            plan_hygiene_ok=True,
            high_alerts=0,
            medium_alerts=0,
            site_count=0,
            zap_available=True,
            active_scan=active,
            execute_requested=True,
            notes=f"ERROR: malformed ZAP JSON: {e}",
        )
        write_verdict(verdict_path, v)
        print(json.dumps(v, indent=2))
        return 1

    if not isinstance(data, dict):
        v = build_verdict(
            status="ERROR",
            mode="execute",
            plan_hygiene_ok=True,
            high_alerts=0,
            medium_alerts=0,
            site_count=0,
            zap_available=True,
            active_scan=active,
            execute_requested=True,
            notes="ERROR: ZAP report root must be object",
        )
        write_verdict(verdict_path, v)
        print(json.dumps(v, indent=2))
        return 1

    site_errors = validate_report_sites(data, origin)
    if site_errors:
        v = build_verdict(
            status="ERROR",
            mode="execute",
            plan_hygiene_ok=True,
            high_alerts=0,
            medium_alerts=0,
            site_count=0,
            zap_available=True,
            zap_detection=mode,
            zap_exit_code=rc,
            active_scan=active,
            execute_requested=True,
            notes="ERROR: invalid ZAP report sites: " + "; ".join(site_errors),
        )
        write_verdict(verdict_path, v)
        print(json.dumps(v, indent=2))
        return 1

    summary = summarize_zap_json(data)
    high = int(summary["by_risk"].get("High", 0))
    med = int(summary["by_risk"].get("Medium", 0))
    sites = int(summary["site_count"])
    malformed_sites = summary.get("malformed_sites", 0)

    # Reject reused/stale reports or wrong-target crawls.
    report_mtime = report_path.stat().st_mtime
    run_started = float(os.environ.get("ZAP_AF_RUN_STARTED_EPOCH", "0") or "0")
    if run_started <= 0:
        # Infer: if report mtime is far older than process start, treat as stale.
        run_started = time.time() - 2.0
    stale = report_mtime + 1.0 < run_started
    site_names = summary.get("site_names") or []
    wrong_target = bool(site_names) and not any(
        origin.rstrip("/") in str(name).rstrip("/")
        or str(name).rstrip("/") in origin.rstrip("/")
        for name in site_names
    )

    # Archive report under reports/security without secrets (ZAP JSON usually
    # has URLs, not Authorization headers — still redact defensively).
    archive = verdict_path.parent / "zap_af_report.json"
    archive.write_text(redact(report_path.read_text(encoding="utf-8")), encoding="utf-8")

    if rc != 0:
        status = "FAIL"
        notes = f"FAIL: ZAP scanner exit rc={rc} (report present is not a PASS)"
        exit_code = 1
    elif stale:
        status = "FAIL"
        notes = "FAIL: ZAP report mtime predates this run (stale/reused artifact)"
        exit_code = 1
    elif wrong_target:
        status = "FAIL"
        notes = f"FAIL: report site names {site_names!r} do not match target {origin}"
        exit_code = 1
    elif malformed_sites or sites == 0:
        status = "FAIL" if malformed_sites else "BLOCKED"
        notes = (
            "FAIL: malformed empty site objects — no crawl/auth coverage"
            if malformed_sites
            else "BLOCKED: empty site[] — no crawl/auth coverage evidence"
        )
        exit_code = 1 if malformed_sites else 2
    elif high > 0:
        status = "FAIL"
        notes = f"FAIL: High={high} ({', '.join(summary['high_alert_names'][:8])})"
        exit_code = 1
    elif med > 0:
        status = "FAIL"
        notes = f"FAIL: Medium={med} without dispositions"
        exit_code = 1
    elif not summary.get("auth_me_hit"):
        status = "FAIL"
        notes = (
            "FAIL: no /api/auth/me evidence in ZAP report "
            "(authenticated AF coverage required)"
        )
        exit_code = 1
    else:
        status = "PASS"
        notes = (
            f"PASS: disposable AF High=0 Medium=0 site_count={sites} "
            f"auth_me_hit=true active_scan={active} zap_rc={rc}"
        )
        exit_code = 0

    v = build_verdict(
        status=status,
        mode="execute",
        plan_hygiene_ok=True,
        high_alerts=high,
        medium_alerts=med,
        site_count=sites,
        alert_count=summary["alert_count"],
        high_alert_names=summary["high_alert_names"],
        zap_available=True,
        zap_detection=mode,
        zap_exit_code=rc,
        active_scan=active,
        execute_requested=True,
        target_origin_configured=True,
        auth_header_configured=True,
        auth_me_hit=bool(summary.get("auth_me_hit")),
        report_archive=str(archive.relative_to(ROOT)) if archive.is_relative_to(ROOT) else str(archive),
        work_dir=str(work_root),
        notes=notes,
    )
    write_verdict(verdict_path, v)
    print(json.dumps(v, indent=2))
    print(f"{status}: → {verdict_path}", file=sys.stderr)
    return exit_code


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--selftest",
        action="store_true",
        help="plan hygiene + verdict schema; exit BLOCKED (2), never PASS",
    )
    p.add_argument(
        "--out",
        default=str(DEFAULT_VERDICT),
        help=f"verdict JSON path (default: {DEFAULT_VERDICT})",
    )
    args = p.parse_args(argv)
    out = Path(args.out)

    if args.selftest:
        return run_selftest(out)

    execute = os.environ.get("OPENFDD_ZAP_AF_EXECUTE", "").strip() in (
        "1",
        "true",
        "yes",
    )
    if not execute:
        print(
            "BLOCKED: set OPENFDD_ZAP_AF_EXECUTE=1 for a real disposable scan, "
            "or pass --selftest for hygiene-only BLOCKED evidence.",
            file=sys.stderr,
        )
        v = build_verdict(
            status="BLOCKED",
            mode="idle",
            plan_hygiene_ok=not validate_af_plan(PLAN_PATH),
            plan_hygiene_errors=validate_af_plan(PLAN_PATH),
            high_alerts=0,
            medium_alerts=0,
            site_count=0,
            zap_available=detect_zap()[0] is not None,
            active_scan=False,
            execute_requested=False,
            notes=(
                "OPENFDD_ZAP_AF_EXECUTE not set — refusing to invent a scan PASS. "
                "Use --selftest or EXECUTE=1 with ZAP_TARGET_ORIGIN + "
                "ZAP_AUTH_HEADER_VALUE."
            ),
        )
        write_verdict(out, v)
        print(json.dumps(v, indent=2))
        return 2

    return run_execute(out)


if __name__ == "__main__":
    sys.exit(main())
