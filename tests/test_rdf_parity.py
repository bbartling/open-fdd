"""rdflib answers vs the Node path in nf-app/hooks/sparql.js (Oxigraph 0.5.13).

Panel queries are the ones ``static/sparql.js`` serves. Role queries read the
shipped role file, the same Turtle in both engines. Rows are sorted. IRIs stay
IRIs. A plain literal and ``xsd:string`` are the same term. The hook does not
resolve ``owl:imports`` and does not run SHACL. ``OPENFDD_RDF_CLOSURE=1`` checks
the vendored OntoEnv closure and does not download it. The shipped role Turtle
and binding must be the bytes the Python alignment job validates.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

rdflib = pytest.importorskip("rdflib")

ROOT = Path(__file__).resolve().parents[1]
GOOD = ROOT / "open_fdd" / "ontology_audit" / "data" / "example_building.ttl"
ROLES = ROOT / "sql" / "fdd" / "roles-223p.ttl"
NODE = ROOT / "tests" / "fixtures" / "rdf" / "node_parity.mjs"
XSD_STRING = "http://www.w3.org/2001/XMLSchema#string"

ROLE_QUERIES = {
    "role_count": """
        PREFIX ofdd: <urn:openfdd:role#>
        SELECT (COUNT(?role) AS ?n) WHERE { ?role a ofdd:PointRole }
    """,
    "role_with_unit": """
        PREFIX ofdd: <urn:openfdd:role#>
        ASK { ?role a ofdd:PointRole ; ofdd:unit ?unit }
    """,
    "g36_valve": """
        PREFIX ofdd: <urn:openfdd:role#>
        PREFIX g36: <http://data.ashrae.org/standard223/1.0/extensions/g36#>
        SELECT ?role WHERE { ?role ofdd:appliesTo g36:ChilledWaterValve }
    """,
}
MISSING_SITE = """
    PREFIX phIoT: <https://project-haystack.org/def/phIoT/4.0.0#>
    SELECT ?point WHERE {
      ?point a phIoT:point .
      FILTER NOT EXISTS { ?point phIoT:siteRef ?site }
    }
"""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _term(term):
    if term is None:
        return None
    if isinstance(term, rdflib.URIRef):
        return {"type": "uri", "value": str(term)}
    if isinstance(term, rdflib.BNode):
        return {"type": "bnode", "value": str(term)}
    if isinstance(term, rdflib.Literal):
        datatype = str(term.datatype) if term.datatype else ""
        lang = term.language or ""
        if not lang and datatype in ("", XSD_STRING):
            datatype = XSD_STRING
        return {"type": "literal", "value": str(term), "datatype": datatype, "lang": lang}
    raise TypeError(type(term))


def _sort_select(payload: dict) -> dict:
    names = list(payload["vars"])
    rows = [tuple(json.dumps(binding.get(name), sort_keys=True) for name in names) for binding in payload["bindings"]]
    rows.sort()
    return {"kind": "select", "vars": names, "rows": rows}


def _rdflib(turtle: str, queries: dict[str, str]) -> dict:
    graph = rdflib.Graph()
    graph.parse(data=turtle, format="turtle")
    out = {}
    for name, query in queries.items():
        result = graph.query(query)
        if result.type == "ASK":
            out[name] = {"kind": "ask", "value": bool(result.askAnswer)}
            continue
        names = [str(var) for var in result.vars]
        bindings = [{var: _term(row[var]) for var in names} for row in result]
        out[name] = {"kind": "select", "vars": names, "bindings": bindings}
    return out


def _node(turtle: str, queries: dict[str, str], tmp: Path, *, include_examples: bool) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not available")
    tmp.mkdir(parents=True, exist_ok=True)
    path = tmp / "model.ttl"
    path.write_text(turtle, encoding="utf-8")
    spec = tmp / "spec.json"
    spec.write_text(json.dumps({
        "turtle": str(path), "queries": queries, "includeExamples": include_examples,
    }), encoding="utf-8")
    dest = tmp / "node.json"
    run = subprocess.run([node, str(NODE), str(spec), str(dest)], cwd=ROOT, capture_output=True, text=True, timeout=180)
    assert run.returncode == 0, run.stderr
    return json.loads(dest.read_text(encoding="utf-8"))


def _normalize_bindings(payload: dict) -> dict:
    bindings = []
    for binding in payload["bindings"]:
        cell = {}
        for name, term in binding.items():
            if isinstance(term, dict) and term.get("type") == "literal":
                datatype = term.get("datatype") or ""
                lang = term.get("lang") or ""
                if not lang and datatype in ("", XSD_STRING):
                    datatype = XSD_STRING
                term = {**term, "datatype": datatype, "lang": lang}
            cell[name] = term
        bindings.append(cell)
    return {**payload, "bindings": bindings}


def _same(python: dict, node: dict) -> None:
    assert set(python) == set(node)
    for name in python:
        left, right = python[name], node[name]
        assert left["kind"] == right["kind"], name
        if left["kind"] == "ask":
            assert bool(left["value"]) is bool(right["value"]), name
        else:
            assert _sort_select(_normalize_bindings(left)) == _sort_select(_normalize_bindings(right)), name


def test_panel_queries_match_on_the_example_and_a_broken_model(tmp_path: Path):
    good = GOOD.read_text(encoding="utf-8")
    broken = good + """
local:orphan a phIoT:point ;
    rdfs:label "orphan" ;
    ph:hasTag phIoT:point .
"""
    assert "local:orphan" not in good
    for label, turtle in (("good", good), ("broken", broken)):
        node = _node(turtle, {"missing_site": MISSING_SITE}, tmp_path / label, include_examples=True)
        python = _rdflib(turtle, node["queries"])
        _same(python, node["results"])
        rows = _sort_select(python["missing_site"])["rows"]
        if label == "good":
            assert rows == []
        else:
            assert rows


def test_role_queries_match(tmp_path: Path):
    turtle = ROLES.read_text(encoding="utf-8")
    node = _node(turtle, ROLE_QUERIES, tmp_path, include_examples=False)
    _same(_rdflib(turtle, ROLE_QUERIES), node["results"])


@pytest.mark.skipif(os.environ.get("OPENFDD_RDF_CLOSURE") != "1", reason="set OPENFDD_RDF_CLOSURE=1")
def test_pinned_closure_resolves_offline():
    pytest.importorskip("ontoenv")
    from open_fdd.ontology_audit.closure import imported_pins, materialize_223p_closure

    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        names = materialize_223p_closure(Path(tmp))
    assert set(names) == {item["iri"] for item in imported_pins()}


def test_hook_does_not_run_shacl_and_shipped_roles_match_python():
    hook = (ROOT / "nf-app" / "hooks" / "sparql.js").read_text(encoding="utf-8").lower()
    panel = (ROOT / "nf-app" / "static" / "sparql.js").read_text(encoding="utf-8").lower()
    assert "shacl" not in hook and "shifty" not in hook
    assert "shacl" not in panel and "shifty" not in panel
    ttl = _sha256(ROLES)
    binding = _sha256(ROOT / "nf-app" / "static" / "roles" / "role-binding.json")
    for edition in ("nf-app", "lite"):
        base = ROOT / edition / "static" / "roles"
        assert _sha256(base / "roles-223p.ttl") == ttl
        assert _sha256(base / "role-binding.json") == binding


def test_shifty_verdict_is_the_reference_on_a_small_fixture():
    shifty = pytest.importorskip("shifty")
    from rdflib import Graph

    from open_fdd.ontology_audit.shacl import validate_shacl

    shapes = Graph().parse(data="""
        @prefix sh: <http://www.w3.org/ns/shacl#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
        @prefix ex: <urn:ex:> .
        ex:Labeled a sh:NodeShape ;
            sh:targetClass ex:Item ;
            sh:property [ sh:path rdfs:label ; sh:minCount 1 ] .
    """, format="turtle")
    good = Graph().parse(data="""
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
        @prefix ex: <urn:ex:> .
        ex:ok a ex:Item ; rdfs:label "ok" .
    """, format="turtle")
    bad = Graph().parse(data="""
        @prefix ex: <urn:ex:> .
        ex:missing a ex:Item .
    """, format="turtle")
    passed = validate_shacl(good, shapes, engine="shifty")
    failed = validate_shacl(bad, shapes, engine="shifty")
    assert passed["conforms"] is True and passed["engine"] == "shifty"
    assert failed["conforms"] is False
    assert any(row["focus"].endswith("missing") for row in failed["violations"])
    assert shifty is not None
