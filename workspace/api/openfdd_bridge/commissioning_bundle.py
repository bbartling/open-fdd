"""Combined BRICK model + FDD rule assignment export/import for human/AI commissioning."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from .rule_bindings import normalize_bindings
from .rule_store import RuleStore


def _strip_point_assignment_fields(pt: dict[str, Any]) -> dict[str, Any]:
    row = dict(pt)
    row.pop("fdd_rule_ids", None)
    row.pop("fdd_rules_linked", None)
    return row


def _rule_source_file(rule: dict[str, Any]) -> str:
    raw = str(rule.get("source_path") or "").strip()
    return Path(raw).name if raw else ""


def _rules_by_point(rules: list[dict[str, Any]]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = defaultdict(list)
    for rule in rules:
        if rule.get("enabled") is False:
            continue
        rid = str(rule.get("id") or "").strip()
        if not rid:
            continue
        b = normalize_bindings(rule.get("bindings"))
        for pid in b["point_ids"]:
            p = str(pid).strip()
            if p and rid not in out[p]:
                out[p].append(rid)
    return out


def build_commissioning_export(model: dict[str, Any], rules: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Export sites, equipment, points (with fdd_rule_ids + names) and rule binding summary."""
    rules = rules if rules is not None else RuleStore().list_rules()
    rule_name_by_id = {
        str(rule.get("id") or "").strip(): str(rule.get("name") or rule.get("id") or "")
        for rule in rules
        if isinstance(rule, dict) and str(rule.get("id") or "").strip()
    }
    by_point = _rules_by_point(rules)
    points: list[dict[str, Any]] = []
    for pt in model.get("points") or []:
        if not isinstance(pt, dict):
            continue
        row = dict(pt)
        pid = str(pt.get("id") or "").strip()
        bound = sorted(by_point.get(pid, []))
        if bound:
            row["fdd_rule_ids"] = bound
            row["fdd_rules_linked"] = [
                {"id": rid, "name": rule_name_by_id.get(rid, rid)} for rid in bound
            ]
        points.append(row)

    fdd_rules: list[dict[str, Any]] = []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        rid = str(rule.get("id") or "").strip()
        if not rid:
            continue
        entry: dict[str, Any] = {
            "id": rid,
            "name": str(rule.get("name") or rid),
            "enabled": rule.get("enabled") is not False,
            "bindings": normalize_bindings(rule.get("bindings")),
        }
        source_file = _rule_source_file(rule)
        if source_file:
            entry["source_file"] = source_file
        fdd_rules.append(entry)
    fdd_rules.sort(key=lambda r: str(r.get("name") or "").lower())

    return {
        "version": 1,
        "sites": list(model.get("sites") or []),
        "equipment": list(model.get("equipment") or []),
        "points": points,
        "fdd_rules": fdd_rules,
    }


def _model_payload_from_commissioning(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "sites": payload.get("sites") or [],
        "equipment": payload.get("equipment") or [],
        "points": [
            _strip_point_assignment_fields(pt)
            for pt in (payload.get("points") or [])
            if isinstance(pt, dict)
        ],
    }


def _bindings_from_points(points: list[dict[str, Any]]) -> dict[str, dict[str, list[str]]]:
    """rule_id -> normalized bindings rebuilt from points[].fdd_rule_ids."""
    rule_points: dict[str, set[str]] = defaultdict(set)
    for pt in points:
        if not isinstance(pt, dict):
            continue
        pid = str(pt.get("id") or "").strip()
        if not pid:
            continue
        for rid in pt.get("fdd_rule_ids") or []:
            r = str(rid).strip()
            if r:
                rule_points[r].add(pid)
    return {
        rid: normalize_bindings({"point_ids": sorted(pids), "direct_point_ids": sorted(pids)})
        for rid, pids in rule_points.items()
    }


def validate_commissioning_payload(payload: dict[str, Any], *, known_rule_ids: set[str] | None = None) -> dict[str, Any]:
    """Validate commissioning import JSON — sites, equipment, points, rule refs."""
    issues: list[str] = []
    sites = {str(s.get("id") or s.get("site_id") or "").strip() for s in (payload.get("sites") or []) if isinstance(s, dict)}
    sites.discard("")
    equipment_ids = {
        str(e.get("id") or e.get("equipment_id") or "").strip()
        for e in (payload.get("equipment") or [])
        if isinstance(e, dict)
    }
    equipment_ids.discard("")
    rule_ids = known_rule_ids or {
        str(r.get("id") or "").strip() for r in (payload.get("fdd_rules") or []) if isinstance(r, dict)
    }
    rule_ids.discard("")
    for pt in payload.get("points") or []:
        if not isinstance(pt, dict):
            continue
        pid = str(pt.get("id") or "").strip()
        sid = str(pt.get("site_id") or "").strip()
        eid = str(pt.get("equipment_id") or "").strip()
        if sid and sites and sid not in sites:
            issues.append(f"point {pid}: unknown site_id {sid!r}")
        if eid and equipment_ids and eid not in equipment_ids:
            issues.append(f"point {pid}: unknown equipment_id {eid!r}")
        for rid in pt.get("fdd_rule_ids") or []:
            r = str(rid).strip()
            if r and rule_ids and r not in rule_ids:
                issues.append(f"point {pid}: unknown fdd_rule_id {r!r}")
    return {"ok": not issues, "issues": issues}


def apply_commissioning_import(payload: dict[str, Any], *, replace_model: bool = True) -> dict[str, Any]:
    """Import model + merge FDD rule bindings from fdd_rules and/or points[].fdd_rule_ids."""
    from .model_service import ModelService

    model_part = _model_payload_from_commissioning(payload)
    svc = ModelService()
    model_counts = svc.import_json(model_part, replace=replace_model)

    store = RuleStore()
    existing = {str(r.get("id") or ""): r for r in store.list_rules()}
    point_bindings = _bindings_from_points(payload.get("points") or [])
    explicit_rules = payload.get("fdd_rules") if isinstance(payload.get("fdd_rules"), list) else []

    updated = 0
    skipped_unknown = 0
    for entry in explicit_rules:
        if not isinstance(entry, dict):
            continue
        rid = str(entry.get("id") or "").strip()
        if not rid or rid not in existing:
            skipped_unknown += 1
            continue
        rule = dict(existing[rid])
        rule["bindings"] = normalize_bindings(entry.get("bindings"))
        if "enabled" in entry:
            rule["enabled"] = bool(entry.get("enabled"))
        store.upsert(rule, saved_by="commissioning-import")
        existing[rid] = rule
        updated += 1

    for rid, bindings in point_bindings.items():
        if rid not in existing:
            skipped_unknown += 1
            continue
        rule = dict(existing[rid])
        prev = normalize_bindings(rule.get("bindings"))
        merged_points = sorted(set(prev["point_ids"]) | set(bindings["point_ids"]))
        merged_direct = sorted(set(prev["direct_point_ids"]) | set(bindings["direct_point_ids"]))
        rule["bindings"] = normalize_bindings(
            {
                **prev,
                "point_ids": merged_points,
                "direct_point_ids": merged_direct,
            }
        )
        store.upsert(rule, saved_by="commissioning-import")
        existing[rid] = rule
        updated += 1

    bound_points = sum(len(normalize_bindings(r.get("bindings"))["point_ids"]) for r in existing.values())
    return {
        **model_counts,
        "fdd_rules_updated": updated,
        "fdd_rules_skipped_unknown": skipped_unknown,
        "fdd_bound_point_refs": bound_points,
    }
