"""BRICK scope queries over synced TTL (rdflib SPARQL) with model.json fallback."""

from __future__ import annotations

import logging
import re
from typing import Any

from .model_service import ModelService
from .timeseries_api import plot_column_name
from .ttl_service import TtlService, _sanitize_local_name

_log = logging.getLogger(__name__)

DEMO_SITE_IDS = frozenset({"demo", "site", "test", "sample", "default"})

EQUIPMENT_QUERY = """
PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX ofdd: <http://openfdd.local/ontology#>
SELECT ?eq ?label ?eqType ?bacnetInst WHERE {{
  ?eq a ?eqType .
  ?eq brick:isPartOf :site_{site} .
  ?eq rdfs:label ?label .
  OPTIONAL {{ ?eq ofdd:bacnetDeviceInstance ?bacnetInst }}
  FILTER(STRSTARTS(STR(?eqType), "https://brickschema.org/schema/Brick#"))
}}
ORDER BY ?label
"""

SENSORS_QUERY = """
PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX ofdd: <http://openfdd.local/ontology#>
SELECT ?pt ?label ?brickType ?ruleInput ?seriesId ?tsCol WHERE {{
  ?pt a ?brickType .
  ?pt brick:isPointOf :eq_{equipment} .
  ?pt rdfs:label ?label .
  OPTIONAL {{ ?pt ofdd:mapsToRuleInput ?ruleInput }}
  OPTIONAL {{ ?pt ofdd:seriesId ?seriesId }}
  OPTIONAL {{ ?pt ofdd:timeseriesColumn ?tsCol }}
  FILTER(STRSTARTS(STR(?brickType), "https://brickschema.org/schema/Brick#"))
}}
ORDER BY ?label
"""

FEEDS_QUERY = """
PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?fromEq ?toEq ?fromLabel ?toLabel WHERE {{
  ?fromEq brick:feeds ?toEq .
  ?fromEq brick:isPartOf :site_{site} .
  ?toEq brick:isPartOf :site_{site} .
  OPTIONAL {{ ?fromEq rdfs:label ?fromLabel }}
  OPTIONAL {{ ?toEq rdfs:label ?toLabel }}
}}
"""


def _is_demo_site(site_id: str) -> bool:
    return str(site_id or "").strip().lower() in DEMO_SITE_IDS


def list_model_sites(model: dict[str, Any] | None = None) -> list[dict[str, str]]:
    model = model if model is not None else ModelService().load()
    out: list[dict[str, str]] = []
    for row in model.get("sites") or []:
        if not isinstance(row, dict):
            continue
        sid = str(row.get("id") or "").strip()
        if not sid or _is_demo_site(sid):
            continue
        out.append({"site_id": sid, "name": str(row.get("name") or sid)})
    return sorted(out, key=lambda r: r["name"].lower())


def _equipment_from_json(model: dict[str, Any], site_id: str) -> list[dict[str, Any]]:
    sid = str(site_id).strip()
    rows: list[dict[str, Any]] = []
    for eq in model.get("equipment") or []:
        if not isinstance(eq, dict) or str(eq.get("site_id") or "").strip() != sid:
            continue
        eid = str(eq.get("id") or "").strip()
        if not eid:
            continue
        inst = eq.get("bacnet_device_instance")
        if inst is None:
            inst = eq.get("bacnet_device_id")
        name = str(eq.get("name") or eid)
        rows.append(
            {
                "equipment_id": eid,
                "name": name,
                "label": name,
                "equipment_type": str(eq.get("equipment_type") or eq.get("brick_type") or ""),
                "bacnet_device_instance": int(inst) if inst is not None and str(inst).isdigit() else inst,
            }
        )
    rows.sort(key=lambda r: (_bacnet_sort_key(r.get("bacnet_device_instance")), r["name"].lower()))
    return rows


def _bacnet_sort_key(inst: Any) -> int:
    try:
        return int(inst)
    except (TypeError, ValueError):
        return 999_999


def _sparql_available() -> bool:
    try:
        import rdflib  # noqa: F401

        return True
    except ImportError:
        return False


def _sensors_from_json(model: dict[str, Any], site_id: str, equipment_id: str) -> list[dict[str, Any]]:
    eid = str(equipment_id).strip()
    rows: list[dict[str, Any]] = []
    for pt in model.get("points") or []:
        if not isinstance(pt, dict):
            continue
        ps = str(pt.get("site_id") or "").strip()
        if ps and ps != str(site_id).strip():
            continue
        if str(pt.get("equipment_id") or "").strip() != eid:
            continue
        pid = str(pt.get("id") or "").strip()
        if not pid:
            continue
        col = plot_column_name(pt)
        name = str(pt.get("name") or pt.get("description") or col or pid)
        rows.append(
            {
                "point_id": pid,
                "name": name,
                "label": name,
                "brick_type": str(pt.get("brick_type") or ""),
                "timeseries_column": col,
                "fdd_input": str(pt.get("fdd_input") or ""),
                "series_id": str(pt.get("series_id") or pt.get("metadata", {}).get("series_id") or ""),
            }
        )
    rows.sort(key=lambda r: r["name"].lower())
    return rows


def _run_sparql(ttl_text: str, query: str) -> list[dict[str, str]]:
    try:
        from rdflib import Graph
        from rdflib.query import ResultRow
    except ImportError:
        return []

    g = Graph()
    g.parse(data=ttl_text, format="turtle")
    out: list[dict[str, str]] = []
    for row in g.query(query):
        if not isinstance(row, ResultRow):
            continue
        item: dict[str, str] = {}
        for key in row.labels:
            val = row[key]
            item[str(key)] = str(val) if val is not None else ""
        out.append(item)
    return out


def _local_name(uri: str, prefix: str) -> str:
    text = str(uri or "")
    if f":{prefix}_" in text:
        return text.rsplit(f":{prefix}_", 1)[-1].split('"')[0].split()[0]
    m = re.search(rf"{prefix}_([A-Za-z0-9_]+)", text)
    return m.group(1) if m else ""


def query_equipment(site_id: str, *, model: dict[str, Any] | None = None, ttl: TtlService | None = None) -> list[dict[str, Any]]:
    site = _sanitize_local_name(site_id)
    if site is None:
        return []
    model = model if model is not None else ModelService().load()
    ttl_svc = ttl or TtlService()
    ttl_text = ttl_svc.build_ttl()
    q = EQUIPMENT_QUERY.format(site=site)
    sparql_rows = _run_sparql(ttl_text, q)
    if not sparql_rows:
        return _equipment_from_json(model, site_id)

    json_eq = {e["equipment_id"]: e for e in _equipment_from_json(model, site_id)}
    out: list[dict[str, Any]] = []
    for row in sparql_rows:
        eid = _local_name(row.get("eq", ""), "eq")
        if not eid:
            continue
        meta = json_eq.get(eid, {})
        inst = row.get("bacnetInst") or meta.get("bacnet_device_instance")
        name = row.get("label") or meta.get("name") or eid
        eq_type = row.get("eqType", "")
        if "#" in eq_type:
            eq_type = eq_type.rsplit("#", 1)[-1]
        out.append(
            {
                "equipment_id": eid,
                "name": name,
                "label": name,
                "equipment_type": eq_type or meta.get("equipment_type", ""),
                "bacnet_device_instance": int(inst) if inst and str(inst).isdigit() else inst,
            }
        )
    if not out:
        return _equipment_from_json(model, site_id)
    out.sort(key=lambda r: (_bacnet_sort_key(r.get("bacnet_device_instance")), r["name"].lower()))
    return out


def query_sensors(
    site_id: str,
    equipment_id: str,
    *,
    brick_type: str | None = None,
    model: dict[str, Any] | None = None,
    ttl: TtlService | None = None,
) -> list[dict[str, Any]]:
    eq = _sanitize_local_name(equipment_id)
    if eq is None:
        return []
    model = model if model is not None else ModelService().load()
    ttl_svc = ttl or TtlService()
    ttl_text = ttl_svc.build_ttl()
    q = SENSORS_QUERY.format(equipment=eq)
    sparql_rows = _run_sparql(ttl_text, q)
    json_rows = _sensors_from_json(model, site_id, equipment_id)
    json_by_id = {r["point_id"]: r for r in json_rows}

    if sparql_rows:
        out: list[dict[str, Any]] = []
        for row in sparql_rows:
            pid = _local_name(row.get("pt", ""), "pt")
            if not pid:
                continue
            meta = json_by_id.get(pid, {})
            brick = row.get("brickType", "")
            if "#" in brick:
                brick = brick.rsplit("#", 1)[-1]
            col = (
                meta.get("timeseries_column")
                or str(row.get("tsCol") or "").strip()
                or str(row.get("label") or pid)
            )
            name = meta.get("name") or col
            item = {
                "point_id": pid,
                "name": name,
                "label": name,
                "brick_type": brick or meta.get("brick_type", ""),
                "timeseries_column": col,
                "fdd_input": meta.get("fdd_input") or str(row.get("ruleInput") or ""),
                "series_id": meta.get("series_id") or str(row.get("seriesId") or ""),
            }
            out.append(item)
        rows = out
    else:
        rows = json_rows

    if brick_type:
        bt = brick_type.strip()
        filtered = [r for r in rows if r.get("brick_type") == bt]
        if filtered:
            rows = filtered
    rows.sort(key=lambda r: r["name"].lower())
    return rows


def query_feeds(
    site_id: str,
    *,
    model: dict[str, Any] | None = None,
    ensure: bool = True,
) -> list[dict[str, str]]:
    site = _sanitize_local_name(site_id)
    if site is None:
        return []
    if ensure:
        from .model_feeds import ensure_site_feeds

        with ModelService().transaction() as model:
            ensure_site_feeds(model, site_id)
    model = model if model is not None else ModelService().load()
    ttl_text = TtlService().build_ttl()
    q = FEEDS_QUERY.format(site=site)
    sparql_rows = _run_sparql(ttl_text, q)
    if sparql_rows:
        out: list[dict[str, str]] = []
        for row in sparql_rows:
            src = _local_name(row.get("fromEq", ""), "eq")
            dst = _local_name(row.get("toEq", ""), "eq")
            if src and dst:
                out.append(
                    {
                        "from_equipment_id": src,
                        "to_equipment_id": dst,
                        "from_label": row.get("fromLabel") or src,
                        "to_label": row.get("toLabel") or dst,
                    }
                )
        return out
    edges: list[dict[str, str]] = []
    by_id = {str(e.get("id") or ""): e for e in model.get("equipment") or [] if isinstance(e, dict)}
    for eq in model.get("equipment") or []:
        if not isinstance(eq, dict) or str(eq.get("site_id") or "") != site_id:
            continue
        src = str(eq.get("id") or "")
        for dst in eq.get("feeds") or []:
            dst = str(dst)
            if not dst:
                continue
            target = by_id.get(dst, {})
            edges.append(
                {
                    "from_equipment_id": src,
                    "to_equipment_id": dst,
                    "from_label": str(eq.get("name") or src),
                    "to_label": str(target.get("name") or dst),
                }
            )
    return edges


def query_model_graph(site_id: str) -> dict[str, Any]:
    """Full site graph for Data Model UI — SPARQL-backed, no client-side grep."""
    from .model_feeds import ensure_site_feeds

    with ModelService().transaction() as model:
        ensure_site_feeds(model, site_id)
    model = ModelService().load()
    equipment = query_equipment(site_id, model=model)
    feeds = query_feeds(site_id, model=model, ensure=False)
    points_by_eq: dict[str, list[dict[str, Any]]] = {}
    for eq in equipment:
        eid = eq["equipment_id"]
        points_by_eq[eid] = query_sensors(site_id, eid, model=model)
    return {
        "site_id": site_id,
        "query_engine": "sparql" if _sparql_available() else "json",
        "equipment": equipment,
        "feeds": feeds,
        "points_by_equipment": points_by_eq,
    }


def scope_bundle(
    site_id: str,
    *,
    equipment_id: str | None = None,
    brick_type: str | None = None,
) -> dict[str, Any]:
    model = ModelService().load()
    sites = list_model_sites(model)
    sid = str(site_id or "").strip()
    if not sid and sites:
        sid = sites[0]["site_id"]
    equipment = query_equipment(sid, model=model) if sid else []
    eid = str(equipment_id or "").strip()
    if not eid and equipment:
        eid = equipment[0]["equipment_id"]
    sensors = query_sensors(sid, eid, brick_type=brick_type, model=model) if sid and eid else []
    return {
        "site_id": sid,
        "equipment_id": eid,
        "sites": sites,
        "equipment": equipment,
        "sensors": sensors,
        "query_engine": "sparql" if _sparql_available() else "json",
    }
