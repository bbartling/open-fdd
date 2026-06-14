"""Composed FDD / BRICK coverage queries for the Data Model tab (no parallel model store)."""

from __future__ import annotations

from typing import Any

from .equipment_classify import effective_equipment_type, hvac_bucket
from .fdd_equipment import data_source_label
from .model_service import ModelService
from .rule_store import RuleStore
from .site_defaults import ensure_default_site
from .ttl_service import TtlService

PRESET_CATALOG: list[dict[str, str]] = [
    {
        "preset_id": "rules_by_data_source",
        "title": "Rules by data source",
        "description": "Source-agnostic FDD rules with bound points grouped by BACnet vs Niagara driver.",
    },
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
    "rules_by_data_source": [
        "rule_id",
        "rule_name",
        "short_description",
        "data_source",
        "bound_points",
        "point_ids",
    ],
    "rules_to_equipment": ["rule_id", "rule_name", "short_description", "enabled", "equipment_id", "equipment_type", "brick_types"],
    "rules_to_sensors": [
        "rule_id",
        "rule_name",
        "short_description",
        "data_source",
        "point_id",
        "brick_class",
        "external_id",
        "equipment_id",
    ],
    "rules_to_bacnet_devices": [
        "rule_id",
        "rule_name",
        "point_id",
        "bacnet_device_id",
        "object_identifier",
        "brick_class",
    ],
    "equipment_to_points": ["equipment_id", "equipment_type", "point_id", "brick_class", "external_id", "series_ref"],
    "ahus_vavs_zones": ["equipment_id", "hvac_class", "equipment_type", "brick_type", "name", "point_count"],
    "missing_rule_bindings": ["rule_id", "rule_name", "enabled", "issue"],
    "points_by_bacnet_device": ["bacnet_device_id", "point_id", "brick_class", "external_id", "equipment_id"],
    "sensor_classes_used_by_fdd": ["brick_class", "rule_count", "rule_ids"],
    "rule_coverage_by_equipment_type": ["equipment_type", "rule_count", "rule_ids"],
    "orphan_points": ["point_id", "brick_class", "external_id", "equipment_id"],
}


def _point_meta(point: dict[str, Any], eq_map: dict[str, dict[str, Any]] | None = None) -> dict[str, str]:
    meta = point.get("metadata") if isinstance(point.get("metadata"), dict) else {}
    eq = (eq_map or {}).get(str(point.get("equipment_id") or ""), {})
    dev = str(
        point.get("bacnet_device_id")
        or meta.get("bacnet_device_id")
        or meta.get("device_instance")
        or eq.get("bacnet_device_instance")
        or eq.get("bacnet_device_id")
        or ""
    )
    if not dev:
        import re

        m = re.match(r"^(\d+)-", str(point.get("id") or ""))
        if m:
            dev = m.group(1)
    obj = str(
        point.get("object_identifier")
        or meta.get("object_identifier")
        or meta.get("object_id")
        or point.get("bacnet_object")
        or ""
    )
    return {
        "bacnet_device_id": dev,
        "object_identifier": obj,
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


def _point_source_label(pt: dict[str, Any], eq_map: dict[str, dict[str, Any]]) -> str:
    eq = eq_map.get(str(pt.get("equipment_id") or ""), {})
    label = data_source_label(eq)
    if label:
        return label
    pid = str(pt.get("id") or "").lower()
    if pid.startswith("niagara-"):
        return "Niagara"
    if pid[:1].isdigit() or "analog-" in pid or "binary-" in pid:
        return "BACnet"
    meta = pt.get("metadata") if isinstance(pt.get("metadata"), dict) else {}
    driver = str(meta.get("driver") or meta.get("source") or "").strip()
    return driver.replace("_", " ") if driver else "(unassigned)"


def _rule_short_description(rule: dict[str, Any]) -> str:
    return str(rule.get("short_description") or rule.get("name") or "").strip()


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

    if preset_id == "rules_by_data_source":
        point_by_id = {str(p.get("id")): p for p in points if p.get("id")}
        for rule in rules:
            bindings = rule.get("bindings") if isinstance(rule.get("bindings"), dict) else {}
            pids = [str(x) for x in bindings.get("point_ids") or [] if str(x).strip()]
            if not pids:
                rows.append(
                    {
                        "rule_id": rule.get("id"),
                        "rule_name": rule.get("name"),
                        "short_description": _rule_short_description(rule),
                        "data_source": "(no bindings)",
                        "bound_points": 0,
                        "point_ids": "",
                    }
                )
                continue
            by_source: dict[str, list[str]] = {}
            for pid in pids:
                pt = point_by_id.get(pid, {})
                src = _point_source_label(pt, eq_map)
                by_source.setdefault(src, []).append(pid)
            for src in sorted(by_source):
                pids_for_src = by_source[src]
                preview = ", ".join(pids_for_src[:6])
                if len(pids_for_src) > 6:
                    preview += "…"
                rows.append(
                    {
                        "rule_id": rule.get("id"),
                        "rule_name": rule.get("name"),
                        "short_description": _rule_short_description(rule),
                        "data_source": src,
                        "bound_points": len(pids_for_src),
                        "point_ids": preview,
                    }
                )

    elif preset_id == "rules_to_equipment":
        for rule in rules:
            bindings = rule.get("bindings") if isinstance(rule.get("bindings"), dict) else {}
            eq_ids = [str(x) for x in bindings.get("equipment_ids") or [] if str(x).strip()]
            brick_types = [str(x) for x in bindings.get("brick_types") or [] if str(x).strip()]
            if not eq_ids and not brick_types:
                rows.append(
                    {
                        "rule_id": rule.get("id"),
                        "rule_name": rule.get("name"),
                        "short_description": _rule_short_description(rule),
                        "enabled": rule.get("enabled", True),
                        "equipment_id": "",
                        "equipment_type": "",
                        "brick_types": "",
                    }
                )
                continue
            if eq_ids:
                for eid in eq_ids:
                    eq = eq_map.get(eid, {})
                    rows.append(
                        {
                            "rule_id": rule.get("id"),
                            "rule_name": rule.get("name"),
                            "short_description": _rule_short_description(rule),
                            "enabled": rule.get("enabled", True),
                            "equipment_id": eid,
                            "equipment_type": effective_equipment_type(eq),
                            "brick_types": ", ".join(brick_types),
                        }
                    )
                continue
            matched_eq: set[str] = set()
            for bt in brick_types:
                for pt in points:
                    if str(pt.get("brick_type") or "") == bt:
                        eid = str(pt.get("equipment_id") or "")
                        if eid:
                            matched_eq.add(eid)
            if matched_eq:
                for eid in sorted(matched_eq):
                    eq = eq_map.get(eid, {})
                    rows.append(
                        {
                            "rule_id": rule.get("id"),
                            "rule_name": rule.get("name"),
                            "short_description": _rule_short_description(rule),
                            "enabled": rule.get("enabled", True),
                            "equipment_id": eid,
                            "equipment_type": effective_equipment_type(eq),
                            "brick_types": ", ".join(brick_types),
                        }
                    )
            else:
                rows.append(
                    {
                        "rule_id": rule.get("id"),
                        "rule_name": rule.get("name"),
                        "short_description": _rule_short_description(rule),
                        "enabled": rule.get("enabled", True),
                        "equipment_id": "",
                        "equipment_type": "",
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
                        "short_description": _rule_short_description(rule),
                        "data_source": _point_source_label(pt, eq_map),
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
                m = _point_meta(pt, eq_map)
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
            m = _point_meta(pt, eq_map)
            rows.append(
                {
                    "equipment_id": str(pt.get("equipment_id") or ""),
                    "equipment_type": effective_equipment_type(eq),
                    "point_id": str(pt.get("id") or ""),
                    "brick_class": str(pt.get("brick_type") or ""),
                    "external_id": str(pt.get("external_id") or ""),
                    "series_ref": m["series_ref"],
                }
            )

    elif preset_id == "ahus_vavs_zones":
        counts: dict[str, int] = {}
        for pt in points:
            eid = str(pt.get("equipment_id") or "")
            counts[eid] = counts.get(eid, 0) + 1
        for eid, eq in eq_map.items():
            bucket = hvac_bucket(eq)
            if not bucket:
                continue
            rows.append(
                {
                    "equipment_id": eid,
                    "hvac_class": bucket,
                    "equipment_type": effective_equipment_type(eq),
                    "brick_type": str(eq.get("brick_type") or ""),
                    "name": str(eq.get("name") or ""),
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
            m = _point_meta(pt, eq_map)
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
            eq_ids = [str(x) for x in bindings.get("equipment_ids") or [] if str(x).strip()]
            brick_types = [str(x) for x in bindings.get("brick_types") or [] if str(x).strip()]
            targets: set[str] = set(eq_ids)
            if not targets and brick_types:
                for bt in brick_types:
                    for pt in points:
                        if str(pt.get("brick_type") or "") == bt:
                            eid = str(pt.get("equipment_id") or "")
                            if eid:
                                targets.add(eid)
            for eid in targets or [""]:
                eq = eq_map.get(eid, {}) if eid else {}
                et = effective_equipment_type(eq) if eid else "BRICK-bound"
                if et in ("", "Equipment"):
                    et = "BRICK-bound"
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
