"""BRICK data-model reads: SPARQL over synced ``data_model.ttl`` (rdflib), JSON only for writes/import."""

from __future__ import annotations

import logging
from typing import Any

from .model_service import ModelService
from .timeseries_api import plot_column_name
from .ttl_graph import (
    TtlGraphError,
    brick_type_local,
    load_graph,
    local_name,
    run_sparql,
)
from .ttl_service import TtlService, _sanitize_local_name

_log = logging.getLogger(__name__)

DEMO_SITE_IDS = frozenset({"site", "test", "sample", "default"})

SITES_QUERY = """
PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?site ?label WHERE {
  ?site a brick:Site .
  OPTIONAL { ?site rdfs:label ?label }
}
ORDER BY ?label
"""

EQUIPMENT_QUERY = """
PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX ofdd: <http://openfdd.local/ontology#>
SELECT ?eq ?label ?eqType ?bacnetInst WHERE {
  ?eq a ?eqType .
  ?eq brick:isPartOf :site_{site} .
  ?eq rdfs:label ?label .
  OPTIONAL { ?eq ofdd:bacnetDeviceInstance ?bacnetInst }
  FILTER(STRSTARTS(STR(?eqType), "https://brickschema.org/schema/Brick#"))
}
ORDER BY ?label
"""

SENSORS_QUERY = """
PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX ofdd: <http://openfdd.local/ontology#>
SELECT ?pt ?label ?brickType ?ruleInput ?seriesId ?tsCol WHERE {
  ?pt a ?brickType .
  ?pt brick:isPointOf :eq_{equipment} .
  ?pt rdfs:label ?label .
  OPTIONAL { ?pt ofdd:mapsToRuleInput ?ruleInput }
  OPTIONAL { ?pt ofdd:seriesId ?seriesId }
  OPTIONAL { ?pt ofdd:timeseriesColumn ?tsCol }
  FILTER(STRSTARTS(STR(?brickType), "https://brickschema.org/schema/Brick#"))
}
ORDER BY ?label
"""

FEEDS_QUERY = """
PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?fromEq ?toEq ?fromLabel ?toLabel WHERE {
  ?fromEq brick:feeds ?toEq .
  ?fromEq brick:isPartOf :site_{site} .
  ?toEq brick:isPartOf :site_{site} .
  OPTIONAL { ?fromEq rdfs:label ?fromLabel }
  OPTIONAL { ?toEq rdfs:label ?toLabel }
}
"""

TREE_EQUIPMENT_QUERY = """
PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX ofdd: <http://openfdd.local/ontology#>
SELECT ?eq ?label ?eqType ?site ?bacnetInst WHERE {
  ?eq a ?eqType .
  ?eq brick:isPartOf ?site .
  ?site a brick:Site .
  ?eq rdfs:label ?label .
  OPTIONAL { ?eq ofdd:bacnetDeviceInstance ?bacnetInst }
  FILTER(STRSTARTS(STR(?eqType), "https://brickschema.org/schema/Brick#"))
}
ORDER BY ?label
"""

def _bind_query(query: str, **bindings: str) -> str:
    """Substitute {site} / {equipment} without breaking SPARQL { } braces."""
    out = query
    for key, value in bindings.items():
        out = out.replace("{" + key + "}", str(value))
    return out


TREE_POINTS_QUERY = """
PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX ofdd: <http://openfdd.local/ontology#>
SELECT ?pt ?label ?brickType ?eq ?site ?ruleInput ?seriesId ?tsCol ?unit ?bacnetObj WHERE {
  ?pt a ?brickType .
  ?pt brick:isPointOf ?eq .
  ?eq brick:isPartOf ?site .
  ?site a brick:Site .
  OPTIONAL { ?pt rdfs:label ?label }
  OPTIONAL { ?pt ofdd:mapsToRuleInput ?ruleInput }
  OPTIONAL { ?pt ofdd:seriesId ?seriesId }
  OPTIONAL { ?pt ofdd:timeseriesColumn ?tsCol }
  OPTIONAL { ?pt ofdd:unit ?unit }
  OPTIONAL { ?pt ofdd:bacnetObjectIdentifier ?bacnetObj }
  FILTER(STRSTARTS(STR(?brickType), "https://brickschema.org/schema/Brick#"))
}
ORDER BY ?label
"""


def _is_demo_site(site_id: str) -> bool:
    return str(site_id or "").strip().lower() in DEMO_SITE_IDS


def _ids_match(a: str, b: str) -> bool:
    left = str(a or "").strip()
    right = str(b or "").strip()
    if not left or not right:
        return False
    if left == right:
        return True
    sl = _sanitize_local_name(left)
    sr = _sanitize_local_name(right)
    return sl == sr or sl == right or left == sr


def _meta_lookup(rows: list[dict[str, Any]], *, key: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        rid = str(row.get(key) or "").strip()
        if not rid:
            continue
        out[rid] = row
        san = _sanitize_local_name(rid)
        if san:
            out[san] = row
    return out


def _bacnet_sort_key(inst: Any) -> int:
    try:
        return int(inst)
    except (TypeError, ValueError):
        return 999_999


def _json_equipment_rows(model: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for eq in model.get("equipment") or []:
        if not isinstance(eq, dict):
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
                "bacnet_device_instance": inst,
                "site_id": str(eq.get("site_id") or ""),
            }
        )
    return rows


def _json_point_rows(model: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for pt in model.get("points") or []:
        if not isinstance(pt, dict):
            continue
        pid = str(pt.get("id") or "").strip()
        if not pid:
            continue
        col = plot_column_name(pt)
        name = str(pt.get("name") or pt.get("external_id") or pt.get("description") or col or pid)
        rows.append(
            {
                "point_id": pid,
                "id": pid,
                "name": name,
                "brick_type": str(pt.get("brick_type") or ""),
                "equipment_id": str(pt.get("equipment_id") or ""),
                "site_id": str(pt.get("site_id") or ""),
                "fdd_input": str(pt.get("fdd_input") or ""),
                "external_id": str(pt.get("external_id") or ""),
                "object_identifier": str(pt.get("object_identifier") or ""),
                "unit": str(pt.get("unit") or ""),
                "series_id": str(pt.get("series_id") or pt.get("metadata", {}).get("series_id") or ""),
            }
        )
    return rows


def _enrich_equipment_row(row: dict[str, str], meta: dict[str, dict[str, Any]]) -> dict[str, Any]:
    eid = local_name(row.get("eq", ""), "eq")
    if not eid:
        raise TtlGraphError("SPARQL equipment row missing ?eq binding")
    m = meta.get(eid, {})
    inst = row.get("bacnetInst") or m.get("bacnet_device_instance")
    name = row.get("label") or m.get("name") or eid
    eq_type = brick_type_local(row.get("eqType", "")) or m.get("equipment_type", "")
    canonical = str(m.get("equipment_id") or eid)
    return {
        "id": canonical,
        "equipment_id": canonical,
        "name": name,
        "label": name,
        "equipment_type": eq_type,
        "brick_type": eq_type,
        "site_id": m.get("site_id") or "",
        "bacnet_device_instance": int(inst) if inst is not None and str(inst).isdigit() else inst,
    }


def _enrich_sensor_row(row: dict[str, str], meta: dict[str, dict[str, Any]]) -> dict[str, Any]:
    pid = local_name(row.get("pt", ""), "pt")
    if not pid:
        raise TtlGraphError("SPARQL sensor row missing ?pt binding")
    m = meta.get(pid, {})
    canonical = str(m.get("point_id") or pid)
    brick = brick_type_local(row.get("brickType", "")) or m.get("brick_type", "")
    col = (
        m.get("timeseries_column")
        or str(row.get("tsCol") or "").strip()
        or str(m.get("external_id") or "")
        or canonical
    )
    name = m.get("name") or row.get("label") or col
    return {
        "point_id": canonical,
        "id": canonical,
        "name": name,
        "label": name,
        "brick_type": brick,
        "timeseries_column": col,
        "fdd_input": m.get("fdd_input") or str(row.get("ruleInput") or ""),
        "series_id": m.get("series_id") or str(row.get("seriesId") or ""),
        "object_identifier": m.get("object_identifier") or str(row.get("bacnetObj") or ""),
        "bacnet_device_address": m.get("bacnet_device_address") or "",
        "bacnet_device_id": m.get("bacnet_device_id"),
        "unit": m.get("unit") or str(row.get("unit") or ""),
        "equipment_id": m.get("equipment_id") or "",
        "site_id": m.get("site_id") or "",
        "external_id": m.get("external_id") or col,
    }


def _enrich_tree_point(row: dict[str, str], eq_meta: dict[str, dict[str, Any]], pt_meta: dict[str, dict[str, Any]]) -> dict[str, Any]:
    pid = local_name(row.get("pt", ""), "pt")
    eq_local = local_name(row.get("eq", ""), "eq")
    site_local = local_name(row.get("site", ""), "site")
    pm = pt_meta.get(pid, {})
    em = eq_meta.get(eq_local, {})
    canonical = str(pm.get("point_id") or pid)
    brick = brick_type_local(row.get("brickType", "")) or pm.get("brick_type", "")
    col = pm.get("external_id") or str(row.get("tsCol") or "").strip() or canonical
    return {
        "id": canonical,
        "name": pm.get("name") or row.get("label") or col,
        "brick_type": brick,
        "equipment_id": str(pm.get("equipment_id") or em.get("equipment_id") or eq_local),
        "site_id": str(pm.get("site_id") or em.get("site_id") or site_local),
        "fdd_input": pm.get("fdd_input") or str(row.get("ruleInput") or ""),
        "external_id": pm.get("external_id") or col,
        "object_identifier": pm.get("object_identifier") or str(row.get("bacnetObj") or ""),
        "unit": pm.get("unit") or str(row.get("unit") or ""),
        "series_id": pm.get("series_id") or str(row.get("seriesId") or ""),
    }


def list_model_sites(model: dict[str, Any] | None = None) -> list[dict[str, str]]:
    """Sites from SPARQL on synced TTL; excludes placeholder ids only."""
    ttl = TtlService()
    graph = load_graph(ttl)
    rows = run_sparql(graph, SITES_QUERY)
    if not rows:
        raise TtlGraphError("SPARQL found no brick:Site in data_model.ttl")
    out: list[dict[str, str]] = []
    for row in rows:
        sid = local_name(row.get("site", ""), "site")
        if not sid or _is_demo_site(sid):
            continue
        out.append({"site_id": sid, "name": row.get("label") or sid})
    if not out and model is not None:
        for row in model.get("sites") or []:
            if isinstance(row, dict):
                sid = str(row.get("id") or "").strip()
                if sid and not _is_demo_site(sid):
                    out.append({"site_id": sid, "name": str(row.get("name") or sid)})
    return sorted(out, key=lambda r: r["name"].lower())


def query_equipment(
    site_id: str,
    *,
    model: dict[str, Any] | None = None,
    ttl: TtlService | None = None,
) -> list[dict[str, Any]]:
    site = _sanitize_local_name(site_id)
    if site is None:
        return []
    model = model if model is not None else ModelService().load()
    ttl_svc = ttl or TtlService()
    graph = load_graph(ttl_svc)
    q = _bind_query(EQUIPMENT_QUERY, site=site)
    sparql_rows = run_sparql(graph, q)
    if not sparql_rows:
        raise TtlGraphError(f"SPARQL returned no equipment for site {site_id}; sync TTL")
    json_eq = _meta_lookup(_json_equipment_rows(model), key="equipment_id")
    out = [_enrich_equipment_row(row, json_eq) for row in sparql_rows]
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
    graph = load_graph(ttl_svc)
    q = _bind_query(SENSORS_QUERY, equipment=eq)
    sparql_rows = run_sparql(graph, q)
    if not sparql_rows:
        return []
    json_by_id = _meta_lookup(_json_point_rows(model), key="point_id")
    rows = [_enrich_sensor_row(row, json_by_id) for row in sparql_rows]
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

        with ModelService().transaction() as doc:
            ensure_site_feeds(doc, site_id)
            TtlService().sync()
    ttl_svc = TtlService()
    graph = load_graph(ttl_svc)
    q = _bind_query(FEEDS_QUERY, site=site)
    sparql_rows = run_sparql(graph, q)
    if not sparql_rows:
        return []
    out: list[dict[str, str]] = []
    for row in sparql_rows:
        src = local_name(row.get("fromEq", ""), "eq")
        dst = local_name(row.get("toEq", ""), "eq")
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


def query_model_tree() -> dict[str, Any]:
    """Full model catalog for Data Model / Rule Lab — all sites, equipment, points via SPARQL."""
    model = ModelService().load()
    ttl_svc = TtlService()
    graph = load_graph(ttl_svc)
    eq_rows = run_sparql(graph, TREE_EQUIPMENT_QUERY)
    pt_rows = run_sparql(graph, TREE_POINTS_QUERY)
    if not eq_rows and not pt_rows:
        raise TtlGraphError("SPARQL model tree is empty; POST /api/model/sync-ttl")
    eq_meta = _meta_lookup(_json_equipment_rows(model), key="equipment_id")
    pt_meta = _meta_lookup(_json_point_rows(model), key="point_id")
    equipment = [_enrich_equipment_row(row, eq_meta) for row in eq_rows]
    points = [_enrich_tree_point(row, eq_meta, pt_meta) for row in pt_rows]
    sites = list_model_sites(model)
    brick_types = sorted({str(p.get("brick_type") or "").strip() for p in points if p.get("brick_type")})
    eq_types = sorted(
        {str(e.get("equipment_type") or "").strip() for e in equipment if e.get("equipment_type")}
    )
    return {
        "query_engine": "sparql",
        "ttl_path": str(ttl_svc.ttl_path),
        "sites": sites,
        "equipment": equipment,
        "points": points,
        "brick_types": brick_types,
        "equipment_types": eq_types,
    }


def query_model_graph(site_id: str) -> dict[str, Any]:
    """Site equipment, points, and brick:feeds edges — SPARQL over synced TTL."""
    from .model_feeds import ensure_site_feeds

    svc = ModelService()
    model = svc.load()
    try:
        with svc.transaction() as doc:
            ensure_site_feeds(doc, site_id)
            TtlService().sync()
    except OSError as exc:
        _log.warning("model graph: skip feeds write (%s): %s", site_id, exc)
    equipment = query_equipment(site_id, model=model)
    feeds = query_feeds(site_id, model=model, ensure=False)
    points_by_eq: dict[str, list[dict[str, Any]]] = {}
    for eq in equipment:
        eid = eq["equipment_id"]
        points_by_eq[eid] = query_sensors(site_id, eid, model=model)
    return {
        "site_id": site_id,
        "query_engine": "sparql",
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
        "query_engine": "sparql",
    }
