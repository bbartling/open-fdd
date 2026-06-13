#!/usr/bin/env python3
"""12-hour local bench smoke test — BACnet direct + Niagara baskStream (read-only).

Default: 12 hours, 60s poll cadence, checkpoint every 2 hours.

  export OPENFDD_NIAGARA_ADMIN_PASSWORD='…'
  python3 scripts/run_overnight_bench_smoke.py
  python3 scripts/run_overnight_bench_smoke.py --duration-hours 1 --checkpoint-minutes 15
  python3 scripts/run_overnight_bench_smoke.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
API = REPO / "workspace" / "api"
if str(API) not in sys.path:
    sys.path.insert(0, str(API))

os.environ.setdefault("OPENFDD_REPO_ROOT", str(REPO))
os.environ.setdefault("OFDD_DESKTOP_DATA_DIR", str(REPO / "workspace" / "data"))

REPORT_ROOT = REPO / "reports" / "overnight_bench"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _run_pytest(targets: list[str]) -> dict:
    cmd = [sys.executable, "-m", "pytest", *targets, "-q", "--tb=line"]
    env = {**os.environ, "PYTHONPATH": f"{API}:{REPO}"}
    proc = subprocess.run(cmd, cwd=REPO, env=env, capture_output=True, text=True)
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout_tail": proc.stdout.splitlines()[-5:],
        "stderr_tail": proc.stderr.splitlines()[-5:],
    }


def _checkpoint(
    *,
    label: str,
    run_dir: Path,
    api_base: str,
    test_poll_freq: bool,
) -> dict:
    from openfdd_bridge.bench_validator import (  # noqa: E402
        export_report_markdown,
        poll_cadence_report,
        validate_bacnet_vs_niagara,
        write_checkpoint_report,
    )

    report = validate_bacnet_vs_niagara()
    report["checkpoint"] = label
    report["poll_cadence"] = {
        "bacnet": poll_cadence_report(source="bacnet_direct", expected_interval_s=60),
        "niagara": poll_cadence_report(source="niagara_baskstream", station_id="bench9065", expected_interval_s=60),
    }
    report["pytest"] = _run_pytest(
        [
            "tests/workspace_bridge/test_bench_validator.py",
            "tests/workspace_bridge/test_driver_point_contract.py",
            "tests/workspace_bridge/test_niagara.py",
        ]
    )

    if test_poll_freq and api_base:
        report["poll_freq_test"] = _poll_frequency_sequence(api_base)

    paths = write_checkpoint_report(report, label=label)
    (run_dir / f"{label}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (run_dir / f"{label}.md").write_text(export_report_markdown(report), encoding="utf-8")
    report["report_paths"] = paths
    return report


def _poll_frequency_sequence(api_base: str) -> dict:
    """Validate poll interval changes (lab mode) via Niagara API."""
    import asyncio
    from openfdd_bridge.niagara_store import get_station, upsert_station, set_poll_running  # noqa: E402
    from openfdd_bridge.niagara_service import poll_station_once  # noqa: E402

    sid = "bench9065"
    results: dict = {"steps": []}

    async def cycles(n: int, interval: int) -> list[float]:
        station = get_station(sid) or {}
        upsert_station({**station, "id": sid, "poll_interval_seconds": interval})
        times: list[float] = []
        for _ in range(n):
            t0 = time.monotonic()
            try:
                await poll_station_once(sid, persistent=True)
                times.append(time.monotonic() - t0)
            except Exception as exc:
                times.append(-1.0)
                results["steps"].append({"error": str(exc)[:200]})
            await asyncio.sleep(max(15, interval))
        return times

    async def run():
        set_poll_running(sid, True)
        results["steps"].append({"phase": "60s", "durations": await cycles(2, 60)})
        results["steps"].append({"phase": "30s", "durations": await cycles(2, 30)})
        upsert_station({**(get_station(sid) or {}), "id": sid, "poll_interval_seconds": 60})
        results["restored_60s"] = True

    try:
        asyncio.run(run())
        results["ok"] = True
    except Exception as exc:
        results["ok"] = False
        results["error"] = str(exc)[:300]
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration-hours", type=float, default=12.0)
    parser.add_argument("--checkpoint-hours", type=float, default=2.0)
    parser.add_argument("--api", default=os.environ.get("OPENFDD_BASE_URL", "http://127.0.0.1:8765"))
    parser.add_argument("--skip-bootstrap", action="store_true")
    parser.add_argument("--test-poll-freq", action="store_true", help="Run poll interval change test at t=0")
    parser.add_argument("--dry-run", action="store_true", help="Single checkpoint then exit")
    args = parser.parse_args()

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = REPORT_ROOT / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    meta = {
        "started_at": _utc_now(),
        "duration_hours": args.duration_hours,
        "checkpoint_hours": args.checkpoint_hours,
        "read_only": True,
        "run_dir": str(run_dir),
    }
    (run_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    if not args.skip_bootstrap:
        subprocess.run([sys.executable, str(REPO / "scripts" / "bootstrap_bench_dual_source.py")], check=False)

    duration_s = args.duration_hours * 3600
    checkpoint_s = args.checkpoint_hours * 3600
    t0 = time.time()
    checkpoint_n = 0
    final_ok = True
    checkpoints: list[dict] = []

    while True:
        elapsed = time.time() - t0
        label = "final" if elapsed >= duration_s else f"checkpoint_{checkpoint_n:02d}"
        print(f"[{_utc_now()}] Running {label} (elapsed {elapsed/3600:.2f}h)", flush=True)
        cp = _checkpoint(
            label=label,
            run_dir=run_dir,
            api_base=args.api,
            test_poll_freq=args.test_poll_freq and checkpoint_n == 0,
        )
        checkpoints.append({"label": label, "ok": cp.get("ok"), "summary": cp.get("summary")})
        if not cp.get("ok"):
            final_ok = False

        if args.dry_run or elapsed >= duration_s:
            break
        checkpoint_n += 1
        sleep_s = min(checkpoint_s, duration_s - elapsed)
        print(f"Sleeping {sleep_s/3600:.2f}h until next checkpoint…", flush=True)
        time.sleep(sleep_s)

    final = {
        "ok": final_ok,
        "started_at": meta["started_at"],
        "finished_at": _utc_now(),
        "checkpoints": checkpoints,
        "next_actions": [] if final_ok else ["Inspect failing points in checkpoint JSON", "Verify BACnet commission poll loop", "Verify Niagara password env and station reachability"],
    }
    (run_dir / "final_report.json").write_text(json.dumps(final, indent=2), encoding="utf-8")
    (run_dir / "final_report.md").write_text(
        f"# Overnight bench smoke — {'PASS' if final_ok else 'FAIL'}\n\n"
        f"- Started: {meta['started_at']}\n"
        f"- Finished: {final['finished_at']}\n"
        f"- Checkpoints: {len(checkpoints)}\n\n"
        + "\n".join(f"- {c['label']}: {'PASS' if c['ok'] else 'FAIL'} ({c.get('summary')})" for c in checkpoints)
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps(final, indent=2))
    return 0 if final_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
