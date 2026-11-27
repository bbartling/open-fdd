"""pyoxigraph is the SPARQL engine. rdflib 7.6.0 disagrees on three of six edge cases.

The Full hook (vendored Oxigraph 0.5.13) and the local path (pyoxigraph 0.5.13) return
the same rows. The three disagreements are locked so a later rdflib release cannot
silently become the answer.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

pyoxigraph = pytest.importorskip("pyoxigraph")
rdflib = pytest.importorskip("rdflib")

from open_fdd.sparql_eval import query_turtle  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

TTL = textwrap.dedent("""\
    @prefix ex: <urn:ex:> .
    @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
    ex:s ex:plain "x" .
    ex:s ex:typed "x"^^xsd:string .
    ex:s ex:bad "abc"^^xsd:integer .
    ex:s ex:ok "2"^^xsd:integer .
    ex:s ex:item "b" .
    ex:s ex:item "a" .
    ex:s ex:item "c" .
    """)

QUERIES = {
    "bgp": "SELECT (COUNT(*) AS ?n) WHERE { ?s ?p ?o }",
    "filter_num": """
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        SELECT ?n WHERE { ?s <urn:ex:ok> ?n FILTER(?n > 1) }""",
    "optional": """
        SELECT ?p ?o WHERE {
          <urn:ex:s> <urn:ex:plain> ?p
          OPTIONAL { <urn:ex:s> <urn:ex:missing> ?o }
        }""",
    "string_join": """
        SELECT ?a ?b WHERE { ?a <urn:ex:plain> ?v . ?b <urn:ex:typed> ?v . }""",
    "ill_typed": """
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        SELECT ?x WHERE { ?s <urn:ex:bad> ?x FILTER(?x > 0) }""",
    "group_concat": """
        SELECT (GROUP_CONCAT(?y ; SEPARATOR="|") AS ?g) WHERE { ?s <urn:ex:item> ?y }""",
}


def _oxigraph() -> dict:
    return {name: _rows(query_turtle(TTL, query)) for name, query in QUERIES.items()}


def _rows(answer) -> list[dict]:
    return [{key: value for key, value in row.items()} for row in answer.rows]


def _rdflib() -> dict:
    graph = rdflib.Graph().parse(data=TTL, format="turtle")
    out = {}
    for name, query in QUERIES.items():
        result = graph.query(query)
        names = [str(var) for var in result.vars]
        out[name] = [{n: (None if row[i] is None else str(row[i])) for i, n in enumerate(names)} for row in result]
    return out


def test_six_edge_cases_and_three_disagreements():
    ox, rd = _oxigraph(), _rdflib()
    assert ox["bgp"] == rd["bgp"] == [{"n": "7"}]
    assert ox["filter_num"] == rd["filter_num"] == [{"n": "2"}]
    assert ox["optional"] == rd["optional"] == [{"p": "x", "o": None}]
    # RDF 1.1: a plain string and xsd:string are the same term. Oxigraph joins them.
    assert ox["string_join"] == [{"a": "urn:ex:s", "b": "urn:ex:s"}]
    assert rd["string_join"] == []
    # An ill-typed integer does not pass a numeric filter. rdflib still returns it.
    assert ox["ill_typed"] == []
    assert rd["ill_typed"] == [{"x": "abc"}]
    # GROUP_CONCAT order is not significant in SPARQL. Oxigraph's order is the answer.
    assert ox["group_concat"] == [{"g": "c|a|b"}]
    assert rd["group_concat"] == [{"g": "b|a|c"}]
    assert ox["group_concat"] != rd["group_concat"]


def test_full_hook_and_local_path_return_the_same_rows(tmp_path: Path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not available")
    script = ROOT / "tests" / "fixtures" / "sparql" / "hook_rows.mjs"
    spec = tmp_path / "edge_cases.json"
    spec.write_text(json.dumps({"turtle": TTL, "queries": QUERIES}), encoding="utf-8")
    run = subprocess.run([node, str(script), str(spec)], cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    hook = json.loads(run.stdout)
    local = _oxigraph()
    assert hook.keys() == local.keys()
    for name in QUERIES:
        assert hook[name] == local[name], name
