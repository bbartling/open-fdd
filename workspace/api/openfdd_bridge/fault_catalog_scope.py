"""Scope fault catalog families to BRICK equipment on a site (SPARQL + JSON fallback)."""

from __future__ import annotations

import json
import logging
from typing import Any

from .fault_catalog import FAULT_CATALOG, catalog_tree, family_for_code
from .model_service import ModelService
from .model_sparql import _json_equipment_rows, query_equipment
from .rule_store import RuleStore, _normalize_fault_codes
from .site_defaults import ensure_default_site
from .ttl_graph import TtlGraphError
from .ttl_service import TtlService

_log = logging.getLogger(__name__)

# Catalog families always shown when the site has modeled equipment (site-wide I/O).
_SITE_WIDE_FAMILIES = frozenset({"BUILDING"})


def _norm_type(value: str) -> str:
    return str(value or "").strip().upper().replace("-", "_").replace(" ", "_")


def families_for_equipment(equipment_type: str, name: str = "") -> set[str]:
    """Map one equipment row to zero or more fault-catalog families."""
    et = _norm_type(equipment_type)
    nm = str(name or "").lower()
    found: set[str] = set()

    if any(tok in et for tok in ("AHU", "AIR_HANDLER", "RTU", "DOAS", "MAU", "PACKAGED")) or any(
        tok in nm for tok in (" ahu", "ahu ", "rtu", "doas", "air handler", "air-handler")
    ) or nm.startswith("ahu") or "ahu-" in nm or "ahu_" in nm:
        found.add("AHU")
    if any(tok in et for tok in ("VAV", "VARIABLE_AIR", "TERMINAL", "FCU", "FAN_COIL", "FANCOIL")) or any(
        tok in nm for tok in ("vav", "fan coil", "fan-coil", "fcu", "fan coil unit")
    ):
        found.add("VAV")
    if any(tok in et for tok in ("HEAT_PUMP", "HEATPUMP")) or any(
        tok in nm for tok in ("heat pump", "heatpump", "heat-pump")
    ):
        found.add("HEATPUMP")
    if any(tok in et for tok in ("GEOTHERMAL", "GEO", "GROUND_SOURCE", "GROUND_LOOP")) or "geothermal" in nm:
        found.add("GEO")
    if "CHILLER" in et or "chiller" in nm:
        found.add("CHILLER")
    if any(tok in et for tok in ("CRAC", "CRAH", "DATA_CENTER", "DATACENTER")) or any(
        tok in nm for tok in ("datacenter", "data center", "crah", "crac")
    ):
        found.add("DATACENTER")
    return found


def detect_applicable_families(equipment: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate equipment → catalog families with match detail per family."""
    family_hits: dict[str, list[dict[str, str]]] = {fam: [] for fam in FAULT_CATALOG}
    unmatched: list[dict[str, str]] = []

    for eq in equipment:
        if not isinstance(eq, dict):
            continue
        eid = str(eq.get("equipment_id") or eq.get("id") or "").strip()
        et = str(eq.get("equipment_type") or eq.get("brick_type") or "").strip()
        name = str(eq.get("name") or eq.get("label") or eid).strip()
        matched = families_for_equipment(et, name)
        row = {"equipment_id": eid, "name": name, "equipment_type": et}
        if matched:
            for fam in matched:
                family_hits[fam].append(row)
        elif eid:
            unmatched.append(row)

    applicable = {fam for fam, hits in family_hits.items() if hits}
    if equipment:
        applicable |= _SITE_WIDE_FAMILIES
    hidden = sorted(set(FAULT_CATALOG) - applicable)

    return {
        "applicable_families": sorted(applicable),
        "hidden_families": hidden,
        "family_equipment": {fam: hits for fam, hits in family_hits.items() if hits},
        "unmatched_equipment": unmatched,
        "equipment_count": len(equipment),
    }


def _filter_tree(families: set[str]) -> dict[str, Any]:
    full = catalog_tree()
    shown = [f for f in full["families"] if f["family"] in families]
    hidden = [f["family"] for f in full["families"] if f["family"] not in families]
    return {
        "version": full["version"],
        "families": shown,
        "hidden_families": sorted(hidden),
        "family_count": len(shown),
        "code_count": sum(len(c["codes"]) for fam in shown for c in fam["categories"]),
    }


def _site_equipment(site_id: str, model: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    """Equipment rows for a site; SPARQL preferred, JSON fallback."""
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


def _applicable_rules(rules: list[dict[str, Any]], families: set[str], site_id: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for rule in rules:
        if rule.get("enabled") is False:
            continue
        rule_codes = _normalize_fault_codes(rule)
        if not rule_codes:
            continue
        matched_codes = [c for c in rule_codes if family_for_code(c) in families]
        if not matched_codes:
            continue
        code = matched_codes[0]
        applies = rule.get("applies_to") if isinstance(rule.get("applies_to"), dict) else {}
        site_ids = [str(s) for s in applies.get("site_ids", []) if str(s).strip()]
        if site_ids and site_id and site_id not in site_ids:
            continue
        out.append(
            {
                "rule_id": str(rule.get("id") or ""),
                "rule_name": str(rule.get("name") or ""),
                "fault_code": code,
                "fault_codes": matched_codes,
                "family": family_for_code(code) or "",
                "severity": str(rule.get("severity") or "warning"),
                "enabled": rule.get("enabled") is not False,
            }
        )
    out.sort(key=lambda r: (r["family"], r["fault_code"], r["rule_name"].lower()))
    return out


def build_applicable_payload(site_id: str | None = None) -> dict[str, Any]:
    """Fault catalog tree scoped to BRICK equipment on one site."""
    svc = ModelService()
    ttl = TtlService()
    model = svc.load()
    sid = (site_id or "").strip() or ensure_default_site(svc, ttl)

    equipment, query_engine = _site_equipment(sid, model)
    scope = detect_applicable_families(equipment)
    applicable = set(scope["applicable_families"])
    tree = _filter_tree(applicable)

    rules_raw = RuleStore().load().get("rules") or []
    rules = _applicable_rules(rules_raw if isinstance(rules_raw, list) else [], applicable, sid)

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
        **tree,
    }


def validate_scope_with_ollama(site_id: str | None = None) -> dict[str, Any]:
    """Ask local Ollama to sanity-check family scoping (read-only)."""
    from . import ollama_client

    payload = build_applicable_payload(site_id)
    context = {
        "site_id": payload["site_id"],
        "equipment_count": payload["equipment_count"],
        "equipment_sample": payload["equipment_sample"],
        "applicable_families": payload["applicable_families"],
        "hidden_families": payload["hidden_families"],
        "unmatched_equipment": payload["unmatched_equipment"],
        "assigned_rules": payload["assigned_rules"],
    }
    system = (
        "You validate Open-FDD fault catalog scoping for one building. "
        "Families (AHU, VAV, HEATPUMP, GEO, CHILLER, DATACENTER, BUILDING) map to HVAC equipment types. "
        "VAV family covers VAV boxes and fan coil units (FCU). "
        "Reply with 2–4 short plain sentences: confirm applicable families match equipment, "
        "note any obvious missing family or false positive, and mention if unmatched equipment needs BRICK typing. "
        "Do not invent fault codes."
    )
    user = f"Scope JSON:\n{json.dumps(context, separators=(',', ':'))}\n\nValidation:"
    result = ollama_client.chat(user, system=system, history=[], timeout=60.0)
    return {
        "ok": bool(result.get("ok")),
        "validation": str(result.get("reply") or "").strip(),
        "ollama_error": str(result.get("error") or ""),
        "scope": {
            "site_id": payload["site_id"],
            "applicable_families": payload["applicable_families"],
            "hidden_families": payload["hidden_families"],
        },
    }
