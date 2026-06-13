#!/usr/bin/env python3
"""Merge Acme BACnet control-output points into acme_gl36_model.json from poll CSV.

Adds damper/reheat/pump/OAD/cooling commands so brick_type FDD bindings (FC4 PID hunting)
can sweep every VAV and plant output in the model.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MODEL = REPO / "workspace" / "data" / "acme_gl36_model.json"
POLL_CSV = REPO / "edge_backup" / "local" / "acme" / "vm-bbartling" / "points.all_enabled.csv"

# Poll brick_type → model brick_type (normalize plant pump tag)
BRICK_OVERRIDES = {
    "Point": None,  # use brick_tag heuristic below
}

TAG_TO_BRICK = {
    "DPR-CMD": "Damper_Position_Command",
    "HTG-O": "Heating_Valve_Command",
    "HTG-CMD": "Heating_Valve_Command",
    "CLG-O": "Cooling_Command",
    "CLG-STAT": "Cooling_Command",
    "OAD-CMD": "Outside_Air_Damper_Command",
    "System-Pump-VFD-Signal": "Pump_Speed_Command",
    "SF-CMD": "Supply_Fan_Speed_Command",
}

CONTROL_OBJECT_TYPES = frozenset({"analog-output", "analog-value"})
CONTROL_BRICK_TYPES = frozenset(
    {
        "Damper_Position_Command",
        "Heating_Valve_Command",
        "Cooling_Command",
        "Outside_Air_Damper_Command",
        "Pump_Speed_Command",
        "Supply_Fan_Speed_Command",
        "Cooling_Valve_Command",
    }
)


def _equipment_id(site_id: str, building_id: str, system_id: str) -> str:
    return f"{site_id}-vm-{building_id}-{system_id}"


def _point_row(row: dict[str, str]) -> dict | None:
    obj_type = (row.get("object_type") or "").strip().lower()
    brick = (row.get("brick_class") or row.get("brick_type") or "").strip()
    tag = (row.get("brick_tag") or row.get("haystack_tag") or "").strip()
    if brick in CONTROL_BRICK_TYPES:
        brick_type = brick
    elif tag in TAG_TO_BRICK:
        brick_type = TAG_TO_BRICK[tag]
    elif obj_type not in CONTROL_OBJECT_TYPES:
        return None
    else:
        return None

    point_id = (row.get("point_id") or "").strip()
    if not point_id:
        return None
    site = row.get("site_id") or "acme"
    building = row.get("building_id") or "bbartling"
    system = row.get("system_id") or ""
    if not system:
        return None
    equip = _equipment_id(site, building, system)
    name = (row.get("object_name") or row.get("name") or point_id).strip()
    bacnet_obj = ""
    if row.get("object_type") and row.get("object_instance"):
        bacnet_obj = f"{row['object_type']},{row['object_instance']}"
    series = row.get("series_id") or f"{site}#vm-{building}#{system}#{point_id}"
    units = (row.get("units") or "percent").strip()
    return {
        "id": point_id,
        "name": name,
        "brick_type": brick_type,
        "equipment_id": equip,
        "bacnet_object": bacnet_obj,
        "series_id": series,
        "poll_interval_s": int(row.get("poll_interval_s") or 60),
        "units": units,
        "brick_tag": tag or brick_type,
    }


def merge_control_points(model: dict, rows: list[dict]) -> tuple[dict, int]:
    existing = {p["id"] for p in model.get("points") or [] if isinstance(p, dict) and p.get("id")}
    added = 0
    points = list(model.get("points") or [])
    for row in rows:
        pt = _point_row(row)
        if not pt or pt["id"] in existing:
            continue
        points.append(pt)
        existing.add(pt["id"])
        added += 1
    model["points"] = points
    return model, added


def main() -> int:
    if not MODEL.is_file():
        print(f"Missing model: {MODEL}", file=sys.stderr)
        return 1
    if not POLL_CSV.is_file():
        print(f"Missing poll CSV: {POLL_CSV}", file=sys.stderr)
        return 1
    model = json.loads(MODEL.read_text(encoding="utf-8"))
    with POLL_CSV.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    model, added = merge_control_points(model, rows)
    MODEL.write_text(json.dumps(model, indent=2) + "\n", encoding="utf-8")
    print(f"Merged {added} control-output point(s) into {MODEL}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
