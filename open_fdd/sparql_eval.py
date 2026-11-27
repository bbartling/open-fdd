"""Canonical SPARQL evaluation: pyoxigraph 0.5.13.

The Full app's hook uses the vendored Oxigraph 0.5.13 build. Local mode and the
model doctor use this module so those answers match. rdflib 7.6.0 parses Turtle
and checks query shape; it does not evaluate the queries that produce answers.

Three queries are known to differ on rdflib 7.6.0 (plain ``xsd:string`` join,
ill-typed numeric literals, ``GROUP_CONCAT`` order). The Oxigraph result is the
one the app returns. See ``tests/test_sparql_engines.py``.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Any


@dataclass
class QueryAnswer:
    kind: str
    variables: list[str] = field(default_factory=list)
    rows: list[dict[str, str | None]] = field(default_factory=list)
    value: bool | None = None


def _term_text(term: Any) -> str | None:
    if term is None:
        return None
    value = getattr(term, "value", None)
    return str(value) if value is not None else str(term)


def _load(store, data: bytes, fmt) -> None:
    store.load(io.BytesIO(data), fmt)


def query_turtle(turtle: str, query: str) -> QueryAnswer:
    """Evaluate ``query`` against Turtle text. SELECT rows or an ASK boolean."""
    import pyoxigraph

    store = pyoxigraph.Store()
    _load(store, turtle.encode("utf-8"), pyoxigraph.RdfFormat.TURTLE)
    return _query_store(store, query)


def query_graph(graph, query: str) -> QueryAnswer:
    """Evaluate ``query`` against an rdflib graph (serialized to N-Triples first)."""
    import pyoxigraph

    store = pyoxigraph.Store()
    _load(store, graph.serialize(format="nt").encode("utf-8"), pyoxigraph.RdfFormat.N_TRIPLES)
    return _query_store(store, query)


def _query_store(store, query: str) -> QueryAnswer:
    import pyoxigraph

    result = store.query(query)
    if isinstance(result, pyoxigraph.QueryBoolean):
        return QueryAnswer(kind="ask", value=bool(result))
    names = [v.value if hasattr(v, "value") else str(v) for v in result.variables]
    rows = [{name: _term_text(sol[name]) for name in names} for sol in result]
    return QueryAnswer(kind="select", variables=names, rows=rows)
