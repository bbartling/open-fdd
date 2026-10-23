#!/usr/bin/env python3
"""Open-FDD Soft-OPEN stress gate orchestrator (BPS scripts/stress port).

Linux (on the lab box, API at localhost:8080):
  python scripts/stress/run_gate.py --building-id SYNTH_01

Windows / laptop on the LAN (API on the lab):
  python scripts/stress/run_gate.py --host <lab-ip> --building-id SYNTH_01
  python scripts/stress/run_gate.py --host <lab-ip> --remote-api --building-id SYNTH_01

``--remote-api`` (or a non-localhost ``--host``) skips steps that need a local
Timescale checkout and runs HTTP API gates only.

Fail-closed verdict (exit code):
  0 PASS     every required step ran, exited 0 and wrote a PASS result file
  1 FAIL     any step failed, timed out, or contradicted its result file
  2 BLOCKED  a required step is missing, was skipped, or reported BLOCKED

Optional steps (02, seed, 04–07) are reported NOT_LANDED when absent from this
tree; when present they run and any failure fails the gate. Soft-OPEN ≠ FQ.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from helpers import (  # noqa: E402
    EXIT_BLOCKED,
    EXIT_FAIL,
    EXIT_PASS,
    RESULT_FILE_ENV,
    apply_base_url,
    resolve_base_url,
    safe_print,
)

DEFAULT_STEP_TIMEOUT_S = 1800.0

PASS = "PASS"
FAIL = "FAIL"
BLOCKED = "BLOCKED"
SKIPPED = "SKIPPED"
NOT_LANDED = "NOT_LANDED"
NOT_RUN = "NOT_RUN"


@dataclass(frozen=True)
class Step:
    script: str
    required: bool
    extra_args: tuple[str, ...] = ()
    skip_reason: str | None = None


@dataclass
class StepResult:
    script: str
    required: bool
    status: str
    detail: str = ""
    exit_code: int | None = None


@dataclass
class GateReport:
    results: list[StepResult] = field(default_factory=list)

    @property
    def verdict(self) -> str:
        statuses = [r.status for r in self.results]
        if FAIL in statuses:
            return FAIL
        for r in self.results:
            if r.required and r.status != PASS:
                return BLOCKED
            if r.status == BLOCKED:
                return BLOCKED
        if not any(r.required for r in self.results):
            return BLOCKED
        return PASS

    @property
    def exit_code(self) -> int:
        return {PASS: EXIT_PASS, FAIL: EXIT_FAIL}.get(self.verdict, EXIT_BLOCKED)


def _is_local_base(base: str) -> bool:
    host = (urlparse(base).hostname or "").lower()
    return host in {"127.0.0.1", "localhost", "::1"}


def _read_result_file(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return body if isinstance(body, dict) else None


def run_step(
    step: Step,
    conn_args: list[str],
    *,
    scripts_dir: Path,
    result_dir: Path,
    timeout_s: float,
) -> StepResult:
    if step.skip_reason:
        return StepResult(step.script, step.required, SKIPPED, step.skip_reason)
    path = scripts_dir / step.script
    if not path.is_file():
        if step.required:
            return StepResult(step.script, True, BLOCKED, "required step script missing")
        return StepResult(step.script, False, NOT_LANDED, "optional step not in this tree")

    safe_print("\n" + "=" * 60)
    safe_print(f"-> {step.script}")
    safe_print("=" * 60)
    result_file = result_dir / f"{path.stem}.json"
    result_file.unlink(missing_ok=True)
    env = dict(os.environ)
    env[RESULT_FILE_ENV] = str(result_file)
    cmd = [sys.executable, str(path), *conn_args, *step.extra_args]
    try:
        proc = subprocess.run(cmd, cwd=str(HERE.parents[1]), env=env, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        return StepResult(step.script, step.required, FAIL, f"timed out after {timeout_s:g}s")

    code = proc.returncode
    if code == EXIT_BLOCKED:
        return StepResult(step.script, step.required, BLOCKED, "child reported BLOCKED", code)
    if code != EXIT_PASS:
        return StepResult(step.script, step.required, FAIL, f"exit code {code}", code)
    body = _read_result_file(result_file)
    if body is None:
        return StepResult(
            step.script, step.required, BLOCKED, "exit 0 but no readable result file", code
        )
    if body.get("status") != PASS:
        return StepResult(
            step.script,
            step.required,
            FAIL,
            f"exit 0 but result file says {body.get('status')!r}",
            code,
        )
    return StepResult(step.script, step.required, PASS, "", code)


def run_plan(
    plan: list[Step],
    conn_args: list[str],
    *,
    scripts_dir: Path,
    result_dir: Path,
    timeout_s: float,
) -> GateReport:
    """Run ``plan`` in order; after the first FAIL the rest are NOT_RUN."""
    report = GateReport()
    failed = False
    for step in plan:
        if failed:
            report.results.append(
                StepResult(step.script, step.required, NOT_RUN, "after earlier FAIL")
            )
            continue
        res = run_step(
            step,
            conn_args,
            scripts_dir=scripts_dir,
            result_dir=result_dir,
            timeout_s=timeout_s,
        )
        report.results.append(res)
        failed = res.status == FAIL
    return report


def build_plan(args: argparse.Namespace) -> list[Step]:
    def skip(flag: bool, name: str) -> str | None:
        return f"--{name}" if flag else None

    satdev = ("--allow-satdev-drift",) if args.allow_satdev_drift else ()
    return [
        Step("01_sparql_model.py", required=True),
        Step("02_sparql_fc1_points.py", required=False),
        Step("03_sparql_zone_dataframe.py", required=True),
        Step("seed_sv_spike_fixture.py", required=False, skip_reason=skip(args.skip_seed, "skip-seed")),
        Step("04_sql_vs_pandas_zone.py", required=False, skip_reason=skip(args.skip_oracle, "skip-oracle")),
        Step("05_warehouse_parity_smoke.py", required=False, skip_reason=skip(args.skip_parity, "skip-parity")),
        Step("06_prescreen_sql_vs_pandas.py", required=False, skip_reason=skip(args.skip_prescreen, "skip-prescreen")),
        Step("07_building50_fdd.py", required=False, skip_reason=skip(args.skip_building50, "skip-building50")),
        Step(
            "08_sql_vs_pandas_sparql.py",
            required=True,
            extra_args=satdev,
            skip_reason=skip(args.skip_b50_parity, "skip-b50-parity"),
        ),
        Step(
            "09_analytics_sql_vs_pandas.py",
            required=True,
            skip_reason=skip(args.skip_analytics, "skip-analytics"),
        ),
        Step("10_model_crud_helpers.py", required=True),
    ]


def print_report(report: GateReport) -> None:
    safe_print("\n" + "=" * 60)
    safe_print("Stress gate summary")
    for r in report.results:
        kind = "required" if r.required else "optional"
        tail = f"  ({r.detail})" if r.detail else ""
        safe_print(f"  {r.status:<10} {kind:<8} {r.script}{tail}")
    safe_print("=" * 60)
    safe_print(f"STRESS GATE {report.verdict}")
    safe_print("=" * 60)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Open-FDD SPARQL + SQL/pandas stress gate (Linux local or Windows --host)"
    )
    p.add_argument("--base-url", default=None, help="Full API root URL")
    p.add_argument(
        "--host",
        default=None,
        help="Lab hostname/IP for Windows/LAN clients (builds http://HOST:8080)",
    )
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--user", default=None)
    p.add_argument("--password", default=None)
    p.add_argument(
        "--building-id",
        default=None,
        help="Synthetic building_id (required for SPARQL/TTL gates when present)",
    )
    p.add_argument("--skip-seed", action="store_true")
    p.add_argument("--skip-parity", action="store_true", help="skip warehouse parity (05)")
    p.add_argument("--skip-oracle", action="store_true", help="skip live SQL vs pandas (04)")
    p.add_argument("--skip-prescreen", action="store_true", help="skip HVAC pre-screen (06)")
    p.add_argument("--skip-building50", action="store_true", help="skip Building 50 FDD (07)")
    p.add_argument(
        "--skip-b50-parity",
        action="store_true",
        help="skip required SQL↔pandas SPARQL parity (08); the verdict becomes BLOCKED",
    )
    p.add_argument(
        "--skip-analytics",
        action="store_true",
        help="skip required analytics SQL ↔ pandas proof (09); the verdict becomes BLOCKED",
    )
    p.add_argument(
        "--allow-satdev-drift",
        action="store_true",
        help="forward to 08: downgrade an AHU-SATDEV SQL↔oracle mismatch to WARN "
        "(lab emergency only — default is fail-closed; see #1253)",
    )
    p.add_argument(
        "--remote-api",
        action="store_true",
        help="API-only mode for Windows/LAN: skip seed/05/06/07 (need local Timescale); "
        "still runs HTTP gates 01-04, 08, 09, 10",
    )
    p.add_argument(
        "--with-local-db",
        action="store_true",
        help="Even with --host, still run seed/05/06/07 (requires Timescale reachable)",
    )
    p.add_argument(
        "--step-timeout",
        type=float,
        default=DEFAULT_STEP_TIMEOUT_S,
        help=f"per-step timeout in seconds; a timeout is FAIL (default {DEFAULT_STEP_TIMEOUT_S:g})",
    )
    p.add_argument(
        "--summary-json",
        default=None,
        help="write the per-step verdict summary to this JSON file",
    )
    p.add_argument("--scripts-dir", default=None, help=argparse.SUPPRESS)
    args = p.parse_args(argv)
    if args.step_timeout <= 0:
        p.error("--step-timeout must be > 0")

    base = apply_base_url(
        resolve_base_url(base_url=args.base_url, host=args.host, port=args.port)
    )
    os.environ["OPENFDD_STRESS_BASE"] = base
    if args.user:
        os.environ["OPENFDD_STRESS_USER"] = args.user
    if args.password:
        os.environ["OPENFDD_STRESS_PASS"] = args.password
    if args.building_id:
        os.environ["OPENFDD_STRESS_BUILDING_ID"] = args.building_id

    conn_args: list[str] = ["--base-url", base]
    if args.user:
        conn_args += ["--user", args.user]
    if args.password:
        conn_args += ["--password", args.password]
    if args.building_id:
        conn_args += ["--building-id", args.building_id]

    remote = bool(args.remote_api) or (not _is_local_base(base) and not args.with_local_db)
    if remote:
        safe_print(
            f"Remote API mode against {base}\n"
            "  Running HTTP gates 01-04 + 08 + 09 + 10; skipping seed/05/06/07 "
            "(need lab Timescale). Pass --with-local-db to force them."
        )
        args.skip_seed = True
        args.skip_parity = True
        args.skip_prescreen = True
        args.skip_building50 = True

    safe_print(f"Stress gate target: {base}")
    safe_print("Soft-OPEN ≠ FQ — synthetic sites only")

    scripts_dir = Path(args.scripts_dir).resolve() if args.scripts_dir else HERE
    with tempfile.TemporaryDirectory(prefix="openfdd-stress-") as tmp:
        report = run_plan(
            build_plan(args),
            conn_args,
            scripts_dir=scripts_dir,
            result_dir=Path(tmp),
            timeout_s=args.step_timeout,
        )
    print_report(report)
    if args.summary_json:
        Path(args.summary_json).write_text(
            json.dumps(
                {
                    "verdict": report.verdict,
                    "steps": [r.__dict__ for r in report.results],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
