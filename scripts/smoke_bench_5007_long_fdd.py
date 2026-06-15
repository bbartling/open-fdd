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
from open_fdd.validation.bench_stack_preflight import validate_stack_preflight
from open_fdd.validation.bench_5007_long_fdd import (  # noqa: E402
    BACNET_SOURCE,
    NIAGARA_SOURCE,
    FddRunMetrics,
    SmokeConfig,
    SmokeEvent,
    ValidationReport,
    align_semantic_points,
    finalize_live_report,
    aggregate_latest_runs,
    run_synthetic_validation,
    validate_model_preflight,
    write_report_artifacts,
)

PROGRESS_INTERVAL_S = 300


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


def _metrics_from_response(source: str, backend: str, semantic: str, res: dict[str, Any]) -> FddRunMetrics:
    m = res.get("metrics") or {}
    return FddRunMetrics(
        source=str(m.get("source") or source),
        point_id=str(m.get("point_id") or ""),
        equipment_id=str(m.get("equipment_id") or ""),
        semantic_key=str(m.get("semantic_key") or semantic),
        backend=backend,
        row_count=int(m.get("row_count") or 0),
        raw_true_count=int(m.get("raw_true_count") or 0),
        confirmed_true_count=int(m.get("confirmed_true_count") or 0),
        value_avg=m.get("value_avg"),
        value_min=m.get("value_min"),
        value_max=m.get("value_max"),
        raw_mask_fingerprint=str(m.get("raw_mask_fingerprint") or ""),
        confirmed_mask_fingerprint=str(m.get("confirmed_mask_fingerprint") or ""),
        first_sample_time=str(m.get("first_sample_time") or ""),
        last_sample_time=str(m.get("last_sample_time") or ""),
        first_raw_fault_time=str(m.get("first_raw_fault_time") or ""),
        first_confirmed_fault_time=str(m.get("first_confirmed_fault_time") or ""),
        first_raw_fault_after_change=str(m.get("first_raw_fault_after_change") or ""),
        first_confirmed_fault_after_change=str(m.get("first_confirmed_fault_after_change") or ""),
        confirmation_delay_seconds=m.get("confirmation_delay_seconds"),
        observed_confirmation_delay_seconds=m.get("observed_confirmation_delay_seconds"),
        expected_confirmation_delay_seconds=float(m.get("expected_confirmation_delay_seconds") or 0.0),
        average_sample_interval_s=m.get("average_sample_interval_s"),
        max_sample_gap_s=m.get("max_sample_gap_s"),
        threshold_change_wall_time=str(m.get("threshold_change_wall_time") or ""),
        threshold_change_sample_time=str(m.get("threshold_change_sample_time") or ""),
        threshold_change_row_index=m.get("threshold_change_row_index"),
        preexisting_raw_fault=bool(m.get("preexisting_raw_fault")),
        early_confirmed_fault=bool(m.get("early_confirmed_fault")),
        execution_evidence=m.get("execution_evidence") or {},
        errors=list(m.get("errors") or []),
        historian_origin=str(res.get("origin") or ""),
        time_filter_relaxed=bool(res.get("time_filter_relaxed")),
        evaluate_freshness=dict(res.get("freshness") or {}),
    )


def _evaluate(
    base: str,
    token: str,
    cfg: SmokeConfig,
    *,
    source: str,
    backend: str,
    threshold: float,
    phase: str,
    lookback_hours: float | None = None,
    run_started_at: str | None = None,
    threshold_change_at: str | None = None,
) -> tuple[int, dict[str, Any]]:
    body: dict[str, Any] = {
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
        "freshness_window_minutes": cfg.freshness_window_minutes,
        "strict_live_freshness": cfg.strict_live_freshness,
        "allow_historical_replay": cfg.allow_historical_replay,
    }
    if lookback_hours is not None:
        body["lookback_hours"] = lookback_hours
    if run_started_at:
        body["run_started_at"] = run_started_at
    if threshold_change_at:
        body["threshold_change_at"] = threshold_change_at
    return _fetch("POST", f"{base}/api/bench/long-fdd/evaluate", token=token, body=body, timeout=180.0)


def _progress_line(
    *,
    elapsed_min: float,
    remaining_min: float,
    bacnet_rows: int,
    niagara_rows: int,
    raw_seen: bool,
    confirmed_seen: bool,
    verdict_state: str,
    datafusion_ok: bool,
) -> str:
    return (
        f"[progress] elapsed={elapsed_min:.0f}m remaining={remaining_min:.0f}m "
        f"bacnet_rows={bacnet_rows} niagara_rows={niagara_rows} "
        f"pyarrow=ok datafusion={'ok' if datafusion_ok else 'skip'} "
        f"raw_fault={'yes' if raw_seen else 'no'} confirmed_fault={'yes' if confirmed_seen else 'no'} "
        f"state={verdict_state}"
    )


def run_live(cfg: SmokeConfig) -> ValidationReport:
    base = cfg.base_url.rstrip("/")
    report = ValidationReport(
        config=cfg,
        started_at=datetime.now(timezone.utc).isoformat(),
        environment={"mode": "live", "base_url": base, "datafusion_installed": datafusion_available()},
    )
    report.events.append(
        SmokeEvent(
            timestamp=report.started_at,
            event_type="preflight",
            message=f"live smoke starting ({cfg.duration_minutes} min)",
        )
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
        report.environment["health"] = {
            k: health.get(k) for k in ("ok", "openfdd_version", "git_sha") if isinstance(health, dict)
        }

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

    status, rules_body = _fetch("GET", f"{base}/api/rules/saved", token=token)
    rules = rules_body.get("rules") if isinstance(rules_body, dict) else []

    def _api_fetch(method: str, path: str, body: dict | None = None) -> tuple[int, Any]:
        return _fetch(method, f"{base}{path}", token=token, body=body, timeout=120.0)

    stack = validate_stack_preflight(_api_fetch, token, model=model, rules=rules if isinstance(rules, list) else [])
    report.environment["stack_preflight"] = stack
    for w in stack.get("warnings") or []:
        if w not in report.warnings:
            report.warnings.append(w)
    if not stack.get("ok"):
        for err in stack.get("errors") or []:
            report.errors.append(f"stack preflight: {err}")
        report.verdict = "FAIL"
        report.finished_at = datetime.now(timezone.utc).isoformat()
        return report
    rules_pf = stack.get("rules") or {}
    report.events.append(
        SmokeEvent(
            timestamp=datetime.now(timezone.utc).isoformat(),
            event_type="stack_preflight",
            message=(
                f"health+s snapshot ok; {rules_pf.get('enabled_count', 0)} rules enabled, "
                f"{rules_pf.get('arrow_rules', 0)} arrow, {rules_pf.get('datafusion_sql_rules', 0)} sql"
            ),
        )
    )
    print(
        f"[preflight] stack ok — building/snapshot, {rules_pf.get('enabled_count')} FDD rules, "
        f"batch runs={next((c.get('run_count') for c in stack.get('checks') or [] if c.get('name')=='fdd_batch'), 0)}",
        flush=True,
    )

    lookback_h = max(24.0, (cfg.duration_minutes + 10) / 60.0)
    pf_status, pf_res = _evaluate(
        base,
        token,
        cfg,
        source=BACNET_SOURCE,
        backend="pyarrow",
        threshold=cfg.baseline_threshold_f,
        phase="preflight",
        lookback_hours=lookback_h,
    )
    if pf_status != 200 or not isinstance(pf_res, dict) or not pf_res.get("ok"):
        report.errors.append(
            f"preflight evaluate failed HTTP {pf_status} {_redact_payload(pf_res)} — restart bridge after pulling PR branch"
        )
        report.verdict = "FAIL"
        report.finished_at = datetime.now(timezone.utc).isoformat()
        return report

    report.events.append(
        SmokeEvent(
            timestamp=datetime.now(timezone.utc).isoformat(),
            event_type="baseline_start",
            semantic_key=cfg.primary_semantic,
            message=f"baseline threshold {cfg.baseline_threshold_f}F for {cfg.baseline_minutes} min",
        )
    )

    t0 = time.monotonic()
    baseline_s = cfg.baseline_minutes * 60
    total_s = cfg.duration_minutes * 60
    cycle = 0
    threshold_changed = False
    raw_fault_seen = False
    confirmed_fault_seen = False
    last_progress = t0
    latest_runs: dict[tuple[str, str], FddRunMetrics] = {}
    poll_status: dict[str, Any] | None = None

    backends = ("pyarrow", "datafusion_sql")
    sources = (BACNET_SOURCE, NIAGARA_SOURCE)

    lookback_h = max(24.0, (cfg.duration_minutes + 10) / 60.0)

    while (time.monotonic() - t0) < total_s:
        cycle += 1
        elapsed = time.monotonic() - t0
        phase = "baseline" if elapsed < baseline_s else "fault"
        threshold = cfg.baseline_threshold_f if phase == "baseline" else cfg.forced_threshold_f
        if phase == "fault" and not threshold_changed:
            threshold_changed = True
            report.threshold_change_at = datetime.now(timezone.utc).isoformat()
            report.events.append(
                SmokeEvent(
                    timestamp=report.threshold_change_at,
                    event_type="threshold_change",
                    semantic_key=cfg.primary_semantic,
                    message=f"forced threshold {cfg.forced_threshold_f}F ({cfg.fault_direction})",
                )
            )

        bacnet_status, bacnet_res = _fetch("POST", f"{base}/api/bacnet/poll/once", token=token, timeout=180.0)
        niagara_status, niagara_res = _fetch(
            "POST",
            f"{base}/api/niagara/stations/{cfg.niagara_station}/poll/once",
            token=token,
            timeout=180.0,
        )
        if bacnet_status != 200:
            warn = f"cycle {cycle} bacnet poll failed: HTTP {bacnet_status} {_redact_payload(bacnet_res)}"
            if warn not in report.warnings:
                report.warnings.append(warn)
            remaining_sleep = total_s - (time.monotonic() - t0)
            if remaining_sleep > 0:
                time.sleep(min(cfg.poll_seconds, remaining_sleep))
            continue
        if niagara_status != 200:
            warn = f"cycle {cycle} niagara poll failed: HTTP {niagara_status} {_redact_payload(niagara_res)}"
            if warn not in report.warnings:
                report.warnings.append(warn)
            remaining_sleep = total_s - (time.monotonic() - t0)
            if remaining_sleep > 0:
                time.sleep(min(cfg.poll_seconds, remaining_sleep))
            continue

        for source in sources:
            for backend in backends:
                if backend == "datafusion_sql" and not datafusion_available():
                    continue
                status, res = _evaluate(
                    base,
                    token,
                    cfg,
                    source=source,
                    backend=backend,
                    threshold=threshold,
                    phase=phase,
                    lookback_hours=lookback_h,
                    run_started_at=report.started_at,
                    threshold_change_at=report.threshold_change_at or None,
                )
                if status != 200 or not isinstance(res, dict) or not res.get("ok"):
                    detail = res.get("error") or _redact_payload(res)
                    fresh = res.get("freshness") or {}
                    if fresh.get("summary"):
                        detail = f"{detail} ({fresh['summary']})"
                    report.errors.append(
                        f"cycle {cycle} {source}/{backend}: HTTP {status} {detail}"
                    )
                    if cfg.strict_live_freshness and cycle == 1:
                        report.errors.append(
                            f"strict live freshness failed on cycle 1 for {source}/{backend} — "
                            "aborting early (fix historian before long run)"
                        )
                        report.finished_at = datetime.now(timezone.utc).isoformat()
                        finalize_live_report(report, poll_status=None)
                        return report
                    continue
                metrics = _metrics_from_response(source, backend, cfg.primary_semantic, res)
                latest_runs[(source, backend)] = metrics
                eng = metrics.execution_evidence.get("confirmation_engine")
                if eng == "python_loop_over_arrow_mask":
                    warn_key = f"confirmation uses python loop ({source}/{backend})"
                    if warn_key not in report.warnings:
                        report.warnings.append(warn_key)
                if metrics.first_raw_fault_after_change or metrics.first_raw_fault_time:
                    if not raw_fault_seen:
                        raw_fault_seen = True
                        ts = metrics.first_raw_fault_after_change or metrics.first_raw_fault_time
                        report.events.append(
                            SmokeEvent(
                                timestamp=ts,
                                event_type="raw_fault_first_seen",
                                source=source,
                                backend=backend,
                                message=f"first raw fault after change on {source}/{backend}",
                            )
                        )
                if metrics.first_confirmed_fault_after_change or metrics.first_confirmed_fault_time:
                    if not confirmed_fault_seen:
                        confirmed_fault_seen = True
                        ts = metrics.first_confirmed_fault_after_change or metrics.first_confirmed_fault_time
                        report.events.append(
                            SmokeEvent(
                                timestamp=ts,
                                event_type="confirmed_fault_first_seen",
                                source=source,
                                backend=backend,
                                message=f"first confirmed fault after change on {source}/{backend}",
                            )
                        )

        if time.monotonic() - last_progress >= PROGRESS_INTERVAL_S or cycle == 1:
            last_progress = time.monotonic()
            bacnet_rows = max((r.row_count for (s, _), r in latest_runs.items() if s == BACNET_SOURCE), default=0)
            niagara_rows = max((r.row_count for (s, _), r in latest_runs.items() if s == NIAGARA_SOURCE), default=0)
            remaining = max(0.0, (total_s - elapsed) / 60.0)
            line = _progress_line(
                elapsed_min=elapsed / 60.0,
                remaining_min=remaining,
                bacnet_rows=bacnet_rows,
                niagara_rows=niagara_rows,
                raw_seen=raw_fault_seen,
                confirmed_seen=confirmed_fault_seen,
                verdict_state="running",
                datafusion_ok=datafusion_available(),
            )
            print(line, flush=True)

        if cfg.overnight and cycle % max(1, int(3600 / cfg.poll_seconds)) == 0:
            report.hourly_rollups.append(
                {
                    "cycle": cycle,
                    "elapsed_minutes": round(elapsed / 60, 1),
                    "phase": phase,
                    "runs": len(latest_runs),
                }
            )

        remaining_sleep = total_s - (time.monotonic() - t0)
        if remaining_sleep > 0:
            time.sleep(min(cfg.poll_seconds, remaining_sleep))

    if not threshold_changed:
        report.errors.append("fault phase never reached — increase duration_minutes")

    # Final snapshot with full lookback for fault-phase evidence
    lookback_h = max(24.0, (cfg.duration_minutes + 10) / 60.0)
    for source in sources:
        for backend in backends:
            if backend == "datafusion_sql" and not datafusion_available():
                continue
            status, res = _evaluate(
                base,
                token,
                cfg,
                source=source,
                backend=backend,
                threshold=cfg.forced_threshold_f,
                phase="final",
                lookback_hours=lookback_h,
                run_started_at=report.started_at,
                threshold_change_at=report.threshold_change_at or None,
            )
            if status == 200 and isinstance(res, dict) and res.get("ok"):
                latest_runs[(source, backend)] = _metrics_from_response(
                    source, backend, cfg.primary_semantic, res
                )
            else:
                report.errors.append(
                    f"final {source}/{backend}: HTTP {status} {_redact_payload(res)}"
                )

    status, poll_status = _fetch("GET", f"{base}/api/bench/poll-status", token=token)
    if status != 200:
        poll_status = None

    report.matrix_runs = list(latest_runs.values())
    report.finished_at = datetime.now(timezone.utc).isoformat()
    finalize_live_report(report, poll_status=poll_status if isinstance(poll_status, dict) else None)

    bacnet_rows = max((r.row_count for r in report.matrix_runs if r.source == BACNET_SOURCE), default=0)
    niagara_rows = max((r.row_count for r in report.matrix_runs if r.source == NIAGARA_SOURCE), default=0)
    print(
        _progress_line(
            elapsed_min=cfg.duration_minutes,
            remaining_min=0,
            bacnet_rows=bacnet_rows,
            niagara_rows=niagara_rows,
            raw_seen=raw_fault_seen,
            confirmed_seen=confirmed_fault_seen,
            verdict_state=report.verdict,
            datafusion_ok=datafusion_available(),
        ),
        flush=True,
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Bench 5007 long FDD validation smoke")
    parser.add_argument("--live", action="store_true", help="Live historian polling validation (default unless --synthetic)")
    parser.add_argument("--synthetic", action="store_true", help="CI-friendly synthetic Arrow tables")
    parser.add_argument("--dry-run", action="store_true", help="Short developer run (explicit only)")
    parser.add_argument("--allow-historical-replay", action="store_true", help="Permit WARN (not FAIL) when historian returns replay data")
    parser.add_argument(
        "--strict-live-freshness",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="FAIL live runs when sample timestamps are not fresh (default: enabled)",
    )
    parser.add_argument("--freshness-window-minutes", type=float, default=5.0, help="Freshness tolerance vs wall clock")
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
    cfg.live = not args.synthetic
    cfg.allow_historical_replay = args.allow_historical_replay
    cfg.strict_live_freshness = args.strict_live_freshness
    cfg.freshness_window_minutes = args.freshness_window_minutes

    print(
        f"==> Bench 5007 long FDD smoke ({cfg.duration_minutes} min, confirmation window={cfg.confirmation_rows} rows)",
        flush=True,
    )

    if args.synthetic:
        report = run_synthetic_validation(cfg)
    else:
        report = run_live(cfg)

    paths = write_report_artifacts(report, REPO / cfg.reports_dir)
    summary = {
        "verdict": report.verdict,
        "mode": report.environment.get("mode", "synthetic" if cfg.synthetic else "live"),
        "started_at": report.started_at,
        "finished_at": report.finished_at,
        "matrix_runs": len(aggregate_latest_runs(report.matrix_runs)),
        "events": len(report.events),
        "artifacts": paths,
        "errors": report.errors,
        "warnings": report.warnings,
    }
    print(json.dumps(summary, indent=2))

    if report.verdict == "FAIL":
        print("\nLONG FDD SMOKE FAILED", file=sys.stderr)
        return 1
    print(f"\nLONG FDD SMOKE {report.verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
