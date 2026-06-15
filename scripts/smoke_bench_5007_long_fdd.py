#!/usr/bin/env python3
"""Bench 5007 long-running FDD validation — 2h default, 12h overnight, synthetic CI."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
API = REPO / "workspace" / "api"
if str(API) not in sys.path:
    sys.path.insert(0, str(API))

os.environ.setdefault("OPENFDD_REPO_ROOT", str(REPO))
os.environ.setdefault("OPENFDD_WORKSPACE_DIR", str(REPO / "workspace"))
os.environ.setdefault("OFDD_DESKTOP_DATA_DIR", str(REPO / "workspace" / "data"))

from open_fdd.arrow_runtime.datafusion_backend import datafusion_available
from open_fdd.validation.bench_5007_long_fdd import (  # noqa: E402
    BACNET_SOURCE,
    NIAGARA_SOURCE,
    SmokeConfig,
    ValidationReport,
    align_semantic_points,
    run_synthetic_validation,
    validate_model_preflight,
    write_report_artifacts,
)


def _load_auth() -> tuple[str, str]:
    auth_env = Path(os.environ.get("OPENFDD_AUTH_ENV", REPO / "workspace" / "auth.env.local"))
    if auth_env.is_file():
        for line in auth_env.read_text(encoding="utf-8").splitlines():
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
    url: str,
    *,
    token: str | None = None,
    body: dict | None = None,
    timeout: float = 120.0,
) -> tuple[int, Any]:
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
            return resp.status, json.loads(raw)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"detail": raw}
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        return 0, {"error": str(exc)}


def _redact_payload(payload: Any) -> str:
    text = json.dumps(payload) if isinstance(payload, dict) else str(payload)
    lowered = text.lower()
    for needle in ("password", "token", "bearer", "secret", "authorization"):
        if needle in lowered and "********" not in text:
            return "[redacted]"
    return text


def run_live(cfg: SmokeConfig) -> ValidationReport:
    base = cfg.base_url.rstrip("/")
    report = ValidationReport(
        config=cfg,
        started_at=datetime.now(timezone.utc).isoformat(),
        environment={"mode": "live", "base_url": base, "datafusion_installed": datafusion_available()},
    )

    user, password = _load_auth()
    status, login = _fetch("POST", f"{base}/api/auth/login", body={"username": user, "password": password})
    if status != 200 or not isinstance(login, dict) or not login.get("token"):
        report.errors.append(f"auth failed HTTP {status}")
        report.verdict = "FAIL"
        return report
    token = str(login["token"])

    status, health = _fetch("GET", f"{base}/health")
    if status != 200:
        report.errors.append(f"health HTTP {status}")
    else:
        report.environment["health"] = {k: health.get(k) for k in ("ok", "openfdd_version", "git_sha") if isinstance(health, dict)}

    status, model = _fetch("GET", f"{base}/api/model/commissioning-export", token=token)
    if status != 200 or not isinstance(model, dict):
        report.errors.append(f"commissioning export HTTP {status}")
        report.verdict = "FAIL"
        return report

    report.errors.extend(validate_model_preflight(model, cfg))
    aligned = align_semantic_points(model, cfg.site_id)
    for semantic, by_source in aligned.items():
        for pt in by_source.values():
            report.model_alignment.append(pt)

    if cfg.strict_datafusion and not datafusion_available():
        report.errors.append("DataFusion required but not installed")

    status, poll_status = _fetch("GET", f"{base}/api/bench/poll-status", token=token)
    if status == 200 and isinstance(poll_status, dict):
        report.polling_health.append(poll_status)

    t0 = time.monotonic()
    baseline_s = cfg.baseline_minutes * 60
    total_s = cfg.duration_minutes * 60
    cycle = 0
    threshold_changed = False

    backends = ("pyarrow", "datafusion_sql")
    sources = (BACNET_SOURCE, NIAGARA_SOURCE)

    while (time.monotonic() - t0) < total_s:
        cycle += 1
        elapsed = time.monotonic() - t0
        phase = "baseline" if elapsed < baseline_s else "fault"
        threshold = cfg.baseline_threshold_f if phase == "baseline" else cfg.forced_threshold_f
        if phase == "fault" and not threshold_changed:
            threshold_changed = True
            report.threshold_change_at = datetime.now(timezone.utc).isoformat()

        _fetch("POST", f"{base}/api/bacnet/poll/once", token=token, timeout=180.0)
        _fetch(
            "POST",
            f"{base}/api/niagara/stations/{cfg.niagara_station}/poll/once",
            token=token,
            timeout=180.0,
        )

        for source in sources:
            for backend in backends:
                if backend == "datafusion_sql" and not datafusion_available():
                    continue
                status, res = _fetch(
                    "POST",
                    f"{base}/api/bench/long-fdd/evaluate",
                    token=token,
                    body={
                        "site_id": cfg.site_id,
                        "source": source,
                        "semantic_key": cfg.primary_semantic,
                        "backend": backend,
                        "threshold": threshold,
                        "phase": phase,
                        "poll_interval_s": cfg.poll_seconds,
                        "confirmation_rows": cfg.confirmation_rows,
                        "confirmation_minutes": cfg.confirmation_minutes,
                        "fault_direction": cfg.fault_direction,
                    },
                )
                if status != 200 or not isinstance(res, dict) or not res.get("ok"):
                    report.errors.append(
                        f"cycle {cycle} {source}/{backend}: HTTP {status} {_redact_payload(res)}"
                    )
                    continue
                m = res.get("metrics") or {}
                from open_fdd.validation.bench_5007_long_fdd import FddRunMetrics

                metrics = FddRunMetrics(
                    source=str(m.get("source") or source),
                    point_id=str(m.get("point_id") or ""),
                    equipment_id=str(m.get("equipment_id") or ""),
                    semantic_key=cfg.primary_semantic,
                    backend=backend,
                    row_count=int(m.get("row_count") or 0),
                    raw_true_count=int(m.get("raw_true_count") or 0),
                    confirmed_true_count=int(m.get("confirmed_true_count") or 0),
                    first_raw_fault_time=str(m.get("first_raw_fault_time") or ""),
                    first_confirmed_fault_time=str(m.get("first_confirmed_fault_time") or ""),
                    confirmation_delay_seconds=m.get("confirmation_delay_seconds"),
                    execution_evidence=m.get("execution_evidence") or {},
                    errors=list(m.get("errors") or []),
                )
                report.matrix_runs.append(metrics)
                if metrics.execution_evidence.get("confirmation_engine") == "python_loop_over_arrow_mask":
                    report.warnings.append(f"confirmation uses python loop ({source}/{backend})")

        if cfg.overnight and cycle % max(1, int(3600 / cfg.poll_seconds)) == 0:
            report.hourly_rollups.append(
                {
                    "cycle": cycle,
                    "elapsed_minutes": round(elapsed / 60, 1),
                    "phase": phase,
                    "runs": len(report.matrix_runs),
                }
            )

        remaining = total_s - (time.monotonic() - t0)
        if remaining > cfg.poll_seconds:
            time.sleep(cfg.poll_seconds)

    if not threshold_changed:
        report.errors.append("fault phase never reached — increase duration_minutes")

    # Final fault-phase evaluation snapshot for timeline
    report.fault_timeline = [r for r in report.matrix_runs if r.backend and r.source]

    report.finished_at = datetime.now(timezone.utc).isoformat()
    from open_fdd.validation.bench_5007_long_fdd import _compute_verdict

    report.verdict = _compute_verdict(report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Bench 5007 long FDD validation smoke")
    parser.add_argument("--synthetic", action="store_true", help="CI-friendly synthetic Arrow tables")
    parser.add_argument("--dry-run", action="store_true", help="Short developer run (explicit only)")
    parser.add_argument("--overnight", action="store_true", help="12-hour validation (720 min)")
    parser.add_argument("--strict-datafusion", action="store_true", help="Fail if DataFusion extra missing")
    parser.add_argument("--site-id", default=None)
    parser.add_argument("--duration-minutes", type=int, default=None)
    parser.add_argument("--poll-seconds", type=int, default=None)
    parser.add_argument("--baseline-minutes", type=int, default=None)
    parser.add_argument("--confirmation-minutes", type=float, default=None)
    parser.add_argument("--confirmation-rows", type=int, default=None)
    parser.add_argument("--primary-semantic", default=None)
    parser.add_argument("--forced-threshold", type=float, default=None)
    parser.add_argument("--reports-dir", default=None)
    args = parser.parse_args()

    cfg = SmokeConfig.from_env()
    if args.site_id:
        cfg.site_id = args.site_id
    if args.poll_seconds:
        cfg.poll_seconds = args.poll_seconds
    if args.baseline_minutes:
        cfg.baseline_minutes = args.baseline_minutes
    if args.confirmation_minutes is not None:
        cfg.confirmation_minutes = args.confirmation_minutes
    if args.confirmation_rows:
        cfg.confirmation_rows = args.confirmation_rows
    if args.primary_semantic:
        cfg.primary_semantic = args.primary_semantic
    if args.forced_threshold is not None:
        cfg.forced_threshold_f = args.forced_threshold
    if args.overnight:
        cfg.overnight = True
        cfg.duration_minutes = 720
    if args.duration_minutes:
        cfg.duration_minutes = args.duration_minutes
    if args.dry_run:
        cfg.dry_run = True
        cfg.duration_minutes = min(cfg.duration_minutes, 15)
        cfg.baseline_minutes = min(cfg.baseline_minutes, 5)
    if args.strict_datafusion:
        cfg.strict_datafusion = True
    if args.reports_dir:
        cfg.reports_dir = args.reports_dir
    cfg.synthetic = args.synthetic

    if args.synthetic:
        report = run_synthetic_validation(cfg)
    else:
        report = run_live(cfg)

    paths = write_report_artifacts(report, REPO / cfg.reports_dir)
    print(json.dumps({"verdict": report.verdict, "artifacts": paths, "errors": report.errors}, indent=2))

    if report.verdict == "FAIL":
        print("\nLONG FDD SMOKE FAILED", file=sys.stderr)
        return 1
    print(f"\nLONG FDD SMOKE {report.verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
