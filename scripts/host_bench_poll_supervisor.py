#!/usr/bin/env python3
"""Supervise 1-minute bench 5007 poll — commission BACnet or synthetic CSV fallback."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "workspace" / "api"))
os.environ.setdefault("OPENFDD_REPO_ROOT", str(REPO))
os.environ.setdefault("OPENFDD_WORKSPACE_DIR", str(REPO / "workspace"))
os.environ.setdefault("OFDD_DESKTOP_DATA_DIR", str(REPO / "workspace" / "data"))

from openfdd_bridge.bench_b5007_poll import (  # noqa: E402
    enable_bench_5007_poll,
    trigger_poll_once,
)
from openfdd_bridge.commission_client import commission_poll_status  # noqa: E402


def main() -> int:
    interval = max(60, int(os.environ.get("OPENFDD_BENCH_POLL_INTERVAL_S", "60")))
    enable = enable_bench_5007_poll(poll_interval_s=60, start_commission=True)
    print("enable", enable.get("ok"), "points", enable.get("point_count"))

    fail_streak = 0
    while True:
        code, status = commission_poll_status(timeout=5.0)
        used_synthetic = False
        if code == 200 and isinstance(status, dict) and status.get("ok"):
            result = trigger_poll_once()
            ok = bool(result.get("ok"))
            if ok:
                fail_streak = 0
                print(
                    "bacnet_poll",
                    status.get("samples"),
                    "ingest",
                    (result.get("ingest") or {}).get("rows_long"),
                )
            else:
                fail_streak += 1
                print("bacnet_poll_failed", result)
        else:
            fail_streak += 1
            print("commission_unreachable", code, status)

        if fail_streak >= 2:
            tick = subprocess.run(
                [sys.executable, str(REPO / "scripts" / "seed_bench_poll_samples.py"), "--tick"],
                cwd=str(REPO),
                env=os.environ.copy(),
                capture_output=True,
                text=True,
            )
            used_synthetic = True
            fail_streak = 0
            print("synthetic_tick", tick.returncode, (tick.stdout or tick.stderr or "")[:200])

        time.sleep(interval if not used_synthetic else interval)


if __name__ == "__main__":
    raise SystemExit(main())
