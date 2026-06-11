"""Composed FDD / BRICK coverage queries for the Data Model tab (no parallel model store)."""

from __future__ import annotations

from typing import Any

from .model_service import ModelService
from .rule_store import RuleStore
from .site_defaults import ensure_default_site
from .ttl_service import TtlService

PRESET_CATALOG: list[dict[str, str]] = [
    {
        "preset_id": "rules_to_equipment",
        "title": "Rules → Equipment",
        "description": "Each enabled FDD rule and equipment types / ids from bindings.",
    },
    {
        "preset_id": "rules_to_sensors",
        "title": "Rules → Sensors",
        "description": "FDD rules mapped to bound point ids and BRICK sensor classes.",
    },
    {
        "preset_id": "rules_to_bacnet_devices",
        "title": "Rules → BACnet Devices",
        "description": "Rules with BACnet device id and object identifier from point metadata.",
    },
    {
        "preset_id": "equipment_to_points",
        "title": "Equipment → Points",
        "description": "All equipment rows with child points and historian columns.",
    },
    {
        "preset_id": "ahus_vavs_zones",
        "title": "AHUs / VAVs / Zones",
        "description": "HVAC equipment filtered to AHU, VAV, and zone types.",
    },
    {
        "preset_id": "missing_rule_bindings",
        "title": "Missing Rule Bindings",
        "description": "Enabled rules with no point, equipment, or brick_type bindings.",
    },
    {
        "preset_id": "points_by_bacnet_device",
        "title": "Points by BACnet Device",
        "description": "Model points grouped by BACnet device id from metadata.",
    },
    {
        "preset_id": "sensor_classes_used_by_fdd",
        "title": "Sensor Classes Used by FDD",
        "description": "Distinct BRICK point classes referenced by rule bindings.",
    },
    {
        "preset_id": "rule_coverage_by_equipment_type",
        "title": "Rule Coverage by Equipment Type",
        "description": "How many rules target each equipment type via bindings.",
    },
    {
        "preset_id": "orphan_points",
        "title": "Orphan Points / Unused Sensors",
        "description": "Points with no FDD rule binding referencing them.",
    },
]

COLUMNS: dict[str, list[str]] = {
    "rules_to_equipment": ["rule_id", "rule_name", "enabled", "equipment_id", "equipment_type", "brick_types"],
    "rules_to_sensors": ["rule_id", "rule_name", "point_id", "brick_class", "external_id", "equipment_id"],
    "rules_to_bacnet_devices": [
        "rule_id",
        "rule_name",
        "point_id",
        "bacnet_device_id",
        "object_identifier",
        "brick_class",
    ],
    "equipment_to_points": ["equipment_id", "equipment_type", "point_id", "brick_class", "external_id", "series_ref"],
    "ahus_vavs_zones": ["equipment_id", "equipment_type", "name", "point_count"],
    "missing_rule_bindings": ["rule_id", "rule_name", "enabled", "issue"],
    "points_by_bacnet_device": ["bacnet_device_id", "point_id", "brick_class", "external_id", "equipment_id"],
    "sensor_classes_used_by_fdd": ["brick_class", "rule_count", "rule_ids"],
    "rule_coverage_by_equipment_type": ["equipment_type", "rule_count", "rule_ids"],
    "orphan_points": ["point_id", "brick_class", "external_id", "equipment_id"],
}


def _point_meta(point: dict[str, Any]) -> dict[str, str]:
    meta = point.get("metadata") if isinstance(point.get("metadata"), dict) else {}
    return {
        "bacnet_device_id": str(meta.get("bacnet_device_id") or meta.get("device_instance") or ""),
        "object_identifier": str(meta.get("object_identifier") or meta.get("object_id") or ""),
        "series_ref": str(meta.get("external_ref") or ""),
    }


def _equipment_map(model: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for eq in model.get("equipment") or []:
        if isinstance(eq, dict) and eq.get("id"):
            out[str(eq["id"])] = eq
    return out


def _bound_point_ids(rules: list[dict[str, Any]]) -> set[str]:
    ids: set[str] = set()
    for rule in rules:
        bindings = rule.get("bindings") if isinstance(rule.get("bindings"), dict) else {}
        for pid in bindings.get("point_ids") or []:
            if str(pid).strip():
                ids.add(str(pid))
    return ids


def run_fdd_preset(preset_id: str, *, site_id: str | None = None) -> dict[str, Any]:
    meta = next((p for p in PRESET_CATALOG if p["preset_id"] == preset_id), None)
    if meta is None:
        raise KeyError(preset_id)

    svc = ModelService()
    sid = (site_id or "").strip() or ensure_default_site(svc, TtlService())
    model = svc.load()
    rules = [r for r in RuleStore().list_rules() if r.get("enabled", True)]
    eq_map = _equipment_map(model)
    points = [p for p in (model.get("points") or []) if isinstance(p, dict)]
    rows: list[dict[str, Any]] = []

    if preset_id == "rules_to_equipment":
        for rule in rules:
            bindings = rule.get("bindings") if isinstance(rule.get("bindings"), dict) else {}
            eq_ids = [str(x) for x in bindings.get("equipment_ids") or [] if str(x).strip()]
            brick_types = [str(x) for x in bindings.get("brick_types") or [] if str(x).strip()]
            if not eq_ids and not brick_types:
                rows.append(
                    {
                        "rule_id": rule.get("id"),
                        "rule_name": rule.get("name"),
                        "enabled": rule.get("enabled", True),
                        "equipment_id": "",
                        "equipment_type": "",
                        "brick_types": "",
                    }
                )
                continue
            for eid in eq_ids or [""]:
                eq = eq_map.get(eid, {})
                rows.append(
                    {
                        "rule_id": rule.get("id"),
                        "rule_name": rule.get("name"),
                        "enabled": rule.get("enabled", True),
                        "equipment_id": eid,
                        "equipment_type": str(eq.get("equipment_type") or ""),
                        "brick_types": ", ".join(brick_types),
                    }
                )

    elif preset_id == "rules_to_sensors":
        point_by_id = {str(p.get("id")): p for p in points if p.get("id")}
        for rule in rules:
            bindings = rule.get("bindings") if isinstance(rule.get("bindings"), dict) else {}
            pids = [str(x) for x in bindings.get("point_ids") or [] if str(x).strip()]
            if not pids:
                for bt in bindings.get("brick_types") or []:
                    for pt in points:
                        if str(pt.get("brick_type") or "") == str(bt):
                            pids.append(str(pt.get("id")))
            for pid in pids:
                pt = point_by_id.get(pid, {})
                rows.append(
                    {
                        "rule_id": rule.get("id"),
                        "rule_name": rule.get("name"),
                        "point_id": pid,
                        "brick_class": str(pt.get("brick_type") or ""),
                        "external_id": str(pt.get("external_id") or ""),
                        "equipment_id": str(pt.get("equipment_id") or ""),
                    }
                )

    elif preset_id == "rules_to_bacnet_devices":
        point_by_id = {str(p.get("id")): p for p in points if p.get("id")}
        for rule in rules:
            bindings = rule.get("bindings") if isinstance(rule.get("bindings"), dict) else {}
            for pid in bindings.get("point_ids") or []:
                pt = point_by_id.get(str(pid), {})
                m = _point_meta(pt)
                rows.append(
                    {
                        "rule_id": rule.get("id"),
                        "rule_name": rule.get("name"),
                        "point_id": str(pid),
                        "bacnet_device_id": m["bacnet_device_id"],
                        "object_identifier": m["object_identifier"],
                        "brick_class": str(pt.get("brick_type") or ""),
                    }
                )

    elif preset_id == "equipment_to_points":
        for pt in points:
            eq = eq_map.get(str(pt.get("equipment_id") or ""), {})
            m = _point_meta(pt)
            rows.append(
                {
                    "equipment_id": str(pt.get("equipment_id") or ""),
                    "equipment_type": str(eq.get("equipment_type") or ""),
                    "point_id": str(pt.get("id") or ""),
                    "brick_class": str(pt.get("brick_type") or ""),
                    "external_id": str(pt.get("external_id") or ""),
                    "series_ref": m["series_ref"],
                }
            )

    elif preset_id == "ahus_vavs_zones":
        keywords = ("air_handling", "vav", "zone", "ahu")
        counts: dict[str, int] = {}
        for pt in points:
            eid = str(pt.get("equipment_id") or "")
            counts[eid] = counts.get(eid, 0) + 1
        for eid, eq in eq_map.items():
            et = str(eq.get("equipment_type") or "").lower()
            name = str(eq.get("name") or "")
            if any(k in et or k in name.lower() for k in keywords):
                rows.append(
                    {
                        "equipment_id": eid,
                        "equipment_type": eq.get("equipment_type"),
                        "name": name,
                        "point_count": counts.get(eid, 0),
                    }
                )

    elif preset_id == "missing_rule_bindings":
        for rule in rules:
            bindings = rule.get("bindings") if isinstance(rule.get("bindings"), dict) else {}
            has_any = any(
                bindings.get(k)
                for k in ("point_ids", "equipment_ids", "brick_types")
                if bindings.get(k)
            )
            if not has_any:
                rows.append(
                    {
                        "rule_id": rule.get("id"),
                        "rule_name": rule.get("name"),
                        "enabled": rule.get("enabled", True),
                        "issue": "no bindings",
                    }
                )

    elif preset_id == "points_by_bacnet_device":
        for pt in points:
            m = _point_meta(pt)
            dev = m["bacnet_device_id"] or "(none)"
            rows.append(
                {
                    "bacnet_device_id": dev,
                    "point_id": str(pt.get("id") or ""),
                    "brick_class": str(pt.get("brick_type") or ""),
                    "external_id": str(pt.get("external_id") or ""),
                    "equipment_id": str(pt.get("equipment_id") or ""),
                }
            )

    elif preset_id == "sensor_classes_used_by_fdd":
        tally: dict[str, list[str]] = {}
        for rule in rules:
            bindings = rule.get("bindings") if isinstance(rule.get("bindings"), dict) else {}
            for bt in bindings.get("brick_types") or []:
                key = str(bt)
                tally.setdefault(key, []).append(str(rule.get("id") or ""))
        for brick_class, rule_ids in sorted(tally.items()):
            rows.append(
                {
                    "brick_class": brick_class,
                    "rule_count": len(rule_ids),
                    "rule_ids": ", ".join(rule_ids),
                }
            )

    elif preset_id == "rule_coverage_by_equipment_type":
        tally: dict[str, list[str]] = {}
        for rule in rules:
            bindings = rule.get("bindings") if isinstance(rule.get("bindings"), dict) else {}
            for eid in bindings.get("equipment_ids") or []:
                eq = eq_map.get(str(eid), {})
                et = str(eq.get("equipment_type") or "unknown")
                tally.setdefault(et, []).append(str(rule.get("id") or ""))
        for et, rule_ids in sorted(tally.items()):
            rows.append({"equipment_type": et, "rule_count": len(rule_ids), "rule_ids": ", ".join(rule_ids)})

    elif preset_id == "orphan_points":
        bound = _bound_point_ids(rules)
        for pt in points:
            pid = str(pt.get("id") or "")
            if pid and pid not in bound:
                rows.append(
                    {
                        "point_id": pid,
                        "brick_class": str(pt.get("brick_type") or ""),
                        "external_id": str(pt.get("external_id") or ""),
                        "equipment_id": str(pt.get("equipment_id") or ""),
                    }
                )

    return {
        **meta,
        "site_id": sid,
        "query_type": "composed",
        "columns": COLUMNS.get(preset_id, []),
        "row_count": len(rows),
        "rows": rows,
    }


def list_fdd_presets() -> dict[str, Any]:
    return {"presets": PRESET_CATALOG}
