#!/usr/bin/env python3
"""Print RTU fan/system run hours from feather or poll CSV (Acme GL36 site)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
API = REPO / "workspace" / "api"
if str(API) not in sys.path:
    sys.path.insert(0, str(API))

os.environ.setdefault("OPENFDD_REPO_ROOT", str(REPO))
os.environ.setdefault("OFDD_DESKTOP_DATA_DIR", str(REPO / "workspace" / "data"))

from openfdd_bridge.data_loader import load_frame_for_run  # noqa: E402
from openfdd_bridge.playground import run_dataframe_script  # noqa: E402


def _read_script() -> str:
    return (REPO / "workspace" / "data" / "rules_py" / "acme_ahu_run_hours.py").read_text(encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Acme RTU-01 run-hour report from stored poll data")
    parser.add_argument("--site", default="acme")
    parser.add_argument("--lookback-hours", type=float, default=24.0)
    parser.add_argument("--json-out", default="", help="Optional path to write metrics JSON")
    args = parser.parse_args()

    import pandas as pd

    frame, origin = load_frame_for_run(args.site)
    if frame.empty:
        print(f"No data for site {args.site}")
        return 1

    if args.lookback_hours > 0 and "timestamp" in frame.columns:
        cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=args.lookback_hours)
        ts = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
        trimmed = frame.loc[ts >= cutoff].copy()
        if not trimmed.empty:
            frame = trimmed

    cfg = {
        "site_id": args.site,
        "equipment_id": "acme-vm-bbartling-rtu-01",
        "occupied_start_hour": 8,
        "occupied_end_hour": 17,
        "tz_offset_hours": -6,
        "fan_on_threshold": 5.0,
        "fan_speed_col": "supply-fan-speed-command",
        "fan_binary_col": "supply-fan-start-stop-command",
        "compressor_cols": [
            "compressor-1-command",
            "compressor-2-command",
            "compressor-3-command",
            "compressor-4-command",
        ],
        "max_gap_hours": 2.0,
    }
    result = run_dataframe_script(_read_script(), frame, cfg=cfg)
    if not result.get("ok"):
        print(result.get("error") or "script failed")
        return 1

    metrics = result.get("metrics") or {}
    print(f"source={origin} rows={result.get('rows')} lookback={args.lookback_hours}h")
    for key in (
        "fan_run_hours",
        "system_run_hours",
        "occupied_fan_run_hours",
        "afterhours_fan_run_hours",
        "lookback_first_ts",
        "lookback_last_ts",
    ):
        if key in metrics:
            print(f"  {key}: {metrics[key]}")

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote {args.json_out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
