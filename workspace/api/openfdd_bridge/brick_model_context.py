"""BRICK model + fault-catalog context for Ollama (building insight + agent tools).

Keeps SPARQL/graph payloads small but interlinks equipment feeds, sensors, fault
codes, and REST/tool paths operators can use to drill down.
"""

from __future__ import annotations

import json
from typing import Any

from .fault_catalog import CATEGORIES, entry_for_code
from .model_service import ModelService
from .site_defaults import ensure_default_site
from .ttl_service import TtlService


def catalog_entries_for_codes(codes: list[str], *, limit: int = 8) -> list[dict[str, Any]]:
    """Full catalog semantics for active fault codes (title, category, checks)."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in codes:
        code = str(raw or "").strip().upper()
        if not code or code in seen:
            continue
        seen.add(code)
        entry = entry_for_code(code)
        if not entry:
            continue
        cat = CATEGORIES.get(str(entry.get("category") or ""), {})
        out.append(
            {
                "code": code,
                "family": entry.get("family"),
                "title": entry.get("title"),
                "category": entry.get("category"),
                "category_label": cat.get("label"),
                "severity": entry.get("severity"),
                "description": str(entry.get("description") or "")[:320],
                "likely_causes": (entry.get("likely_causes") or [])[:4],
                "suggested_checks": (entry.get("suggested_checks") or [])[:4],
                "cookbook_patterns": (entry.get("cookbook_patterns") or [])[:3],
            }
        )
        if len(out) >= limit:
            break
    return out


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


def _feeds_to_chains(feeds: list[dict[str, Any]], *, limit: int = 16) -> list[str]:
    chains: list[str] = []
    for edge in feeds[:limit]:
        if not isinstance(edge, dict):
            continue
        src = str(edge.get("from_label") or edge.get("from_equipment_id") or "")
        dst = str(edge.get("to_label") or edge.get("to_equipment_id") or "")
        if src and dst:
            chains.append(f"{src} → feeds → {dst}")
    return chains


def _point_counts_by_brick(points_by_equipment: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for pts in points_by_equipment.values():
        for pt in pts or []:
            if not isinstance(pt, dict):
                continue
            bt = str(pt.get("brick_type") or "Point").strip() or "Point"
            counts[bt] = counts.get(bt, 0) + 1
    return dict(sorted(counts.items(), key=lambda x: -x[1])[:12])


def slim_brick_graph(
    site_id: str | None = None,
    *,
    max_equipment: int = 24,
    max_feeds: int = 20,
    max_points_per_equipment: int = 8,
) -> dict[str, Any]:
    """Compact BRICK site graph for LLM context (SPARQL when TTL is synced)."""
    svc = ModelService()
    ttl = TtlService()
    sid = (site_id or "").strip() or ensure_default_site(svc, ttl)
    model = svc.load()
    eq_index = _equipment_index(model, sid)

    try:
        from .model_sparql import query_model_graph

        graph = query_model_graph(sid)
        equipment = (graph.get("equipment") or [])[:max_equipment]
        feeds = (graph.get("feeds") or [])[:max_feeds]
        pbe = graph.get("points_by_equipment") or {}
        equipment_slim = [
            {
                "equipment_id": e.get("equipment_id"),
                "name": e.get("name"),
                "equipment_type": e.get("equipment_type") or e.get("brick_type"),
                "bacnet_device_instance": e.get("bacnet_device_instance"),
            }
            for e in equipment
            if isinstance(e, dict)
        ]
        points_by_eq: dict[str, list[dict[str, Any]]] = {}
        for eid, pts in pbe.items():
            if not isinstance(pts, list):
                continue
            points_by_eq[str(eid)] = [
                {
                    "point_id": p.get("point_id"),
                    "name": p.get("name"),
                    "brick_type": p.get("brick_type"),
                    "column": p.get("column") or p.get("external_id"),
                }
                for p in pts[:max_points_per_equipment]
                if isinstance(p, dict)
            ]
        return {
            "site_id": sid,
            "query_engine": graph.get("query_engine") or "sparql",
            "equipment_count": len(graph.get("equipment") or []),
            "feed_edge_count": len(graph.get("feeds") or []),
            "equipment": equipment_slim,
            "feeds_chains": _feeds_to_chains(feeds, limit=max_feeds),
            "points_by_brick_type": _point_counts_by_brick(pbe),
            "points_by_equipment": points_by_eq,
        }
    except Exception as exc:  # noqa: BLE001 — insight must not fail on TTL
        equipment_json = [
            {
                "equipment_id": eq.get("id"),
                "name": eq.get("name"),
                "equipment_type": eq.get("equipment_type"),
            }
            for eq in list(eq_index.values())[:max_equipment]
        ]
        return {
            "site_id": sid,
            "query_engine": "model_json_fallback",
            "equipment_count": len(eq_index),
            "warning": str(exc)[:200],
            "equipment": equipment_json,
            "feeds_chains": [],
            "points_by_brick_type": {},
            "note": "Sync TTL on Data Model tab (POST /api/model/sync-ttl) for brick:feeds SPARQL graph.",
        }


def link_faults_to_brick(
    alerts: list[dict[str, Any]],
    *,
    site_id: str | None = None,
) -> list[dict[str, Any]]:
    """Attach BRICK equipment names to fault alerts when equipment_id is present."""
    svc = ModelService()
    sid = (site_id or "").strip()
    if not sid:
        try:
            sid = ensure_default_site(svc, TtlService())
        except Exception:
            return []
    eq_index = _equipment_index(svc.load(), sid)
    linked: list[dict[str, Any]] = []
    for alert in alerts[:12]:
        if not isinstance(alert, dict):
            continue
        eid = str(alert.get("equipment_id") or "").strip()
        eq = eq_index.get(eid) or {}
        linked.append(
            {
                "code": alert.get("code"),
                "title": alert.get("title"),
                "severity": alert.get("severity"),
                "equipment_id": eid or None,
                "equipment_name": eq.get("name") if eid else None,
                "equipment_type": eq.get("equipment_type") if eid else None,
            }
        )
    return linked


def api_query_guide() -> dict[str, Any]:
    """REST + agent tool map for local Ollama (same bridge, Bearer auth)."""
    return {
        "auth": "Bearer token from POST /api/auth/login",
        "brick_model": {
            "GET /api/model/graph?site_id=": "equipment, brick:feeds, points_by_equipment (SPARQL)",
            "GET /api/model/scope?site_id=&equipment_id=": "sensors + historian column names for one equipment",
            "GET /api/model/tree": "full BRICK catalog (all sites)",
            "GET /api/model/health": "model score + TTL status",
            "POST /api/model/sync-ttl": "refresh data_model.ttl from model.json",
        },
        "historian": {
            "GET /api/timeseries/readings?site_id=&columns=&hours=": "feather poll trends + optional FDD overlay",
            "GET /api/timeseries/series?site_id=": "plottable column list grouped by equipment",
        },
        "faults": {
            "GET /api/faults/catalog": "fixed fault code definitions (VAV-C, AHU-B, …)",
            "GET /api/faults/tree": "catalog by family/category",
            "GET /api/building/status": "active alerts + traffic light",
        },
        "agent_read_tools": [
            "model.graph",
            "model.scope",
            "timeseries.snapshot",
            "faults.lookup",
            "building.zone_temps",
            "building.device_health",
            "building.operational_brief",
        ],
        "agent_write_tools_note": "model.add_*, rules.save, building.set_alerts require integrator/agent role",
        "insight": {
            "GET /openfdd-agent/building-insight": "cached operator briefing (this page)",
            "GET /openfdd-agent/operational-brief": "full JSON analytics bundle",
        },
    }


def build_insight_brick_payload(
    status: dict[str, Any],
    *,
    site_id: str | None = None,
) -> dict[str, Any]:
    alerts = [a for a in (status.get("alerts") or []) if isinstance(a, dict)]
    codes = [str(a.get("code") or "").strip() for a in alerts if a.get("code")]
    brick = slim_brick_graph(site_id)
    return {
        "brick_model": brick,
        "fault_catalog": catalog_entries_for_codes(codes),
        "faults_linked": link_faults_to_brick(alerts, site_id=brick.get("site_id")),
        "api_query_guide": api_query_guide(),
    }


def build_agent_system_extra(*, site_id: str | None = None) -> str:
    """Extra system-prompt block for /openfdd-agent/chat (compact JSON)."""
    try:
        alerts: list[dict[str, Any]] = []
        traffic = None
        fdd_count = 0
        try:
            from .building_status import collect_status

            status = collect_status()
            alerts = [a for a in (status.get("alerts") or []) if isinstance(a, dict)]
            traffic = status.get("traffic")
            fdd_count = int(status.get("fdd_alert_count") or 0)
        except Exception:  # noqa: BLE001
            pass
        codes = [str(a.get("code") or "").strip() for a in alerts if a.get("code")]
        brick = slim_brick_graph(site_id, max_equipment=16, max_feeds=14)
        payload = {
            "building_traffic": traffic,
            "fdd_alert_count": fdd_count,
            "fault_catalog_active": catalog_entries_for_codes(codes, limit=6),
            "faults_linked": link_faults_to_brick(alerts, site_id=brick.get("site_id") or site_id)[:6],
            "brick_model": brick,
            "api_query_guide": api_query_guide(),
            "tool_usage": (
                "You cannot call HTTP yourself from this chat unless the operator runs tools. "
                "Tell the operator to use POST /openfdd-agent/tool with tools listed in "
                "api_query_guide.agent_read_tools, or cite GET paths for integrators. "
                "Interlink faults to brick_model equipment and feeds_chains."
            ),
        }
        text = json.dumps(payload, separators=(",", ":"))
        if len(text) > 6000:
            payload["brick_model"] = {
                "site_id": payload["brick_model"].get("site_id"),
                "equipment_count": payload["brick_model"].get("equipment_count"),
                "feeds_chains": (payload["brick_model"].get("feeds_chains") or [])[:8],
                "warning": "truncated for token budget",
            }
            text = json.dumps(payload, separators=(",", ":"))
        return (
            "Live Open-FDD snapshot (BRICK + faults + API map). "
            "Explain fault codes using fault_catalog_active; tie equipment to feeds_chains.\n"
            f"{text}"
        )
    except Exception as exc:  # noqa: BLE001 — never block chat on context build
        guide = api_query_guide()
        return (
            "Open-FDD operator assistant. BRICK snapshot unavailable; use agent read tools "
            f"(model.graph, timeseries.snapshot, faults.lookup). Error: {str(exc)[:120]}\n"
            f"{json.dumps({'api_query_guide': guide}, separators=(',', ':'))}"
        )
