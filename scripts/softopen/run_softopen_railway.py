#!/usr/bin/env python3
"""Soft-OPEN orchestrator for Railway (or any --host hub).

Runs, in order:
  1) hub health wait
  2) optional assert_hub_env_after_repin.sh when --assert-hub and railway CLI present
  3) scripts/lessons (each present lesson_*.py)
  4) scripts/stress/run_gate.py (HTTP subset)
  5) validate_db_samples.py
  6) validate_plot_bool.py

Unique building ids: pass --building-id or --unique-building (SOFTOPEN_<date>_<sha>).
No screenshots. Soft-OPEN ≠ FQ. ZAP out of scope.

  python scripts/softopen/run_softopen_railway.py \\
    --host openfdd-web-production.up.railway.app --building-id SYNTH_03

  python scripts/softopen/run_softopen_railway.py \\
    --base-url https://openfdd-web-production.up.railway.app \\
    --unique-building --shortsha 52e1045
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SOFTOPEN = Path(__file__).resolve().parent
STRESS = REPO / "scripts" / "stress"
LESSONS = REPO / "scripts" / "lessons"

if str(STRESS) not in sys.path:
    sys.path.insert(0, str(STRESS))

from helpers import (  # noqa: E402
    apply_base_url,
    resolve_base_url,
    safe_print,
    unique_softopen_building_id,
)


def _conn_base(args: argparse.Namespace) -> str:
    return apply_base_url(
        resolve_base_url(base_url=args.base_url, host=args.host, port=args.port)
    )


def _run(cmd: list[str], *, cwd: Path) -> int:
    safe_print("\n" + "=" * 60)
    safe_print("-> " + " ".join(cmd))
    safe_print("=" * 60)
    return subprocess.call(cmd, cwd=str(cwd))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Soft-OPEN Railway lessons+stress+plot-bool")
    p.add_argument("--base-url", default=None)
    p.add_argument("--host", default=None)
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--user", default=None)
    p.add_argument("--password", default=None)
    p.add_argument("--building-id", default=None)
    p.add_argument(
        "--unique-building",
        action="store_true",
        help="Allocate SOFTOPEN_<date>_<sha> (needs import/fixture separately)",
    )
    p.add_argument("--shortsha", default=None)
    p.add_argument(
        "--assert-hub",
        action="store_true",
        help="Run scripts/ops/assert_hub_env_after_repin.sh when present",
    )
    p.add_argument("--skip-lessons", action="store_true")
    p.add_argument("--skip-stress", action="store_true")
    p.add_argument("--skip-db", action="store_true")
    p.add_argument("--skip-plots", action="store_true")
    args = p.parse_args(argv)
    base = _conn_base(args)

    building_id = (args.building_id or os.environ.get("OPENFDD_STRESS_BUILDING_ID") or "").strip()
    if args.unique_building or not building_id:
        building_id = unique_softopen_building_id(shortsha=args.shortsha)
        safe_print(
            f"NOTE: Soft-OPEN building_id={building_id} "
            "(import fixture before expecting PASS on a brand-new id)"
        )

    common = ["--base-url", base, "--building-id", building_id]
    if args.user:
        common += ["--user", args.user]
    if args.password:
        common += ["--password", args.password]

    safe_print("Soft-OPEN Railway orchestrator")
    safe_print(f"  base_url     {base}")
    safe_print(f"  building_id  {building_id}")
    safe_print("  screenshots  OFF (bool API gates only)")
    safe_print("  soft-open    Soft-OPEN ≠ FQ; ZAP deferred")

    fails = 0

    if args.assert_hub:
        script = REPO / "scripts" / "ops" / "assert_hub_env_after_repin.sh"
        if script.is_file():
            sha = args.shortsha or os.environ.get("OPENFDD_IMAGE_TAG") or ""
            cmd = ["bash", str(script)]
            if sha:
                cmd.append(sha if sha.startswith("sha-") else f"sha-{sha}")
            env = os.environ.copy()
            env["OPENFDD_API_BASE"] = base
            rc = subprocess.call(cmd, cwd=str(REPO), env=env)
            if rc != 0:
                fails += 1
        else:
            safe_print("SKIP assert_hub (script missing)")

    if not args.skip_lessons:
        lessons = sorted(LESSONS.glob("lesson_*.py"))
        if not lessons:
            safe_print("SKIP lessons (none landed)")
        for path in lessons:
            rc = _run([sys.executable, str(path), *common], cwd=REPO)
            if rc != 0:
                fails += 1

    if not args.skip_stress:
        gate = STRESS / "run_gate.py"
        if gate.is_file():
            rc = _run(
                [
                    sys.executable,
                    str(gate),
                    *common,
                    "--remote-api",
                    "--skip-prescreen",
                    "--skip-building50",
                ],
                cwd=REPO,
            )
            if rc != 0:
                fails += 1
        else:
            safe_print("SKIP stress run_gate.py missing")

    if not args.skip_db:
        rc = _run(
            [sys.executable, str(SOFTOPEN / "validate_db_samples.py"), *common],
            cwd=REPO,
        )
        if rc != 0:
            fails += 1

    if not args.skip_plots:
        rc = _run(
            [sys.executable, str(SOFTOPEN / "validate_plot_bool.py"), *common],
            cwd=REPO,
        )
        if rc != 0:
            fails += 1

    if fails:
        safe_print(f"\nFAIL Soft-OPEN Railway suite ({fails} step groups)")
        return 2
    safe_print("\nPASS Soft-OPEN Railway suite")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
