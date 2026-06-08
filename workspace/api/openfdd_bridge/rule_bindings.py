"""Shared rule binding merge/unbind logic for REST, agent tools, and assignments API."""

from __future__ import annotations

from typing import Any, Literal

BindKind = Literal["point", "equipment", "brick_type"]
BindOp = Literal["add", "remove"]


def normalize_bindings(raw: dict[str, Any] | None) -> dict[str, list[str]]:
    raw = raw if isinstance(raw, dict) else {}
    point_ids = [str(x) for x in raw.get("point_ids") or [] if str(x).strip()]
    direct = raw.get("direct_point_ids")
    if direct is None:
        direct_point_ids = list(point_ids)
    else:
        direct_point_ids = [str(x) for x in direct if str(x).strip()]
    return {
        "point_ids": point_ids,
        "direct_point_ids": direct_point_ids,
        "equipment_ids": [str(x) for x in raw.get("equipment_ids") or [] if str(x).strip()],
        "brick_types": [str(x) for x in raw.get("brick_types") or [] if str(x).strip()],
    }


def merge_bind(
    prev: dict[str, Any] | None,
    kind: BindKind,
    target_id: str,
    extra_point_ids: list[str] | None = None,
) -> dict[str, list[str]]:
    next_b = normalize_bindings(prev)
    tid = str(target_id).strip()
    if kind == "point" and tid:
        if tid not in next_b["point_ids"]:
            next_b["point_ids"].append(tid)
        if tid not in next_b["direct_point_ids"]:
            next_b["direct_point_ids"].append(tid)
    if kind == "equipment" and tid and tid not in next_b["equipment_ids"]:
        next_b["equipment_ids"].append(tid)
    if kind == "brick_type" and tid and tid not in next_b["brick_types"]:
        next_b["brick_types"].append(tid)
    for pid in extra_point_ids or []:
        p = str(pid).strip()
        if p and p not in next_b["point_ids"]:
            next_b["point_ids"].append(p)
    return next_b


def unbind_target(
    prev: dict[str, Any] | None,
    *,
    kind: BindKind,
    target_id: str,
    point_ids: list[str] | None = None,
) -> dict[str, list[str]]:
    next_b = normalize_bindings(prev)
    tid = str(target_id).strip()
    direct = set(next_b["direct_point_ids"])
    if kind == "point" and tid:
        next_b["point_ids"] = [x for x in next_b["point_ids"] if x != tid]
        next_b["direct_point_ids"] = [x for x in next_b["direct_point_ids"] if x != tid]
    elif kind == "equipment" and tid:
        next_b["equipment_ids"] = [x for x in next_b["equipment_ids"] if x != tid]
        drop = {str(x) for x in point_ids or [] if str(x).strip()}
        if drop:
            next_b["point_ids"] = [x for x in next_b["point_ids"] if x not in drop or x in direct]
    elif kind == "brick_type" and tid:
        next_b["brick_types"] = [x for x in next_b["brick_types"] if x != tid]
        drop = {str(x) for x in point_ids or [] if str(x).strip()}
        if drop:
            next_b["point_ids"] = [x for x in next_b["point_ids"] if x not in drop or x in direct]
    return next_b


def apply_bind_op(
    rule: dict[str, Any],
    *,
    op: BindOp,
    kind: BindKind,
    target_id: str,
    point_ids: list[str] | None = None,
) -> dict[str, list[str]]:
    if op == "add":
        return merge_bind(rule.get("bindings"), kind, target_id, point_ids)
    return unbind_target(
        rule.get("bindings"),
        kind=kind,
        target_id=target_id,
        point_ids=point_ids,
    )


def rule_binds_target(rule: dict[str, Any], *, kind: BindKind, target_id: str) -> bool:
    b = normalize_bindings(rule.get("bindings"))
    tid = str(target_id).strip()
    if kind == "point":
        return tid in b["point_ids"]
    if kind == "equipment":
        return tid in b["equipment_ids"]
    return tid in b["brick_types"]


def build_assignment_rows(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for rule in rules:
        if rule.get("enabled") is False:
            continue
        b = normalize_bindings(rule.get("bindings"))
        if not b["point_ids"] and not b["equipment_ids"] and not b["brick_types"]:
            continue
        rows.append(
            {
                "rule_id": str(rule.get("id") or ""),
                "rule_name": str(rule.get("name") or ""),
                "severity": str(rule.get("severity") or "warning"),
                "point_ids": b["point_ids"],
                "equipment_ids": b["equipment_ids"],
                "brick_types": b["brick_types"],
                "point_count": len(b["point_ids"]),
                "equipment_count": len(b["equipment_ids"]),
                "brick_count": len(b["brick_types"]),
            }
        )
    rows.sort(key=lambda r: str(r.get("rule_name") or "").lower())
    return rows


def _point_label(pt: dict[str, Any]) -> str:
    return str(pt.get("name") or pt.get("description") or pt.get("external_id") or pt.get("id") or "")


def _equipment_label(eq: dict[str, Any]) -> str:
    return str(eq.get("name") or eq.get("id") or "")


def build_assignments_view(model: dict[str, Any], rules: list[dict[str, Any]], *, site_id: str | None = None) -> dict[str, Any]:
    """Enriched assignments payload for UI and agent context."""
    from .model_point_utils import point_site_id

    sid = str(site_id or "").strip()
    equipment = [e for e in model.get("equipment") or [] if isinstance(e, dict)]
    points = [p for p in model.get("points") or [] if isinstance(p, dict)]
    if sid:
        equipment = [
            e
            for e in equipment
            if str(e.get("site_id") or "").strip() in {"", sid}
        ]
        points = [p for p in points if point_site_id(p, model) == sid]

    eq_by_id = {str(e.get("id") or ""): e for e in equipment if str(e.get("id") or "")}

    bound_by_point: dict[str, list[dict[str, str]]] = {}
    for rule in rules:
        if rule.get("enabled") is False:
            continue
        rid = str(rule.get("id") or "")
        rname = str(rule.get("name") or rid)
        b = normalize_bindings(rule.get("bindings"))
        for pid in b["point_ids"]:
            bound_by_point.setdefault(pid, []).append({"rule_id": rid, "rule_name": rname})

    device_map: dict[str, dict[str, Any]] = {}
    point_rows: list[dict[str, Any]] = []
    for pt in points:
        pid = str(pt.get("id") or "").strip()
        if not pid:
            continue
        dev = pt.get("bacnet_device_id")
        addr = str(pt.get("bacnet_device_address") or "").strip()
        dev_key = f"{dev}@{addr}" if dev is not None and addr else (str(dev) if dev is not None else "_local")
        if dev_key not in device_map:
            label = f"Device {dev}" if dev is not None else "Local points"
            if addr:
                label = f"{label} @ {addr}"
            device_map[dev_key] = {
                "device_key": dev_key,
                "bacnet_device_id": dev,
                "bacnet_device_address": addr or None,
                "label": label,
            }
        eid = str(pt.get("equipment_id") or "")
        eq = eq_by_id.get(eid, {})
        point_rows.append(
            {
                "point_id": pid,
                "name": _point_label(pt),
                "object_identifier": str(pt.get("object_identifier") or ""),
                "unit": str(pt.get("unit") or ""),
                "brick_type": str(pt.get("brick_type") or ""),
                "equipment_id": eid,
                "equipment_name": _equipment_label(eq) if eq else eid,
                "bacnet_device_id": dev,
                "bacnet_device_address": addr or None,
                "device_key": dev_key,
                "bound_rules": bound_by_point.get(pid, []),
            }
        )

    devices = sorted(device_map.values(), key=lambda d: str(d.get("label") or ""))
    for d in devices:
        key = str(d["device_key"])
        d["point_ids"] = [p["point_id"] for p in point_rows if p["device_key"] == key]
        d["point_count"] = len(d["point_ids"])

    point_rows.sort(key=lambda p: str(p.get("name") or "").lower())

    return {
        "site_id": sid or None,
        "assignment_rows": build_assignment_rows(rules),
        "devices": devices,
        "points": point_rows,
        "rules": rules,
    }
