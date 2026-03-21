"""
Regression guard: rdflib SPARQL + pyparsing must execute without parser callback errors.

Broken rdflib / pyparsing combos can surface as::

    Param.postParse2() missing 1 required positional argument: 'tokenList'

on POST /data-model/sparql (typically **pyparsing 3.2+** with **rdflib 7.x**). Open-FDD pins
``pyparsing>=2.1.0,<3.2`` next to rdflib in ``pyproject.toml`` (brick/dev/test extras).
Pytest runs this on ``./scripts/bootstrap.sh --test`` so the same install as
``pip install -e ".[platform,brick]"`` (API image) is exercised.

Queries mirror patterns from ``scripts/automated_testing/sparql/`` (COUNT, PREFIX,
OPTIONAL, wildcard predicate, GROUP BY).
"""

from __future__ import annotations

import pytest

pytest.importorskip("rdflib")

from open_fdd.platform.api.data_model import _run_sparql_on_ttl

# Minimal Turtle: sites + platform config + one point-ish triple (wildcard query coverage)
_MINIMAL_TTL = """
@prefix brick: <https://brickschema.org/schema/Brick#> .
@prefix ofdd: <http://openfdd.local/ontology#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ref: <https://brickschema.org/schema/Brick/ref#> .

<http://openfdd.local/site/t1> a brick:Site ;
    rdfs:label "TestBenchSite" .

_:cfg a ofdd:PlatformConfig ;
    rdfs:label "platform" ;
    ofdd:someKey "someValue" .

<http://openfdd.local/point/p1> a brick:Supply_Air_Temperature_Sensor ;
    rdfs:label "SA-T" .

_:bref a ref:BACnetReference .
"""


def test_run_sparql_on_ttl_count_star() -> None:
    bindings = _run_sparql_on_ttl(_MINIMAL_TTL, "SELECT (COUNT(*) AS ?n) WHERE { ?s ?p ?o }")
    assert isinstance(bindings, list)
    assert len(bindings) == 1
    assert "n" in bindings[0] or any(k.lower() == "n" for k in bindings[0])


def test_run_sparql_on_ttl_platform_config_wildcard_predicate() -> None:
    """Same shape as 01_platform_config.sparql (wildcard ?c ?p ?v)."""
    q = """PREFIX ofdd: <http://openfdd.local/ontology#>
SELECT ?p ?v WHERE {
  ?c a ofdd:PlatformConfig .
  ?c ?p ?v .
}
"""
    bindings = _run_sparql_on_ttl(_MINIMAL_TTL, q)
    assert isinstance(bindings, list)
    assert len(bindings) >= 1


def test_run_sparql_on_ttl_sites_optional_label() -> None:
    q = """PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?site ?site_label WHERE {
  ?site a brick:Site .
  OPTIONAL { ?site rdfs:label ?site_label }
}
"""
    bindings = _run_sparql_on_ttl(_MINIMAL_TTL, q)
    assert isinstance(bindings, list)
    assert len(bindings) == 1


def test_run_sparql_on_ttl_group_by_with_values() -> None:
    """GROUP BY + VALUES (shape similar to orphan / ref-type counts)."""
    q = """PREFIX ref: <https://brickschema.org/schema/Brick/ref#>
SELECT ?ref_type (COUNT(?ref_node) AS ?cnt) WHERE {
  VALUES ?ref_type { ref:BACnetReference }
  ?ref_node a ?ref_type .
}
GROUP BY ?ref_type
"""
    bindings = _run_sparql_on_ttl(_MINIMAL_TTL, q)
    assert isinstance(bindings, list)
    assert len(bindings) >= 1
