"""Filter BACnet poll lists to the minimum points required by enabled FDD rules."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


def _norm(text: str) -> str:
    return str(text or "").strip().lower().replace("_", "-")


def collect_fdd_poll_requirements(rules: list[dict[str, Any]]) -> dict[str, Any]:
    """Derive brick classes, point ids, and historian column hints from enabled rules."""
    brick_types: set[str] = set()
    point_ids: set[str] = set()
    column_hints: set[str] = set()
    equipment_ids: set[str] = set()

    for rule in rules:
        if not rule.get("enabled", True):
            continue
        bindings = rule.get("bindings") if isinstance(rule.get("bindings"), dict) else {}
        for bt in bindings.get("brick_types") or []:
            if str(bt).strip():
                brick_types.add(str(bt).strip())
        for pid in bindings.get("point_ids") or bindings.get("direct_point_ids") or []:
            if str(pid).strip():
                point_ids.add(str(pid).strip())
        for eid in bindings.get("equipment_ids") or []:
            if str(eid).strip():
                equipment_ids.add(str(eid).strip())
        cfg = rule.get("config") if isinstance(rule.get("config"), dict) else {}
        for key in ("zone_avg_cols", "compressor_cols", "fan_speed_col", "fan_binary_col"):
            raw = cfg.get(key)
            if isinstance(raw, list):
                column_hints.update(str(x).strip() for x in raw if str(x).strip())
            elif isinstance(raw, str) and raw.strip():
                column_hints.add(raw.strip())
        cm = rule.get("column_map") if isinstance(rule.get("column_map"), dict) else {}
        column_hints.update(str(v).strip() for v in cm.values() if str(v).strip())
        cm_cfg = cfg.get("column_map") if isinstance(cfg.get("column_map"), dict) else {}
        column_hints.update(str(v).strip() for v in cm_cfg.values() if str(v).strip())

    return {
        "brick_types": sorted(brick_types),
        "point_ids": sorted(point_ids),
        "column_hints": sorted(column_hints),
        "equipment_ids": sorted(equipment_ids),
    }


def row_matches_fdd_requirements(row: dict[str, str], req: dict[str, Any]) -> bool:
    pid = (row.get("point_id") or "").strip()
    if pid and pid in req.get("point_ids", []):
        return True

    bc = (row.get("brick_class") or "").strip()
    if bc and bc in req.get("brick_types", []):
        return True

    series = _norm(row.get("series_id") or "")
    oname = _norm(row.get("object_name") or "")
    tag = _norm(row.get("brick_tag") or "")
    for hint in req.get("column_hints") or []:
        h = _norm(hint)
        if not h:
            continue
        if h in series or h in oname or h in tag:
            return True
        if h.replace("-", "") in oname.replace("-", ""):
            return True
    return False


def filter_points_for_fdd_rules(
    rows: list[dict[str, str]],
    rules: list[dict[str, Any]],
    *,
    poll_interval_s: int = 60,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Return (filtered rows with enabled=1, manifest)."""
    req = collect_fdd_poll_requirements(rules)
    matched = [r for r in rows if row_matches_fdd_requirements(r, req)]
    out: list[dict[str, str]] = []
    for row in matched:
        copy = dict(row)
        copy["enabled"] = "1"
        copy["poll_interval_s"] = str(poll_interval_s)
        out.append(copy)

    by_brick: dict[str, int] = {}
    by_device: set[str] = set()
    for row in out:
        by_brick[row.get("brick_class") or "?"] = by_brick.get(row.get("brick_class") or "?", 0) + 1
        by_device.add(str(row.get("device_instance") or ""))

    manifest = {
        "policy": "fdd_minimal_poll",
        "description": "Poll only BACnet points required by enabled FDD rules — never poll the full discovery tree.",
        "enabled_rule_count": sum(1 for r in rules if r.get("enabled", True)),
        "requirements": req,
        "matched_rows": len(out),
        "source_rows": len(rows),
        "device_count": len(by_device - {""}),
        "brick_class_counts": dict(sorted(by_brick.items(), key=lambda x: -x[1])),
        "poll_interval_s": poll_interval_s,
    }
    return out, manifest


def load_rules_store(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return list(data.get("rules") or [])


def filter_points_csv_for_rules(
    *,
    points_csv: Path,
    rules_store: Path,
    output_csv: Path,
    manifest_path: Path | None = None,
    poll_interval_s: int = 60,
) -> dict[str, Any]:
    rows = list(csv.DictReader(points_csv.open(newline="", encoding="utf-8")))
    rules = load_rules_store(rules_store)
    filtered, manifest = filter_points_for_fdd_rules(rows, rules, poll_interval_s=poll_interval_s)
    if not filtered:
        raise ValueError("FDD minimal poll filter matched zero rows — check rules_store bindings vs points.csv")

    fieldnames = list(rows[0].keys()) if rows else list(filtered[0].keys())
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(filtered)

    if manifest_path:
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest
