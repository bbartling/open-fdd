#!/usr/bin/env python3
"""Print AHU/RTU fan and system run hours from feather or poll data (any site)."""

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

DEFAULT_SCRIPT = REPO / "workspace" / "data" / "rules_py" / "ahu_run_hours.py"


def main() -> int:
    parser = argparse.ArgumentParser(description="AHU fan/system run-hour report from stored poll data")
    parser.add_argument("--site-id", "--site", dest="site_id", required=True)
    parser.add_argument("--equipment-id", required=True, help="BRICK equipment id for the AHU/RTU")
    parser.add_argument("--rules-script", type=Path, default=DEFAULT_SCRIPT, help="Python metrics script path")
    parser.add_argument("--lookback-hours", type=float, default=24.0)
    parser.add_argument("--json-out", default="", help="Optional path to write metrics JSON")
    parser.add_argument("--occupied-start-hour", type=int, default=8)
    parser.add_argument("--occupied-end-hour", type=int, default=17)
    parser.add_argument("--tz-offset-hours", type=int, default=-6)
    parser.add_argument("--fan-speed-col", default="supply-fan-speed-command")
    parser.add_argument("--fan-binary-col", default="supply-fan-start-stop-command")
    parser.add_argument(
        "--compressor-cols",
        default="compressor-1-command,compressor-2-command,compressor-3-command,compressor-4-command",
        help="Comma-separated wide-frame column names",
    )
    args = parser.parse_args()

    if not args.rules_script.is_file():
        print(f"Rules script not found: {args.rules_script}", file=sys.stderr)
        return 1

    import pandas as pd

    frame, origin = load_frame_for_run(args.site_id)
    if frame.empty:
        print(f"No data for site {args.site_id}")
        return 1

    if args.lookback_hours > 0 and "timestamp" in frame.columns:
        cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=args.lookback_hours)
        ts = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
        trimmed = frame.loc[ts >= cutoff].copy()
        if not trimmed.empty:
            frame = trimmed

    cfg = {
        "site_id": args.site_id,
        "equipment_id": args.equipment_id,
        "occupied_start_hour": args.occupied_start_hour,
        "occupied_end_hour": args.occupied_end_hour,
        "tz_offset_hours": args.tz_offset_hours,
        "fan_on_threshold": 5.0,
        "fan_speed_col": args.fan_speed_col,
        "fan_binary_col": args.fan_binary_col,
        "compressor_cols": [c.strip() for c in args.compressor_cols.split(",") if c.strip()],
        "max_gap_hours": 2.0,
    }
    code = args.rules_script.read_text(encoding="utf-8")
    result = run_dataframe_script(code, frame, cfg=cfg)
    if not result.get("ok"):
        print(result.get("error") or "script failed")
        return 1

    metrics = result.get("metrics") or {}
    print(f"source={origin} rows={result.get('rows')} lookback={args.lookback_hours}h equipment={args.equipment_id}")
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
        out_path = Path(args.json_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote {args.json_out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
