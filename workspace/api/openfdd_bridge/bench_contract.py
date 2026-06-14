"""Benserver dual-source bench contract — two driver devices, one physical box.

Validates that BACnet MS/TP device 5007 and Niagara station bench9065 appear as
separate BRICK equipment while rules stay data-source agnostic (no driver names
in rule titles).
"""

from __future__ import annotations

import re
from typing import Any

BENCH_SITE_ID = "demo"
BACNET_DEVICE_ID = "bacnet-5007"
NIAGARA_DEVICE_ID = "niagara-bench9065"
BACNET_DEVICE_INSTANCE = 5007
NIAGARA_STATION_ID = "bench9065"

EXPECTED_DRIVER_DEVICES: tuple[str, ...] = (BACNET_DEVICE_ID, NIAGARA_DEVICE_ID)

AGNOSTIC_RULE_IDS: tuple[str, ...] = (
    "temp-out-of-bounds",
    "temp-rate-of-change",
    "humidity-out-of-bounds",
    "humidity-rate-of-change",
)

SOURCE_NAME_RE = re.compile(r"\b(niagara|bacnet|baskstream|ms/?tp)\b", re.I)


def _equipment_rows(model: dict[str, Any]) -> list[dict[str, Any]]:
    return [e for e in model.get("equipment") or [] if isinstance(e, dict)]


def _points_for_equipment(model: dict[str, Any], equipment_id: str) -> list[dict[str, Any]]:
    eid = str(equipment_id or "").strip()
    return [
        p
        for p in model.get("points") or []
        if isinstance(p, dict) and str(p.get("equipment_id") or "") == eid
    ]


def dual_driver_devices(model: dict[str, Any], *, site_id: str = BENCH_SITE_ID) -> dict[str, Any]:
    """Return BACnet + Niagara driver equipment rows (two devices on one bench)."""
    by_id: dict[str, dict[str, Any]] = {}
    for eq in _equipment_rows(model):
        if str(eq.get("site_id") or "") not in {"", site_id}:
            continue
        eid = str(eq.get("id") or "").strip()
        if eid in EXPECTED_DRIVER_DEVICES:
            by_id[eid] = eq
    return {
        "site_id": site_id,
        "expected": list(EXPECTED_DRIVER_DEVICES),
        "found": sorted(by_id),
        "devices": by_id,
        "ok": set(by_id) == set(EXPECTED_DRIVER_DEVICES),
        "bacnet_point_count": len(_points_for_equipment(model, BACNET_DEVICE_ID)),
        "niagara_point_count": len(_points_for_equipment(model, NIAGARA_DEVICE_ID)),
    }


def rule_is_source_agnostic(rule: dict[str, Any]) -> bool:
    """Rule name/short_description must not embed a data source label."""
    for key in ("name", "short_description", "id"):
        text = str(rule.get(key) or "")
        if SOURCE_NAME_RE.search(text):
            return False
    return True


def rules_source_agnostic(rules: list[dict[str, Any]]) -> dict[str, Any]:
    enabled = [r for r in rules if isinstance(r, dict) and r.get("enabled", True)]
    bad = [str(r.get("id") or r.get("name") or "?") for r in enabled if not rule_is_source_agnostic(r)]
    ids = [str(r.get("id") or "") for r in enabled if r.get("id")]
    return {
        "rule_count": len(enabled),
        "rule_ids": ids,
        "non_agnostic": bad,
        "ok": not bad,
        "has_four_bench_rules": set(ids) >= set(AGNOSTIC_RULE_IDS) if len(ids) >= 4 else len(enabled) == 4,
    }


def rule_bindings_span_both_sources(rule: dict[str, Any], model: dict[str, Any]) -> dict[str, Any]:
    """Bound points should reference both BACnet and Niagara equipment when configured."""
    bindings = rule.get("bindings") if isinstance(rule.get("bindings"), dict) else {}
    pids = [str(x) for x in bindings.get("point_ids") or [] if str(x).strip()]
    eq_ids: set[str] = set()
    for pid in pids:
        for pt in model.get("points") or []:
            if isinstance(pt, dict) and str(pt.get("id") or "") == pid:
                eid = str(pt.get("equipment_id") or "").strip()
                if eid:
                    eq_ids.add(eid)
    return {
        "rule_id": str(rule.get("id") or ""),
        "bound_points": len(pids),
        "equipment_ids": sorted(eq_ids),
        "spans_bacnet": BACNET_DEVICE_ID in eq_ids,
        "spans_niagara": NIAGARA_DEVICE_ID in eq_ids,
        "spans_both": BACNET_DEVICE_ID in eq_ids and NIAGARA_DEVICE_ID in eq_ids,
    }


def validate_bench_contract(
    model: dict[str, Any],
    rules: list[dict[str, Any]],
    *,
    site_id: str = BENCH_SITE_ID,
    require_four_rules: bool = True,
) -> dict[str, Any]:
    """Full offline contract check for benserver bench layout."""
    devices = dual_driver_devices(model, site_id=site_id)
    agnostic = rules_source_agnostic(rules)
    binding_reports = [rule_bindings_span_both_sources(r, model) for r in rules if r.get("enabled", True)]
    temp_rules = [b for b in binding_reports if b["rule_id"].startswith("temp")]
    humidity_rules = [b for b in binding_reports if b["rule_id"].startswith("humidity")]
    bindings_ok = all(b["spans_both"] for b in binding_reports) if binding_reports else False

    issues: list[str] = []
    if not devices["ok"]:
        missing = set(EXPECTED_DRIVER_DEVICES) - set(devices["found"])
        issues.append(f"missing driver equipment: {sorted(missing)}")
    if devices["bacnet_point_count"] < 1:
        issues.append("bacnet-5007 has no points in model")
    if devices["niagara_point_count"] < 1:
        issues.append("niagara-bench9065 has no points in model")
    if not agnostic["ok"]:
        issues.append(f"rules mention data source: {agnostic['non_agnostic']}")
    if require_four_rules and not agnostic["has_four_bench_rules"]:
        issues.append(f"expected 4 bench rules, got {agnostic['rule_ids']}")
    if binding_reports and not bindings_ok:
        thin = [b["rule_id"] for b in binding_reports if not b["spans_both"]]
        issues.append(f"rules not bound to both sources: {thin}")

    return {
        "ok": not issues,
        "issues": issues,
        "devices": devices,
        "rules": agnostic,
        "bindings": binding_reports,
        "temp_rules_dual_source": all(b["spans_both"] for b in temp_rules) if temp_rules else None,
        "humidity_rules_dual_source": all(b["spans_both"] for b in humidity_rules) if humidity_rules else None,
    }
