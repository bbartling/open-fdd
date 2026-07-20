#!/usr/bin/env python
"""CSV parity check — load any building folder (not just BUILDING_100) and print rule rollups.

Usage:
  python scripts/csv_parity_check.py --building-folder /path/to/MySite
  python scripts/csv_parity_check.py --data-root ./data/hvac_systems_CLEANED --building MySite

Optional: --column-map configs/building_100_column_map.json (works for any building if roles match)
Optional: --json-out results.json for CI diffs
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.column_map_json import load_column_map_json, merge_column_map_into_role_map
from app.data_loader import load_building_folder, load_building_tree
from app.role_map import apply_role_map, enrich_role_map_from_equipment, load_role_map
from app.rules import RULES, run_all
from app.weather_psychrometrics import enrich_weather_frame


def _load_weather(data_root: Path, subdir: str = "weather"):
    hist = data_root / subdir / "history_wide.csv"
    if not hist.is_file():
        return None
    import pandas as pd

    df = pd.read_csv(hist)
    from app.data_loader import normalize_timestamp, detect_timestamp_column

    ts = detect_timestamp_column(df)
    df = normalize_timestamp(df, ts)
    return enrich_weather_frame(df)


def main() -> int:
    ap = argparse.ArgumentParser(description="Run 50-rule cookbook on any building CSV tree")
    ap.add_argument("--building-folder", type=Path, help="Path to a building folder (contains AHU_*/history_wide.csv)")
    ap.add_argument("--data-root", type=Path, help="Parent of building folders + weather/")
    ap.add_argument("--building", type=str, help="Building folder name under --data-root")
    ap.add_argument("--column-map", type=Path, help="Optional JSON column map")
    ap.add_argument("--role-map", type=Path, default=ROOT / "configs" / "role_map.yaml")
    ap.add_argument("--json-out", type=Path, help="Write summary JSON")
    ap.add_argument("--confirm-min", type=float, default=0.0)
    args = ap.parse_args()

    if args.building_folder:
        frames = load_building_folder(args.building_folder)
        weather_root = args.building_folder.parent
        building_id = args.building_folder.name
    elif args.data_root and args.building:
        frames = load_building_tree(args.data_root, args.building)
        weather_root = args.data_root
        building_id = args.building
    else:
        ap.error("Provide --building-folder OR (--data-root AND --building)")
        return 2

    if not frames:
        print(f"No equipment loaded for {building_id}", file=sys.stderr)
        return 1

    role_map: dict = {}
    if args.role_map.is_file():
        role_map = load_role_map(args.role_map)
    if args.column_map and args.column_map.is_file():
        cm = load_column_map_json(args.column_map)
        role_map = merge_column_map_into_role_map(role_map, cm, prefer_json=True)

    for eq_id, df in frames.items():
        enrich_role_map_from_equipment(
            role_map,
            eq_id,
            Path(df.attrs["columns_path"]) if df.attrs.get("columns_path") else None,
            list(df.columns),
        )

    weather = _load_weather(weather_root)
    params = {r.id: {"confirm_min": args.confirm_min} for r in RULES}

    rows = []
    for eq_id, raw in sorted(frames.items()):
        mapped = apply_role_map(raw, eq_id, role_map)
        mapped.attrs["equipment_id"] = eq_id
        poll = float(raw.attrs.get("poll_seconds") or 300.0)
        results = run_all(mapped, params_by_rule=params, poll_seconds=poll, weather=weather)
        for r in results:
            rows.append(
                {
                    "building_id": building_id,
                    "equipment_id": r.equipment_id,
                    "rule_id": r.rule_id,
                    "status": r.status,
                    "fault_hours": r.fault_hours,
                }
            )

    fault_n = sum(1 for r in rows if r["status"] == "FAULT")
    err_n = sum(1 for r in rows if r["status"] == "ERROR")
    print(f"building={building_id} equipment={len(frames)} evaluations={len(rows)} FAULT={fault_n} ERROR={err_n}")
    if args.json_out:
        args.json_out.write_text(json.dumps({"building_id": building_id, "rows": rows}, indent=2), encoding="utf-8")
        print(f"wrote {args.json_out}")
    return 0 if err_n == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
