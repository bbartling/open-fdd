#!/usr/bin/env python3
"""One-stop orchestrator for the Open-FDD automated testing toolkit.

Runs the Selenium E2E checks, the SPARQL/UI parity suite, the long-run BACnet
scrape/fault validation, and the hot-reload/FDD rule verification scripts in
sequence. Pass --skip steps if you only want a subset.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import List

SCRIPT_DIR = Path(__file__).resolve().parent


def run_step(cmd: List[str], name: str) -> None:
    print(f"\n=== {name} ===")
    print(" ".join(cmd))
    result = subprocess.run(cmd)
    if result.returncode != 0:
        raise SystemExit(f"{name} failed with exit code {result.returncode}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the full Open-FDD test bench")
    parser.add_argument("--api-url", required=True, help="Base URL for the FastAPI backend (e.g. http://192.168.204.16:8000)")
    parser.add_argument("--frontend-url", required=True, help="Origin for the React frontend (e.g. http://192.168.204.16)")
    parser.add_argument("--bacnet-devices", nargs="+", default=["3456789", "3456790"], help="BACnet device instance numbers for the Selenium E2E script")
    parser.add_argument("--headed", action="store_true", help="Run Selenium flows with a visible browser window")
    parser.add_argument("--skip", choices=["e2e", "sparql", "long-run", "hot-reload"], action="append", default=[], help="Skip one or more steps")
    parser.add_argument("--long-run-check-faults", action="store_true", help="Enable fault schedule verification in the long-run test")
    parser.add_argument("--long-run-config-via-frontend", action="store_true", help="Have the long-run test adjust config via the frontend instead of API")
    parser.add_argument("--long-run-short-day", action="store_true", help="Run the BACnet scrape test in a daytime short profile (<2h) instead of the full ~3h once pass")
    parser.add_argument("--daytime-smoke", action="store_true", help="Run the recommended daytime smoke profile: E2E + SPARQL parity + short BACnet/FDD pass + hot reload")
    parser.add_argument("--hot-reload-frontend-check", action="store_true", help="Run the optional /faults UI smoke check in the hot-reload script")
    args = parser.parse_args()

    if args.daytime_smoke:
        args.long_run_check_faults = True
        args.long_run_short_day = True
        args.hot_reload_frontend_check = True

    python = sys.executable

    if "e2e" not in args.skip:
        cmd = [python, str(SCRIPT_DIR / "1_e2e_frontend_selenium.py"), "--frontend-url", args.frontend_url, "--bacnet-device-instance", *args.bacnet_devices]
        if args.headed:
            cmd.append("--headed")
        run_step(cmd, "E2E frontend Selenium")

    if "sparql" not in args.skip:
        cmd = [
            python,
            str(SCRIPT_DIR / "2_sparql_crud_and_frontend_test.py"),
            "--api-url",
            args.api_url,
            "--frontend-url",
            args.frontend_url,
            "--frontend-parity",
        ]
        if args.headed:
            cmd.append("--headed")
        run_step(cmd, "SPARQL CRUD + frontend parity")

    if "long-run" not in args.skip:
        cmd = [
            python,
            str(SCRIPT_DIR / "3_long_term_bacnet_scrape_test.py"),
            "--api-url",
            args.api_url,
            "--frontend-url",
            args.frontend_url,
            "--once",
        ]
        if args.long_run_check_faults:
            cmd.append("--check-faults")
        if args.long_run_config_via_frontend:
            cmd.append("--config-via-frontend")
        if args.long_run_short_day:
            cmd.append("--short-day")
        run_step(cmd, "Long-run BACnet scrape + fault schedule")

    if "hot-reload" not in args.skip:
        cmd = [
            python,
            str(SCRIPT_DIR / "4_hot_reload_test.py"),
            "--api-url",
            args.api_url,
        ]
        if args.hot_reload_frontend_check:
            cmd.extend(["--frontend-url", args.frontend_url, "--frontend-check"])
            if args.headed:
                cmd.append("--headed")
        run_step(cmd, "Rules hot-reload + FDD verification")

    print("\nAll selected steps completed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
