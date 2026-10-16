#!/usr/bin/env python3
"""Open-FDD Soft-OPEN stress gate orchestrator (BPS scripts/stress port).

Linux (on the lab box, API at localhost:8080):
  python scripts/stress/run_gate.py --building-id SYNTH_01

Windows / laptop on the LAN (API on the lab):
  python scripts/stress/run_gate.py --host <lab-ip> --building-id SYNTH_01
  python scripts/stress/run_gate.py --host <lab-ip> --remote-api --building-id SYNTH_01

``--remote-api`` (or a non-localhost ``--host``) skips steps that need a local
Timescale checkout and runs HTTP API gates only.

Gates land across Soft-OPEN Track C PRs (T12 skeleton → 01+03 → 08 → 09 → CRUD).
Missing scripts are skipped with a note (skeleton-friendly). Soft-OPEN ≠ FQ.

Every SQL↔pandas gate is fail-closed when present: a divergence returns non-zero.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from helpers import (  # noqa: E402
    apply_base_url,
    resolve_base_url,
    safe_print,
)


def _is_local_base(base: str) -> bool:
    host = (urlparse(base).hostname or "").lower()
    return host in {"127.0.0.1", "localhost", "::1"}


def run_step(script: str, extra_args: list[str]) -> int:
    path = HERE / script
    if not path.is_file():
        safe_print(f"SKIP {script} (not landed yet — Soft-OPEN Track C follow-up)")
        return 0
    safe_print("\n" + "=" * 60)
    safe_print(f"-> {script}")
    safe_print("=" * 60)
    cmd = [sys.executable, str(path), *extra_args]
    return subprocess.call(cmd, cwd=str(HERE.parents[1]))


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
        help="skip synthetic pack SQL↔pandas SPARQL parity (08)",
    )
    p.add_argument(
        "--skip-analytics",
        action="store_true",
        help="skip analytics SQL ↔ pandas proof (09)",
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
        "still runs HTTP gates 01-04, 08, 09 when present",
    )
    p.add_argument(
        "--with-local-db",
        action="store_true",
        help="Even with --host, still run seed/05/06/07 (requires Timescale reachable)",
    )
    args = p.parse_args(argv)

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
            "  Running HTTP gates 01-04 + 08 + 09 (when present); skipping seed/05/06/07 "
            "(need lab Timescale). Pass --with-local-db to force them."
        )
        args.skip_seed = True
        args.skip_parity = True
        args.skip_prescreen = True
        args.skip_building50 = True

    safe_print(f"Stress gate target: {base}")
    safe_print("Soft-OPEN ≠ FQ — synthetic sites only")

    steps = ["01_sparql_model.py", "02_sparql_fc1_points.py", "03_sparql_zone_dataframe.py"]
    for s in steps:
        code = run_step(s, conn_args)
        if code != 0:
            return code

    if not args.skip_seed:
        if (HERE / "seed_sv_spike_fixture.py").is_file():
            code = run_step("seed_sv_spike_fixture.py", conn_args)
            if code != 0:
                safe_print(
                    "WARN: seed failed — later oracle gates may FAIL without Timescale data"
                )
        else:
            safe_print(
                "SKIP seed — seed_sv_spike_fixture.py is not in this tree; "
                "import a package that already has timeseries and semantic_meta"
            )

    if not args.skip_oracle:
        code = run_step("04_sql_vs_pandas_zone.py", conn_args)
        if code != 0:
            return code

    if not args.skip_parity:
        code = run_step("05_warehouse_parity_smoke.py", conn_args)
        if code != 0:
            return code

    if not args.skip_prescreen:
        code = run_step("06_prescreen_sql_vs_pandas.py", conn_args)
        if code != 0:
            return code

    if not args.skip_building50:
        code = run_step("07_building50_fdd.py", conn_args)
        if code != 0:
            return code

    if not args.skip_b50_parity:
        extra = ["--allow-satdev-drift"] if args.allow_satdev_drift else []
        code = run_step("08_sql_vs_pandas_sparql.py", conn_args + extra)
        if code != 0:
            return code

    if not args.skip_analytics:
        code = run_step("09_analytics_sql_vs_pandas.py", conn_args)
        if code != 0:
            return code

    # Optional CRUD helpers (T16) — skipped until landed.
    run_step("10_model_crud_helpers.py", conn_args)

    safe_print("\n" + "=" * 60)
    safe_print("STRESS GATE PASS (present steps)")
    safe_print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
