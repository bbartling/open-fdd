"""Scope assigned rules to BRICK equipment on a site (SPARQL + JSON fallback)."""

from __future__ import annotations

import json
import logging
from typing import Any

from .fdd_equipment import equipment_from_rule_bindings, plain_symptom_from_rule_name
from .model_service import ModelService
from .model_sparql import _json_equipment_rows, query_equipment
from .rule_store import RuleStore
from .site_defaults import ensure_default_site
from .ttl_graph import TtlGraphError
from .ttl_service import TtlService

_log = logging.getLogger(__name__)


def _norm_type(value: str) -> str:
    return str(value or "").strip().upper().replace("-", "_").replace(" ", "_")


def families_for_equipment(equipment_type: str, name: str = "") -> set[str]:
    """Legacy hook for equipment typing — returns empty (catalog families removed)."""
    _ = equipment_type, name
    return set()


def detect_applicable_families(equipment: list[dict[str, Any]]) -> dict[str, Any]:
    unmatched: list[dict[str, str]] = []
    for eq in equipment:
        if not isinstance(eq, dict):
            continue
        eid = str(eq.get("equipment_id") or eq.get("id") or "").strip()
        et = str(eq.get("equipment_type") or eq.get("brick_type") or "").strip()
        name = str(eq.get("name") or eq.get("label") or eid).strip()
        if eid:
            unmatched.append({"equipment_id": eid, "name": name, "equipment_type": et})
    return {
        "applicable_families": [],
        "hidden_families": [],
        "family_equipment": {},
        "unmatched_equipment": unmatched,
        "equipment_count": len(equipment),
    }


def _site_equipment(site_id: str, model: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    try:
        rows = query_equipment(site_id, model=model)
        return rows, "sparql"
    except TtlGraphError as err:
        _log.info("fault scope SPARQL fallback for site %s: %s", site_id, err)
        json_rows = [
            r
            for r in _json_equipment_rows(model)
            if not site_id or str(r.get("site_id") or "") in {"", site_id}
        ]
        return json_rows, "json"


def _applicable_rules(
    rules: list[dict[str, Any]],
    site_id: str,
    *,
    model: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    mdl = model or {}
    for rule in rules:
        if rule.get("enabled") is False:
            continue
        applies = rule.get("applies_to") if isinstance(rule.get("applies_to"), dict) else {}
        site_ids = [str(s) for s in applies.get("site_ids", []) if str(s).strip()]
        if site_ids and site_id and site_id not in site_ids:
            continue
        rid = str(rule.get("id") or "")
        device_names, device_ids = equipment_from_rule_bindings(mdl, site_id, rid)
        if not device_names and not device_ids:
            bindings = rule.get("bindings") if isinstance(rule.get("bindings"), dict) else {}
            if not bindings.get("point_ids") and not bindings.get("equipment_ids"):
                continue
        short_desc = str(rule.get("short_description") or rule.get("description") or "").strip()
        if not short_desc:
            short_desc = plain_symptom_from_rule_name(str(rule.get("name") or ""))
        out.append(
            {
                "rule_id": rid,
                "rule_name": str(rule.get("name") or ""),
                "short_description": short_desc,
                "symptom": short_desc,
                "severity": str(rule.get("severity") or "warning"),
                "enabled": rule.get("enabled") is not False,
                "device_names": device_names,
                "device_ids": device_ids,
            }
        )
    out.sort(key=lambda r: (r["short_description"].lower(), r["device_names"][0] if r["device_names"] else ""))
    return out


def build_applicable_payload(site_id: str | None = None) -> dict[str, Any]:
    """Assigned rules scoped to modeled equipment on one site."""
    svc = ModelService()
    ttl = TtlService()
    model = svc.load()
    sid = (site_id or "").strip() or ensure_default_site(svc, ttl)

    equipment, query_engine = _site_equipment(sid, model)
    scope = detect_applicable_families(equipment)

    rules_raw = RuleStore().load().get("rules") or []
    rules = _applicable_rules(rules_raw if isinstance(rules_raw, list) else [], sid, model=model)

    return {
        "ok": True,
        "site_id": sid,
        "model_configured": bool(equipment),
        "query_engine": query_engine,
        "equipment_count": scope["equipment_count"],
        "equipment_sample": equipment[:12],
        "applicable_families": scope["applicable_families"],
        "hidden_families": scope["hidden_families"],
        "family_equipment": scope["family_equipment"],
        "unmatched_equipment": scope["unmatched_equipment"],
        "assigned_rules": rules,
        "version": 3,
        "families": [],
        "hidden_families_catalog": [],
        "family_count": 0,
        "code_count": 0,
    }


def validate_scope_with_ollama(site_id: str | None = None) -> dict[str, Any]:
    from .ollama_client import chat, should_use_ollama_for_insight

    payload = build_applicable_payload(site_id)
    if not should_use_ollama_for_insight():
        return {"ok": False, "ollama_error": "Ollama insight disabled on this host", "scope": payload}
    prompt = (
        "Review assigned FDD rules for this site. Each rule has short_description and device_names. "
        f"JSON:\n{json.dumps({'assigned_rules': payload['assigned_rules'][:12], 'equipment_count': payload['equipment_count']}, indent=2)}"
    )
    try:
        reply = chat([{"role": "user", "content": prompt}], timeout=30.0)
        return {"ok": True, "validation": str(reply.get("message", {}).get("content", "")), "scope": payload}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "ollama_error": str(exc), "scope": payload}
