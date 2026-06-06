"""Score BRICK model.json completeness (ported from legacy gateway health-summary)."""

from __future__ import annotations

from typing import Any


def model_health_summary(model: dict[str, Any]) -> dict[str, Any]:
    sites = model.get("sites", []) if isinstance(model.get("sites"), list) else []
    equipment = model.get("equipment", []) if isinstance(model.get("equipment"), list) else []
    points = model.get("points", []) if isinstance(model.get("points"), list) else []

    configured = bool(sites or equipment or points)
    if not configured:
        return {
            "status": "ok",
            "configured": False,
            "score": None,
            "counts": {
                "sites": 0,
                "equipment": 0,
                "points": 0,
                "orphan_equipment": 0,
                "orphan_points_site": 0,
                "orphan_points_equipment": 0,
                "missing_brick_type": 0,
                "missing_fdd_input": 0,
                "duplicate_external_ids": 0,
            },
            "issues": [],
            "summary": "",
        }

    site_ids = {str(s.get("id")) for s in sites if isinstance(s, dict) and s.get("id")}
    equipment_ids = {str(e.get("id")) for e in equipment if isinstance(e, dict) and e.get("id")}

    orphan_equipment = 0
    for eq in equipment:
        if not isinstance(eq, dict):
            continue
        sid = eq.get("site_id")
        if sid and str(sid) not in site_ids:
            orphan_equipment += 1

    orphan_points_site = 0
    orphan_points_equipment = 0
    missing_brick_type = 0
    missing_fdd_input = 0
    duplicate_map: dict[tuple[str, str, str], int] = {}
    for pt in points:
        if not isinstance(pt, dict):
            continue
        sid = pt.get("site_id")
        eqid = pt.get("equipment_id")
        if sid and str(sid) not in site_ids:
            orphan_points_site += 1
        if eqid and str(eqid) not in equipment_ids:
            orphan_points_equipment += 1
        if not str(pt.get("brick_type") or "").strip():
            missing_brick_type += 1
        # fdd_input is only needed when rules use a key different from brick_type.
        if not str(pt.get("fdd_input") or "").strip() and not str(pt.get("brick_type") or "").strip():
            missing_fdd_input += 1
        external_id = str(pt.get("external_id") or "").strip()
        if not external_id:
            continue
        key = (
            str(pt.get("site_id") or ""),
            str(pt.get("equipment_id") or ""),
            external_id,
        )
        duplicate_map[key] = duplicate_map.get(key, 0) + 1
    duplicate_external_ids = sum(1 for count in duplicate_map.values() if count > 1)

    critical = orphan_equipment + orphan_points_site + orphan_points_equipment
    warning = missing_brick_type + missing_fdd_input + duplicate_external_ids
    score = max(0, 100 - (critical * 10) - (warning * 2))

    issues: list[dict[str, str]] = []
    if orphan_equipment:
        issues.append(
            {
                "severity": "critical",
                "title": f"{orphan_equipment} orphan equipment row(s)",
                "detail": "Equipment references a site_id that does not exist.",
            }
        )
    if orphan_points_site:
        issues.append(
            {
                "severity": "critical",
                "title": f"{orphan_points_site} point(s) with unknown site",
                "detail": "Fix site_id on points in Data Model BRICK.",
            }
        )
    if orphan_points_equipment:
        issues.append(
            {
                "severity": "warning",
                "title": f"{orphan_points_equipment} point(s) with unknown equipment",
                "detail": "Equipment_id on points does not match any equipment row.",
            }
        )
    if missing_brick_type:
        issues.append(
            {
                "severity": "warning",
                "title": f"{missing_brick_type} point(s) missing brick_type",
                "detail": "Rule Lab Python rules bind via BRICK classes / fdd_input keys.",
            }
        )
    if missing_fdd_input:
        issues.append(
            {
                "severity": "warning",
                "title": f"{missing_fdd_input} point(s) missing fdd_input",
                "detail": "Set fdd_input when the Python rule uses a key different from brick_type.",
            }
        )
    if duplicate_external_ids:
        issues.append(
            {
                "severity": "warning",
                "title": f"{duplicate_external_ids} duplicate external_id group(s)",
                "detail": "Each site/equipment/external_id tuple should be unique.",
            }
        )

    status = "ok"
    if critical:
        status = "critical"
    elif warning:
        status = "warning"

    return {
        "status": status,
        "configured": True,
        "score": score,
        "counts": {
            "sites": len(sites),
            "equipment": len(equipment),
            "points": len(points),
            "orphan_equipment": orphan_equipment,
            "orphan_points_site": orphan_points_site,
            "orphan_points_equipment": orphan_points_equipment,
            "missing_brick_type": missing_brick_type,
            "missing_fdd_input": missing_fdd_input,
            "duplicate_external_ids": duplicate_external_ids,
        },
        "issues": issues,
        "summary": (
            f"Health score={score}; critical={critical}; warnings={warning}. "
            "Check orphan links, missing BRICK/FDD mappings, and duplicate external IDs."
        ),
    }
