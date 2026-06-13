"""Read-only BRICK SPARQL against mirrored site TTL on RCx Central."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from portfolio.central.edge_registry import resolve_site_config, resolve_token
from portfolio.central.model_ttl_mirror import mirror_site_ttl, ttl_mirror_status
from portfolio.central.paths import site_ttl_path
from portfolio.collector.edge_client import EdgeClient

BRICK = "https://brickschema.org/schema/Brick#"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"
OFDD = "http://openfdd.local/ontology#"
MAX_SPARQL_ROWS = 5000

_FORBIDDEN_FORMS = frozenset(
    {
        "INSERT",
        "DELETE",
        "UPDATE",
        "LOAD",
        "CLEAR",
        "DROP",
        "CREATE",
        "MOVE",
        "COPY",
        "ADD",
    }
)
_READONLY_FORMS = frozenset({"SELECT", "ASK", "DESCRIBE", "CONSTRUCT"})

_VALIDATION_QUERIES: list[dict[str, str]] = [
    {
        "id": "sites",
        "label": "Sites",
        "query": f"""PREFIX brick: <{BRICK}>
PREFIX rdfs: <{RDFS}>
SELECT (COUNT(DISTINCT ?site) AS ?count) WHERE {{
  ?site a brick:Site .
}}""",
    },
    {
        "id": "ahu_information",
        "label": "Air Handling Units",
        "query": f"""PREFIX brick: <{BRICK}>
SELECT (COUNT(DISTINCT ?equipment) AS ?count) WHERE {{
  ?equipment a brick:Air_Handling_Unit .
}}""",
    },
    {
        "id": "count-vavs",
        "label": "VAV boxes",
        "query": f"""PREFIX brick: <{BRICK}>
SELECT (COUNT(DISTINCT ?equipment) AS ?count) WHERE {{
  ?equipment a brick:Variable_Air_Volume_Box .
}}""",
    },
]


class TtlGraphError(RuntimeError):
    """BRICK graph missing, invalid, or SPARQL failed."""


class RdfLibRequired(TtlGraphError):
    """rdflib not installed."""


def require_rdflib():
    try:
        import rdflib  # noqa: F401

        return rdflib
    except ImportError as exc:
        raise RdfLibRequired(
            "rdflib is required for local BRICK SPARQL; pip install -r portfolio/requirements.txt"
        ) from exc


def _strip_sparql_comments(query: str) -> str:
    text = re.sub(r"#.*?$", "", query, flags=re.MULTILINE)
    return re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)


def validate_readonly_sparql(query: str) -> None:
    stripped = _strip_sparql_comments(query or "").strip()
    if not stripped:
        raise HTTPException(status_code=400, detail="SPARQL query is empty")
    tokens = re.findall(r"\b(\w+)\b", stripped, flags=re.IGNORECASE)
    form: str | None = None
    for token in tokens:
        upper = token.upper()
        if upper in ("PREFIX", "BASE"):
            continue
        if upper in _FORBIDDEN_FORMS:
            raise HTTPException(
                status_code=400,
                detail="Only read-only SPARQL (SELECT, ASK, DESCRIBE, CONSTRUCT) is allowed",
            )
        if upper in _READONLY_FORMS:
            form = upper
            break
    if form is None:
        raise HTTPException(
            status_code=400,
            detail="Only read-only SPARQL (SELECT, ASK, DESCRIBE, CONSTRUCT) is allowed",
        )


def load_graph_path(path: Path):
    from rdflib import Graph

    require_rdflib()
    if not path.is_file():
        raise TtlGraphError(
            f"TTL mirror missing at {path}; POST /api/central/model/sync-ttl/{{site_id}} first"
        )
    graph = Graph()
    try:
        graph.parse(str(path), format="turtle")
    except Exception as exc:
        raise TtlGraphError(f"Invalid Turtle at {path}: {exc}") from exc
    if len(graph) == 0:
        raise TtlGraphError(f"TTL graph is empty at {path}")
    return graph


def run_sparql(graph, query: str) -> list[dict[str, str]]:
    from rdflib.query import ResultRow

    out: list[dict[str, str]] = []
    try:
        for row in graph.query(query):
            if not isinstance(row, ResultRow):
                continue
            item: dict[str, str] = {}
            for key in row.labels:
                val = row[key]
                item[str(key)] = str(val) if val is not None else ""
            out.append(item)
    except Exception as exc:
        raise TtlGraphError(f"SPARQL query failed: {exc}") from exc
    return out


def ensure_site_ttl(site_id: str, *, sync_edge: bool = False) -> Path:
    path = site_ttl_path(site_id)
    if not path.is_file():
        mirror_site_ttl(site_id, sync_edge=sync_edge)
    return path


def execute_site_sparql(
    site_id: str,
    query: str,
    *,
    sync_if_missing: bool = True,
) -> dict[str, Any]:
    validate_readonly_sparql(query)
    path = site_ttl_path(site_id)
    if not path.is_file():
        if not sync_if_missing:
            raise HTTPException(status_code=404, detail="TTL mirror missing — sync TTL first")
        mirror_site_ttl(site_id, sync_edge=True)
        path = site_ttl_path(site_id)
    try:
        graph = load_graph_path(path)
        rows = run_sparql(graph, query)
    except TtlGraphError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    truncated = len(rows) > MAX_SPARQL_ROWS
    if truncated:
        rows = rows[:MAX_SPARQL_ROWS]
    return {
        "site_id": site_id,
        "query_engine": "sparql",
        "ttl_path": str(path),
        "bindings": rows,
        "row_count": len(rows),
        "truncated": truncated,
    }


def predefined_catalog(site_id: str) -> dict[str, Any]:
    """Edge predefined SPARQL catalog (cached per request via Edge API)."""
    site = resolve_site_config(site_id)
    token = resolve_token(site)
    client = EdgeClient(site.base_url)
    try:
        raw = client.get_model_queries(token=token)
    except RuntimeError as exc:
        raise RuntimeError(f"failed to load SPARQL catalog from Edge: {exc}") from exc
    return {
        "site_id": site_id,
        "default_query": raw.get("default_query"),
        "queries": raw.get("queries") or [],
        "mirror": ttl_mirror_status(site_id),
    }


def _count_from_bindings(rows: list[dict[str, str]]) -> int | None:
    if not rows:
        return 0
    first = rows[0]
    for key in ("count", "COUNT", "c"):
        if key in first and str(first[key]).strip().isdigit():
            return int(first[key])
    return len(rows)


def validate_site_model(site_id: str, *, sync_if_missing: bool = True) -> dict[str, Any]:
    """Run HVAC SPARQL sanity checks on mirrored TTL."""
    if sync_if_missing and not site_ttl_path(site_id).is_file():
        mirror_site_ttl(site_id, sync_edge=True)

    checks: list[dict[str, Any]] = []
    ok = True
    for spec in _VALIDATION_QUERIES:
        try:
            result = execute_site_sparql(site_id, spec["query"], sync_if_missing=False)
            count = _count_from_bindings(result.get("bindings") or [])
            checks.append(
                {
                    "id": spec["id"],
                    "label": spec["label"],
                    "ok": True,
                    "count": count,
                    "row_count": result.get("row_count"),
                }
            )
        except HTTPException as exc:
            ok = False
            checks.append(
                {
                    "id": spec["id"],
                    "label": spec["label"],
                    "ok": False,
                    "error": str(exc.detail),
                }
            )

    mirror = ttl_mirror_status(site_id)
    return {
        "site_id": site_id,
        "ok": ok and mirror.get("ttl_exists"),
        "mirror": mirror,
        "checks": checks,
        "query_engine": "sparql",
    }
