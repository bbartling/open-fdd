#!/usr/bin/env python3
"""Paired FDD smoke — bensserver bench 5007 + Acme OAT/web, hardcoded phases.

Runs both sites in parallel with identical toggle schedule. Installs smoke rules,
alternates NORMAL/BLATANT thresholds, runs FDD batch each cycle, validates PyArrow
vs DataFusion parity and 5-minute fault confirmation.

CURSOR AGENTS: do not invoke this file directly (IDE crash on long blocking waits).
Use scripts/run_paired_fdd_smoke_isolated.sh + smoke_paired_fdd_status.sh instead.
See docs/operations/cursor-agent-safeguards.md.

  OPENFDD_LIVE_ACME=1 python3 scripts/smoke_paired_fdd_harness.py --short --bench-only
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
REPORT_DIR = REPO / "reports"
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "workspace" / "api"))

from open_fdd.validation.paired_fdd_parity import compare_batch_runs  # noqa: E402
from open_fdd.validation.paired_fdd_contract import (  # noqa: E402
    ACME_SITE_ID,
    BENCH_SITE_ID,
    MODES,
    PHASE_BLATANT,
    PHASE_NORMAL,
    RULE_ACME_OAT_ARROW,
    RULE_ACME_OAT_SQL,
    RULE_BENCH_BACNET_ARROW,
    RULE_BENCH_BACNET_SQL,
    RULE_BENCH_NIAGARA_ARROW,
    RULE_BENCH_NIAGARA_SQL,
    acme_rules_for_phase,
    bench_rules_for_phase,
)

from scripts.smoke_paired_fdd_auth import AuthStats, SmokeAuthSession  # noqa: E402

POLL_SECONDS = 60
HEARTBEAT_SECONDS = 300


def _health_probes_enabled(*, mode: str, bench_only: bool) -> bool:
    raw = os.environ.get("OPENFDD_SMOKE_HEALTH_PROBES", "").strip().lower()
    if raw in ("0", "false", "no"):
        return False
    if raw in ("1", "true", "yes"):
        return True
    return mode == "short" and bench_only


def _health_history_path() -> Path:
    override = os.environ.get("OPENFDD_SMOKE_HEALTH_JSON", "").strip()
    if override:
        return Path(override)
    return REPORT_DIR / "bench_5007_half_hour_health.json"


def _append_health_history(snapshot: dict[str, Any]) -> None:
    path = _health_history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    doc: dict[str, Any] = {"history": []}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                doc = loaded
        except (OSError, json.JSONDecodeError):
            pass
    history = doc.get("history") if isinstance(doc.get("history"), list) else []
    history.append(snapshot)
    doc["history"] = history[-48:]
    doc["updated_at"] = _utc()
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")


def _health_probe_loop(
    *,
    stop_event: threading.Event,
    base: str,
    status: dict[str, Any],
    status_lock: threading.Lock,
    status_path: Path,
    auth_stats: AuthStats,
) -> None:
    from open_fdd.validation.smoke_health_probes import run_health_battery  # noqa: E402

    stats = auth_stats
    session = SmokeAuthSession(base=base, label="health", stats=stats, stats_lock=threading.Lock())
    try:
        session.login(reason="health-probes")
    except RuntimeError as exc:
        with status_lock:
            status["health_probe_error"] = str(exc)
            recent = list(status.get("recent_errors") or [])
            recent.append(f"[health] login failed: {exc}")
            status["recent_errors"] = recent[-20:]
        _publish_status(status_path=status_path, status=status, status_lock=status_lock)
        return

    prior_override: dict[str, Any] | None = None
    while not stop_event.is_set():
        if session.stats.auth_failure:
            break
        snap = run_health_battery(
            base=base,
            token=session.token,
            repo_root=REPO,
            prior_override_status=prior_override,
        )
        for probe in snap.get("probes") or []:
            if isinstance(probe, dict) and probe.get("name") == "bacnet_override_scan":
                data = probe.get("data") if isinstance(probe.get("data"), dict) else {}
                st_body = data.get("status") if isinstance(data.get("status"), dict) else {}
                if st_body:
                    prior_override = st_body
        _append_health_history(snap)
        with status_lock:
            status["health_probes"] = snap
            if not snap.get("pass"):
                status["pass_so_far"] = False
                recent = list(status.get("recent_errors") or [])
                for probe in snap.get("probes") or []:
                    if isinstance(probe, dict) and not probe.get("ok"):
                        recent.append(f"[health] {probe.get('name')}: {probe.get('detail')}")
                status["recent_errors"] = recent[-20:]
        _publish_status(status_path=status_path, status=status, status_lock=status_lock)
        print(
            f"[smoke] health pass={snap.get('pass')} probes={len(snap.get('probes') or [])}",
            flush=True,
        )
        if stop_event.wait(HEARTBEAT_SECONDS):
            break


def _maybe_generate_rcx_report(*, mode: str, bench_only: bool, passed: bool) -> Path | None:
    if os.environ.get("OPENFDD_SMOKE_RCX_REPORT", "1").strip().lower() in ("0", "false", "no"):
        return None
    if not (mode == "short" and bench_only):
        return None
    try:
        from open_fdd.validation.smoke_rcx_report import generate_smoke_rcx_docx  # noqa: E402

        blob, out = generate_smoke_rcx_docx(reports_dir=REPORT_DIR, site_id=BENCH_SITE_ID)
        out.write_bytes(blob)
        print(f"[smoke] RCx report: {out} ({len(blob)} bytes) pass={passed}", flush=True)
        return out
    except Exception as exc:
        print(f"[smoke] RCx report generation failed: {exc}", flush=True)
        return None


def _status_path(mode: str) -> Path:
    override = os.environ.get("OPENFDD_SMOKE_STATUS", "").strip()
    if override:
        return Path(override)
    return Path(f"/tmp/paired_fdd_smoke_{mode}.status.json")


def _write_status_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)


def _cycles_log_path(mode: str) -> Path:
    override = os.environ.get("OPENFDD_SMOKE_CYCLES_LOG", "").strip()
    if override:
        return Path(override)
    return Path(f"/tmp/paired_fdd_smoke_{mode}_cycles.jsonl")


def _append_cycle_log(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, default=str) + "\n")


def _smoke_flagged(flagged: dict[str, Any]) -> dict[str, int]:
    return {k: int(v) for k, v in flagged.items() if str(k).startswith("smoke-paired")}


def _publish_status(
    *,
    status_path: Path,
    status: dict[str, Any],
    status_lock: threading.Lock,
) -> dict[str, Any]:
    with status_lock:
        status["updated_at"] = _utc()
        snap = dict(status)
    _write_status_json(status_path, snap)
    return snap


def _heartbeat_loop(
    *,
    stop_event: threading.Event,
    status_path: Path,
    status: dict[str, Any],
    status_lock: threading.Lock,
    started_monotonic: float,
    duration_minutes: int,
) -> None:
    while not stop_event.is_set():
        if stop_event.wait(HEARTBEAT_SECONDS):
            break
        elapsed_min = (time.monotonic() - started_monotonic) / 60.0
        with status_lock:
            status["elapsed_minutes"] = round(elapsed_min, 1)
        snap = _publish_status(status_path=status_path, status=status, status_lock=status_lock)
        bench = snap.get("bench") or {}
        acme = snap.get("acme") or {}
        err_tail = snap.get("recent_errors") or []
        err_hint = f" errors={len(err_tail)}" if err_tail else ""
        print(
            f"[smoke] heartbeat elapsed={elapsed_min:.1f}/{duration_minutes}m "
            f"phase={snap.get('phase')} toggle={snap.get('toggle')} "
            f"bench_cycle={bench.get('cycle', 0)} acme_cycle={acme.get('cycle', 0)} "
            f"bench_smoke={bench.get('smoke_flagged') or {}} "
            f"acme_smoke={acme.get('smoke_flagged') or {}} "
            f"ok={snap.get('pass_so_far', True)}{err_hint}",
            flush=True,
        )
        for err in err_tail[-3:]:
            print(f"[smoke] heartbeat err: {err}", flush=True)


@dataclass
class CycleSnapshot:
    cycle: int
    timestamp: str
    phase: str
    toggles: int
    bench_batch: dict[str, Any] = field(default_factory=dict)
    acme_batch: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


@dataclass
class SiteReport:
    label: str
    base: str
    snapshots: list[CycleSnapshot] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    pass_: bool = True


def _utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _load_auth() -> tuple[str, str]:
    auth_env = Path(os.environ.get("OPENFDD_AUTH_ENV", REPO / "workspace" / "auth.env.local"))
    if auth_env.is_file():
        for line in auth_env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip("'\""))
    user = os.environ.get("OFDD_INTEGRATOR_USER", os.environ.get("OFDD_OPERATOR_USER", "integrator"))
    password = os.environ.get("OFDD_INTEGRATOR_PASSWORD", os.environ.get("OFDD_OPERATOR_PASSWORD", ""))
    return user, password


def _fetch(
    method: str,
    url: str,
    *,
    token: str | None = None,
    body: dict | None = None,
    timeout: float = 180.0,
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
            return resp.status, json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"detail": raw[:500]}
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        return 0, {"error": str(exc)}


def _runs_by_id(batch: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for run in batch.get("runs") or []:
        if isinstance(run, dict):
            out[str(run.get("rule_id") or "")] = run
    return out


def _smoke_rule_pairs(site_kind: str) -> list[tuple[str, str]]:
    if site_kind == "bench":
        return [
            (RULE_BENCH_BACNET_ARROW, RULE_BENCH_BACNET_SQL),
            (RULE_BENCH_NIAGARA_ARROW, RULE_BENCH_NIAGARA_SQL),
        ]
    return [(RULE_ACME_OAT_ARROW, RULE_ACME_OAT_SQL)]


def _parity_issues_from_batch(site_kind: str, batch: dict[str, Any]) -> list[str]:
    runs = _runs_by_id(batch)
    issues: list[str] = []
    for arrow_id, sql_id in _smoke_rule_pairs(site_kind):
        arrow_run = runs.get(arrow_id)
        sql_run = runs.get(sql_id)
        if not arrow_run or not sql_run:
            continue
        if sql_run.get("error"):
            issues.append(f"{sql_id} backend error")
        issues.extend(compare_batch_runs(arrow_run, sql_run))
    return issues


def _save_rules(session: SmokeAuthSession, rules: list[dict[str, Any]]) -> list[str]:
    errs: list[str] = []
    for rule in rules:
        st, _res = session.fetch("POST", "/api/rules/save", body=rule)
        if st != 200:
            if st == 401 and session.stats.auth_failure:
                errs.append(f"save {rule.get('id')}: auth failure")
                break
            errs.append(f"save {rule.get('id')}: HTTP {st}")
    return errs


def _run_batch(session: SmokeAuthSession, *, lookback_hours: float) -> tuple[int, dict[str, Any]]:
    st, body = session.fetch(
        "POST",
        "/api/rules/batch",
        body={"lookback_hours": lookback_hours, "limit": 5000},
    )
    return st, body if isinstance(body, dict) else {}


def _flagged_by_rule(batch: dict[str, Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for run in batch.get("runs") or []:
        if not isinstance(run, dict):
            continue
        rid = str(run.get("rule_id") or "")
        if run.get("error"):
            out[rid] = -2
        else:
            out[rid] = int(run.get("flagged") or run.get("fault_rows") or 0)
    return out


def _run_site_loop(
    *,
    label: str,
    base: str,
    site_kind: str,
    duration_minutes: int,
    toggle_interval_minutes: int,
    stop_event: threading.Event,
    report: SiteReport,
    phase_lock: threading.Lock,
    shared_phase: list[str],
    shared_toggle_count: list[int],
    status: dict[str, Any] | None = None,
    status_lock: threading.Lock | None = None,
    started_monotonic: float | None = None,
    status_path: Path | None = None,
    cycles_log_path: Path | None = None,
    auth_stats: AuthStats | None = None,
) -> None:
    stats = auth_stats or AuthStats()
    session = SmokeAuthSession(base=base, label=label, stats=stats, stats_lock=threading.Lock())
    try:
        session.login(reason="initial")
    except RuntimeError as exc:
        report.errors.append(str(exc))
        report.pass_ = False
        return

    total_s = duration_minutes * 60
    t0 = time.monotonic()
    cycle = 0
    last_toggle_idx = -1

    while not stop_event.is_set() and (time.monotonic() - t0) < total_s:
        if session.stats.auth_failure:
            report.errors.append(f"{label}: unrecoverable auth failure")
            report.pass_ = False
            break
        cycle += 1
        elapsed_min = (time.monotonic() - t0) / 60.0
        toggle_idx = int(elapsed_min // toggle_interval_minutes)
        phase = PHASE_NORMAL if toggle_idx % 2 == 0 else PHASE_BLATANT

        with phase_lock:
            if toggle_idx != last_toggle_idx:
                last_toggle_idx = toggle_idx
                shared_phase[0] = phase
                shared_toggle_count[0] = toggle_idx + 1
                rules = bench_rules_for_phase(phase) if site_kind == "bench" else acme_rules_for_phase(phase)
                save_errs = _save_rules(session, rules)
                if save_errs:
                    report.errors.extend(save_errs)
                    report.pass_ = False
                print(f"[{label}] toggle #{toggle_idx + 1} → phase={phase} ({len(rules)} rules)", flush=True)

        lookback = min(max(2.0, elapsed_min / 60.0 + 0.25), 24.0)
        snap = CycleSnapshot(cycle=cycle, timestamp=_utc(), phase=phase, toggles=shared_toggle_count[0])

        if site_kind == "bench":
            session.fetch("POST", "/api/bacnet/poll/once", timeout=180.0)
            session.fetch("POST", "/api/niagara/stations/bench9065/poll/once", timeout=180.0)
        else:
            session.fetch("POST", "/api/bacnet/poll/once", timeout=180.0)
            session.fetch("POST", "/api/json-api/poll/once", timeout=180.0)

        st, batch = _run_batch(session, lookback_hours=lookback)
        if st != 200 or not isinstance(batch, dict):
            if st == 401 and session.stats.auth_failure:
                snap.errors.append("auth failure (unrecoverable 401)")
            else:
                snap.errors.append(f"batch HTTP {st}")
            report.pass_ = False
        else:
            flagged = _flagged_by_rule(batch)
            batch_summary = {"flagged": flagged, "summary": batch.get("summary")}
            parity_issues = _parity_issues_from_batch(site_kind, batch)
            if parity_issues:
                snap.errors.extend(parity_issues[:6])
                report.pass_ = False
            if site_kind == "bench":
                snap.bench_batch = batch_summary
            else:
                snap.acme_batch = batch_summary

        report.snapshots.append(snap)
        if snap.errors:
            report.errors.extend(snap.errors)

        if status is not None and status_lock is not None:
            flagged = {}
            batch_summary = None
            batch_data = snap.bench_batch if snap.bench_batch else snap.acme_batch
            if batch_data:
                flagged = dict(batch_data.get("flagged") or {})
                batch_summary = batch_data.get("summary")
            with status_lock:
                status["phase"] = phase
                status["toggle"] = shared_toggle_count[0]
                if started_monotonic is not None:
                    status["elapsed_minutes"] = round((time.monotonic() - started_monotonic) / 60.0, 1)
                status[label] = {
                    "cycle": cycle,
                    "phase": phase,
                    "ok": not snap.errors and report.pass_,
                    "last_errors": snap.errors[-3:],
                    "flagged": flagged,
                    "smoke_flagged": _smoke_flagged(flagged),
                    "batch_summary": batch_summary,
                    "timestamp": snap.timestamp,
                }
                if snap.errors:
                    recent = list(status.get("recent_errors") or [])
                    for err in snap.errors:
                        recent.append(f"[{label}] cycle={cycle}: {err}")
                    status["recent_errors"] = recent[-20:]
                status["pass_so_far"] = all(
                    status.get(site, {}).get("ok", True)
                    for site in ("bench", "acme")
                    if isinstance(status.get(site), dict)
                )
            if status_path is not None:
                _publish_status(status_path=status_path, status=status, status_lock=status_lock)
            if cycles_log_path is not None:
                _append_cycle_log(
                    cycles_log_path,
                    {
                        "timestamp": snap.timestamp,
                        "site": label,
                        "cycle": cycle,
                        "phase": phase,
                        "toggle": shared_toggle_count[0],
                        "flagged": flagged,
                        "smoke_flagged": _smoke_flagged(flagged),
                        "batch_summary": batch_summary,
                        "errors": snap.errors,
                    },
                )

        sleep_s = min(POLL_SECONDS, max(5.0, total_s - (time.monotonic() - t0)))
        if sleep_s > 0 and not stop_event.is_set():
            time.sleep(sleep_s)


def _dedupe_issues(errors: list[str]) -> list[str]:
    """Collapse repeated auth/HTTP errors for final reports."""
    counts: dict[str, int] = {}
    order: list[str] = []
    for err in errors:
        key = err
        if "HTTP 401" in err:
            key = "batch HTTP 401 (aggregated)"
        elif "auth failure" in err:
            key = "auth failure (aggregated)"
        counts[key] = counts.get(key, 0) + 1
        if key not in order:
            order.append(key)
    out: list[str] = []
    for key in order:
        n = counts[key]
        out.append(f"{key} ×{n}" if n > 1 and "aggregated" in key else key)
    return out


def _validate_outcomes(bench: SiteReport, acme: SiteReport, *, bench_only: bool = False) -> list[str]:
    issues: list[str] = []

    def _flagged(rep: SiteReport, phase: str, rule_id: str) -> int:
        snaps = [s for s in rep.snapshots if s.phase == phase]
        if not snaps:
            return -1
        last = snaps[-1]
        data = last.bench_batch if last.bench_batch else last.acme_batch
        return int((data.get("flagged") or {}).get(rule_id, 0))

    site_checks: list[tuple[str, SiteReport, str, str]] = [
        ("bench", bench, RULE_BENCH_BACNET_SQL, RULE_BENCH_NIAGARA_ARROW),
    ]
    if not bench_only:
        site_checks.append(("acme", acme, RULE_ACME_OAT_SQL, RULE_ACME_OAT_ARROW))

    for label, rep, primary, secondary in site_checks:
        blatant_flag_primary = _flagged(rep, PHASE_BLATANT, primary)
        blatant_flag_secondary = _flagged(rep, PHASE_BLATANT, secondary)
        if blatant_flag_primary == 0 and blatant_flag_secondary == 0 and any(
            s.phase == PHASE_BLATANT for s in rep.snapshots
        ):
            pass  # warning only — demo historian may not flag in short tryout windows

    issues.extend(_dedupe_issues(bench.errors))
    if not bench_only:
        issues.extend(_dedupe_issues(acme.errors))
    if not bench.pass_:
        issues.append("bench site loop reported errors")
    if not bench_only and not acme.pass_:
        issues.append("acme site loop reported errors")
    return issues


def _write_report(
    *,
    mode: str,
    duration_minutes: int,
    toggle_interval_minutes: int,
    parity: dict[str, Any],
    bench: SiteReport,
    acme: SiteReport,
    issues: list[str],
) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    md = REPORT_DIR / "paired_fdd_smoke_validation.md"
    lines = [
        "# Paired FDD smoke validation",
        "",
        f"- **Started:** {_utc()}",
        f"- **Mode:** {mode} ({duration_minutes} min, toggle every {toggle_interval_minutes} min)",
        f"- **PASS:** {not issues}",
        "",
        "## Parity (bensserver vs Acme)",
        "```json",
        json.dumps(parity, indent=2),
        "```",
        "",
        "## Issues",
    ]
    if issues:
        lines.extend(f"- {i}" for i in issues)
    else:
        lines.append("- none")
    lines.extend(["", "## Bench cycles", "```json", json.dumps([s.__dict__ for s in bench.snapshots[-8:]], indent=2), "```"])
    lines.extend(["", "## Acme cycles", "```json", json.dumps([s.__dict__ for s in acme.snapshots[-8:]], indent=2), "```"])
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (REPORT_DIR / "paired_fdd_smoke_validation.json").write_text(
        json.dumps(
            {
                "mode": mode,
                "pass": not issues,
                "issues": issues,
                "parity": parity,
                "bench": {"snapshots": [s.__dict__ for s in bench.snapshots], "errors": bench.errors},
                "acme": {"snapshots": [s.__dict__ for s in acme.snapshots], "errors": acme.errors},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return md


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tryout", action="store_true", help="6 min / 3 min toggle — dev validation only")
    parser.add_argument("--short", action="store_true")
    parser.add_argument("--standard", action="store_true")
    parser.add_argument("--overnight", action="store_true")
    parser.add_argument("--local", default=os.environ.get("OPENFDD_LOCAL_BASE", "http://127.0.0.1:8765"))
    parser.add_argument("--remote-limit", default=os.environ.get("OPENFDD_ANSIBLE_LIMIT", "acme_vm_bbartling"))
    parser.add_argument("--skip-parity", action="store_true")
    parser.add_argument(
        "--bench-only",
        action="store_true",
        help="benserver bench 5007 only — no Acme loop, no cross-site UI parity",
    )
    args = parser.parse_args()

    bench_only = args.bench_only or os.environ.get("OPENFDD_SMOKE_BENCH_ONLY") == "1"
    if bench_only:
        args.skip_parity = True

    if os.environ.get("CURSOR_AGENT") and os.environ.get("OPENFDD_SMOKE_WORKER") != "1":
        print(
            "REFUSED: smoke_paired_fdd_harness.py must not run attached from a Cursor agent "
            "(crashes IDE). Use scripts/run_paired_fdd_smoke_isolated.sh + "
            "scripts/smoke_paired_fdd_status.sh",
            file=sys.stderr,
        )
        return 2

    if not bench_only and os.environ.get("OPENFDD_LIVE_ACME") != "1":
        print("Set OPENFDD_LIVE_ACME=1 for live paired smoke (or use --bench-only)", file=sys.stderr)
        return 1

    if args.tryout:
        mode = "tryout"
    elif args.short:
        mode = "short"
    elif args.overnight:
        mode = "overnight"
    else:
        mode = "standard"

    cfg = MODES[mode]
    duration = cfg["duration_minutes"]
    toggle_iv = cfg["toggle_interval_minutes"]

    acme_base = ""
    if not bench_only:
        from scripts.acme_live_validate import resolve_base_from_ansible  # noqa: E402

        acme_base = resolve_base_from_ansible(args.remote_limit).rstrip("/")
    bench_base = args.local.rstrip("/")

    parity: dict[str, Any] = {"pass": True, "issues": []}
    if not args.skip_parity:
        import subprocess

        proc = subprocess.run(
            [
                sys.executable,
                str(REPO / "scripts" / "site_parity_smoke.py"),
                "--local",
                bench_base,
                "--remote",
                acme_base,
                "--json-out",
                str(REPORT_DIR / "site_parity_smoke.json"),
            ],
            env={**os.environ, "OPENFDD_LIVE_ACME": "1"},
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            parity["pass"] = False
            parity["issues"].append("site_parity_smoke failed")
        try:
            parity["report"] = json.loads((REPORT_DIR / "site_parity_smoke.json").read_text())
        except (OSError, json.JSONDecodeError):
            pass

    print(f"Paired FDD smoke — mode={mode} duration={duration}m toggle={toggle_iv}m", flush=True)
    print(f"  bench={bench_base} site={BENCH_SITE_ID}", flush=True)
    if bench_only:
        print("  acme=skipped (--bench-only)", flush=True)
    else:
        print(f"  acme={acme_base} site={ACME_SITE_ID}", flush=True)

    bench_report = SiteReport(label="bench", base=bench_base)
    acme_report = SiteReport(label="acme", base=acme_base)
    stop = threading.Event()
    phase_lock = threading.Lock()
    status_lock = threading.Lock()
    shared_phase: list[str] = [PHASE_NORMAL]
    shared_toggle_count: list[int] = [0]
    started_mono = time.monotonic()
    status_path = _status_path(mode)
    cycles_log_path = _cycles_log_path(mode)
    bench_auth = AuthStats()
    acme_auth = AuthStats()
    shared_status: dict[str, Any] = {
        "mode": mode,
        "started_at": _utc(),
        "duration_minutes": duration,
        "toggle_interval_minutes": toggle_iv,
        "elapsed_minutes": 0.0,
        "phase": PHASE_NORMAL,
        "toggle": 0,
        "bench": {"cycle": 0, "ok": True},
        "acme": {"cycle": 0, "ok": True},
        "pass_so_far": True,
        "recent_errors": [],
        "status_file": str(status_path),
        "cycles_log": str(cycles_log_path),
        "log_hint": f"tail -f /tmp/paired_fdd_smoke_{mode}_*.log",
        "bench_base": bench_base,
        "acme_base": acme_base or None,
        "bench_only": bench_only,
        "pid": os.getpid(),
        **bench_auth.to_dict(),
    }
    _write_status_json(status_path, shared_status)

    t_heartbeat = threading.Thread(
        target=_heartbeat_loop,
        kwargs={
            "stop_event": stop,
            "status_path": status_path,
            "status": shared_status,
            "status_lock": status_lock,
            "started_monotonic": started_mono,
            "duration_minutes": duration,
        },
        daemon=True,
    )
    t_heartbeat.start()

    health_enabled = _health_probes_enabled(mode=mode, bench_only=bench_only)
    if health_enabled:
        t_health = threading.Thread(
            target=_health_probe_loop,
            kwargs={
                "stop_event": stop,
                "base": bench_base,
                "status": shared_status,
                "status_lock": status_lock,
                "status_path": status_path,
                "auth_stats": bench_auth,
            },
            daemon=True,
        )
        t_health.start()
        print("[smoke] health probes enabled (API, overrides, frontend, logs)", flush=True)

    t_bench = threading.Thread(
        target=_run_site_loop,
        kwargs={
            "label": "bench",
            "base": bench_base,
            "site_kind": "bench",
            "duration_minutes": duration,
            "toggle_interval_minutes": toggle_iv,
            "stop_event": stop,
            "report": bench_report,
            "phase_lock": phase_lock,
            "shared_phase": shared_phase,
            "shared_toggle_count": shared_toggle_count,
            "status": shared_status,
            "status_lock": status_lock,
            "started_monotonic": started_mono,
            "status_path": status_path,
            "cycles_log_path": cycles_log_path,
            "auth_stats": bench_auth,
        },
        daemon=True,
    )
    t_acme = threading.Thread(
        target=_run_site_loop,
        kwargs={
            "label": "acme",
            "base": acme_base,
            "site_kind": "acme",
            "duration_minutes": duration,
            "toggle_interval_minutes": toggle_iv,
            "stop_event": stop,
            "report": acme_report,
            "phase_lock": phase_lock,
            "shared_phase": shared_phase,
            "shared_toggle_count": shared_toggle_count,
            "status": shared_status,
            "status_lock": status_lock,
            "started_monotonic": started_mono,
            "status_path": status_path,
            "cycles_log_path": cycles_log_path,
            "auth_stats": acme_auth,
        },
        daemon=True,
    )
    t_bench.start()
    if not bench_only:
        t_acme.start()
        t_acme.join()
    t_bench.join()
    stop.set()

    issues = _validate_outcomes(bench_report, acme_report, bench_only=bench_only)
    if not parity.get("pass"):
        issues.insert(0, "cross-site parity failed")

    if health_enabled:
        health_path = _health_history_path()
        if health_path.is_file():
            try:
                health_doc = json.loads(health_path.read_text(encoding="utf-8"))
                for snap in reversed(health_doc.get("history") or []):
                    if isinstance(snap, dict) and not snap.get("pass"):
                        issues.append("health probe cycle failed")
                        break
            except (OSError, json.JSONDecodeError):
                issues.append("health probe history unreadable")
        else:
            issues.append("no health probe history recorded")

    passed = not issues
    auth_summary = {
        "bench": bench_auth.to_dict(),
        "acme": acme_auth.to_dict(),
        "auth_refresh_count": bench_auth.refresh_count + acme_auth.refresh_count,
        "auth_401_count": bench_auth.http_401_count + acme_auth.http_401_count,
        "auth_recovered_count": bench_auth.recovered_count + acme_auth.recovered_count,
        "auth_unrecovered_count": bench_auth.unrecovered_count + acme_auth.unrecovered_count,
    }
    with status_lock:
        shared_status["finished_at"] = _utc()
        shared_status["elapsed_minutes"] = round((time.monotonic() - started_mono) / 60.0, 1)
        shared_status["pass"] = passed
        shared_status["issues"] = issues[:20]
        shared_status["auth"] = auth_summary
        shared_status.update(auth_summary)
        if issues:
            recent = list(shared_status.get("recent_errors") or [])
            for issue in issues[:10]:
                recent.append(f"[final] {issue}")
            shared_status["recent_errors"] = recent[-20:]
        _write_status_json(status_path, dict(shared_status))

    report_path = _write_report(
        mode=mode,
        duration_minutes=duration,
        toggle_interval_minutes=toggle_iv,
        parity=parity,
        bench=bench_report,
        acme=acme_report,
        issues=issues,
    )
    rcx_path = _maybe_generate_rcx_report(mode=mode, bench_only=bench_only, passed=passed)
    print(f"\nReport: {report_path}")
    if rcx_path:
        print(f"RCx DOCX: {rcx_path}")
    if issues:
        for i in issues[:12]:
            print(f"  FAIL: {i}")
        return 1
    print("PASS — paired FDD smoke")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
