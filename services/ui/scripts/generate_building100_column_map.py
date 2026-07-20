"""Generate BUILDING_100 column→role JSON map and optionally validate rules."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.cache import cached_weather
from app.column_map_json import (
    build_column_map_from_equipment_frames,
    column_map_to_role_map,
    merge_column_map_into_role_map,
    save_column_map_json,
    validate_column_map_against_frames,
)
from app.config import AppConfig
from app.data_loader import load_building_tree
from app.role_map import apply_role_map
from app.rules import CANONICAL_RULE_COUNT
from app.rules.runner import run_all_cookbook_rules
from collections import Counter


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--building", default="BUILDING_100")
    ap.add_argument(
        "--out",
        type=Path,
        default=Path("configs/building_100_column_map.json"),
        help="Output JSON path",
    )
    ap.add_argument("--run-rules", action="store_true", help="Run all 50 rules after generating map")
    args = ap.parse_args()

    cfg = AppConfig.load()
    frames = load_building_tree(cfg.data_root, args.building)
    if not frames:
        raise SystemExit(f"No equipment under {cfg.data_root / args.building}")

    column_map = build_column_map_from_equipment_frames(
        frames, building_id=args.building, generated_by="heuristic"
    )
    issues = validate_column_map_against_frames(column_map, frames)
    save_column_map_json(args.out, column_map)
    print(f"Wrote {args.out} ({len(column_map['equipment'])} equipment)")
    if issues:
        print(f"Validation issues ({len(issues)}):")
        for i in issues[:20]:
            print(f"  - {i}")
    else:
        print("All mapped columns exist in history CSVs.")

    if not args.run_rules:
        return

    role_map = merge_column_map_into_role_map({}, column_map, prefer_json=True)
    weather = cached_weather(str(cfg.data_root), cfg.weather_subdir)
    status: Counter = Counter()
    for eq_id, raw in frames.items():
        mapped = apply_role_map(raw, eq_id, role_map)
        mapped.attrs.update(raw.attrs)
        mapped.attrs["equipment_id"] = eq_id
        poll = float(raw.attrs.get("poll_seconds", 300))
        for r in run_all_cookbook_rules(
            mapped,
            equipment_id=eq_id,
            poll_seconds=poll,
            params_by_rule={},
            weather=weather,
        ):
            status[r.status] += 1

    print(json.dumps(
        {
            "canonical_rules": CANONICAL_RULE_COUNT,
            "equipment": len(frames),
            "role_map_equipment": len(column_map_to_role_map(column_map)),
            "status": dict(status),
        },
        indent=2,
    ))


if __name__ == "__main__":
    main()
