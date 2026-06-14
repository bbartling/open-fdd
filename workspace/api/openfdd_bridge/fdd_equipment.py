"""Map historian columns and FDD runs to BRICK equipment labels for operator alerts."""

from __future__ import annotations


from typing import Any

from .timeseries_api import historian_column_candidates, plot_column_name

_RULE_STORE_CACHE: dict[str, Any] | None = None


def _equipment_index(model: dict[str, Any], site_id: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for eq in model.get("equipment") or []:
        if not isinstance(eq, dict):
            continue
        if str(eq.get("site_id") or "") not in {"", site_id}:
            continue
        eid = str(eq.get("id") or "").strip()
        if eid:
            out[eid] = eq
    return out


def _point_index(model: dict[str, Any], site_id: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for pt in model.get("points") or []:
        if not isinstance(pt, dict) or str(pt.get("site_id") or "") not in {"", site_id}:
            continue
        pid = str(pt.get("id") or "").strip()
        if pid:
            out[pid] = pt
    return out


def _rules_by_id() -> dict[str, dict[str, Any]]:
    global _RULE_STORE_CACHE
    if _RULE_STORE_CACHE is None:
        try:
            from .rule_store import RuleStore

            raw = RuleStore().load().get("rules") or []
            _RULE_STORE_CACHE = {
                str(r.get("id") or ""): r for r in raw if isinstance(r, dict) and r.get("id")
            }
        except Exception:
            _RULE_STORE_CACHE = {}
    return _RULE_STORE_CACHE


def plain_symptom_from_rule_name(rule_name: str) -> str:
    """Source-agnostic symptom label (strip Niagara/BACnet bench prefixes)."""
    name = str(rule_name or "").strip()
    for prefix in ("Niagara Bench ", "Niagara ", "Bench "):
        if name.startswith(prefix):
            name = name[len(prefix) :]
    return name or str(rule_name or "Fault")


def data_source_label(eq: dict[str, Any] | None) -> str:
    """Short driver badge: BACnet device 5007 / Niagara bench9065."""
    if not eq:
        return ""
    meta = eq.get("metadata") if isinstance(eq.get("metadata"), dict) else {}
    src = str(meta.get("source") or "").strip().lower()
    eid = str(eq.get("id") or "").strip().lower()
    if src == "bacnet_direct" or eq.get("bacnet_device_id") is not None:
        dev = eq.get("bacnet_device_id") or eq.get("bacnet_device_instance")
        return f"BACnet · {dev}" if dev is not None else "BACnet"
    if src == "niagara_baskstream" or eid.startswith("niagara-"):
        station = str(meta.get("station_id") or "").strip()
        if not station and eid.startswith("niagara-"):
            station = eid.replace("niagara-", "", 1)
        return f"Niagara · {station}" if station else "Niagara"
    driver = str(meta.get("driver") or "").strip()
    if driver:
        return driver.replace("_", " ")
    return ""


def equipment_from_rule_bindings(
    model: dict[str, Any],
    site_id: str,
    rule_id: str,
) -> tuple[list[str], list[str]]:
    """Resolve equipment names/ids from Rule Lab point bindings."""
    rule = _rules_by_id().get(str(rule_id or "").strip())
    if not rule:
        return [], []
    bindings = rule.get("bindings") if isinstance(rule.get("bindings"), dict) else {}
    point_ids = bindings.get("point_ids") or bindings.get("direct_point_ids") or []
    equipment_ids = bindings.get("equipment_ids") or []
    eq_index = _equipment_index(model, site_id)
    pt_index = _point_index(model, site_id)

    ids: list[str] = []
    for raw in equipment_ids:
        eid = str(raw or "").strip()
        if eid and eid not in ids:
            ids.append(eid)
    for raw in point_ids:
        pid = str(raw or "").strip()
        pt = pt_index.get(pid) or {}
        eid = str(pt.get("equipment_id") or "").strip()
        if eid and eid not in ids:
            ids.append(eid)

    names: list[str] = []
    for eid in ids:
        eq = eq_index.get(eid) or {}
        label = str(eq.get("name") or eid).strip()
        if label and label not in names:
            names.append(label)
    return names, ids


def bound_point_ids_for_rule(rule_id: str) -> list[str]:
    rule = _rules_by_id().get(str(rule_id or "").strip())
    if not rule:
        return []
    bindings = rule.get("bindings") if isinstance(rule.get("bindings"), dict) else {}
    return [str(p) for p in bindings.get("point_ids") or bindings.get("direct_point_ids") or [] if str(p).strip()]


def column_to_equipment_map(model: dict[str, Any], site_id: str) -> dict[str, dict[str, str]]:
    """Historian column -> {equipment_id, equipment_name}."""
    eq_index = _equipment_index(model, site_id)
    mapping: dict[str, dict[str, str]] = {}
    for pt in model.get("points") or []:
        if not isinstance(pt, dict) or str(pt.get("site_id") or "") not in {"", site_id}:
            continue
        eid = str(pt.get("equipment_id") or "").strip()
        eq = eq_index.get(eid) or {}
        name = str(eq.get("name") or eid or "").strip()
        for col in historian_column_candidates(pt):
            if col and col not in mapping:
                mapping[col] = {"equipment_id": eid, "equipment_name": name}
        col = plot_column_name(pt)
        if col and col not in mapping:
            mapping[col] = {"equipment_id": eid, "equipment_name": name}
    return mapping


def equipment_labels_for_columns(
    model: dict[str, Any],
    site_id: str,
    columns: list[str] | None,
) -> list[str]:
    """Unique BAS equipment names for historian columns (preserves order)."""
    if not columns:
        return []
    col_map = column_to_equipment_map(model, site_id)
    seen: set[str] = set()
    out: list[str] = []
    for col in columns:
        key = str(col or "").strip()
        if not key:
            continue
        name = str((col_map.get(key) or {}).get("equipment_name") or "").strip()
        if name and name not in seen:
            seen.add(name)
            out.append(name)
    return out


def enrich_fdd_run_with_equipment(
    run: dict[str, Any],
    model: dict[str, Any],
    site_id: str,
) -> dict[str, Any]:
    """Attach equipment_names / equipment_id from historian columns or rule bindings."""
    analytics = run.get("analytics") if isinstance(run.get("analytics"), dict) else {}
    cols = analytics.get("flagged_columns") or analytics.get("value_columns") or []
    if not cols and run.get("bound_columns"):
        cols = run.get("flagged_columns") or []
    if isinstance(cols, int):
        cols = []
    col_map = column_to_equipment_map(model, site_id)
    names = equipment_labels_for_columns(model, site_id, list(cols) if cols else None)
    ids: list[str] = []
    for col in cols:
        eid = str((col_map.get(str(col)) or {}).get("equipment_id") or "").strip()
        if eid and eid not in ids:
            ids.append(eid)
    if not names and not ids:
        names, ids = equipment_from_rule_bindings(model, site_id, str(run.get("rule_id") or ""))
    if not names and ids:
        eq_index = _equipment_index(model, site_id)
        for eid in ids:
            eq = eq_index.get(eid) or {}
            label = str(eq.get("name") or eid).strip()
            if label and label not in names:
                names.append(label)
    eq_index = _equipment_index(model, site_id)
    data_source = ""
    if ids:
        data_source = data_source_label(eq_index.get(ids[0]))
    run = dict(run)
    if names:
        run["equipment_names"] = names
    if ids:
        run["equipment_id"] = ids[0]
        run["equipment_ids"] = ids
        run.setdefault("equipment_name", names[0] if names else None)
        if data_source:
            run["data_source"] = data_source
    elif names:
        run["equipment_name"] = names[0]
    run["symptom"] = str(run.get("short_description") or "").strip() or plain_symptom_from_rule_name(
        str(run.get("rule_name") or "")
    )
    return run
