"""Open-FDD extension-term completeness check (#1569 policy items 1, 2, 5): open_fdd.ontology_audit.extensions."""
from __future__ import annotations

import json

import pytest

rdflib = pytest.importorskip("rdflib")

from open_fdd.ontology_audit.extensions import check_extensions, shipped_vocabulary  # noqa: E402

TTL = """
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix brick: <https://brickschema.org/schema/Brick#> .
@prefix ofdd: <urn:openfdd:ns#> .

ofdd:Vocab a owl:Ontology .
ofdd:Fault_Hours_Point a rdfs:Class ; rdfs:subClassOf brick:Point ;
    rdfs:label "Fault hours point" ; skos:definition "Hours a rule was in fault." .
ofdd:Sensor_Fault_Hours_Point a rdfs:Class ; rdfs:subClassOf ofdd:Fault_Hours_Point ;
    rdfs:label "Sensor fault hours point" ; rdfs:comment "Per-sensor fault hours." .
ofdd:Orphan a rdfs:Class .
ofdd:ruleRef a rdf:Property ; rdfs:subPropertyOf brick:Relationship ; rdfs:label "rule ref" .
ofdd:Kind a rdfs:Class ; rdfs:subClassOf rdfs:Resource ; rdfs:label "Kind" ; skos:definition "x" .
ofdd:Hourly a ofdd:Kind .
ofdd:Stray a ofdd:Undeclared .
brick:My_Custom_Point a rdfs:Class ; rdfs:subClassOf brick:Point .
"""


def _by_iri(report):
    return {t["iri"].rsplit("#", 1)[-1]: t for t in report["terms"]}


def test_complete_terms_pass_and_chains_reach_a_standard_root():
    rep = check_extensions(rdflib.Graph().parse(data=TTL, format="turtle"))
    t = _by_iri(rep)
    assert t["Fault_Hours_Point"]["issues"] == [] and t["Fault_Hours_Point"]["standard_root"].endswith("Brick#Point")
    sub = t["Sensor_Fault_Hours_Point"]
    assert sub["issues"] == [] and sub["parents"][0].endswith("#Fault_Hours_Point")
    assert sub["standard_root"].endswith("Brick#Point")  # followed through the Open-FDD parent
    assert t["Hourly"]["kind"] == "individual" and t["Hourly"]["issues"] == []
    assert "Vocab" not in t  # the ontology header is not a term


def test_incomplete_terms_and_standard_namespace_minting_are_flagged():
    rep = check_extensions(rdflib.Graph().parse(data=TTL, format="turtle"))
    t = _by_iri(rep)
    assert set(t["Orphan"]["issues"]) == {"no_standard_parent", "no_label", "no_definition"}
    assert t["ruleRef"]["issues"] == ["no_definition"]
    assert "no_standard_parent" in t["Kind"]["issues"]  # rdfs:Resource is built-in, not a domain concept
    assert t["Stray"]["issues"] == ["undeclared_type"]
    assert t["My_Custom_Point"]["issues"] == ["minted_in_standard_namespace"]
    assert rep["complete"] is False and rep["issue_counts"]["minted_in_standard_namespace"] == 1


def test_shipped_vocabulary_is_reported_not_rewritten():
    g = shipped_vocabulary()
    before = len(g)
    rep = check_extensions(g)
    assert len(g) == before  # read-only
    assert rep["term_counts"]["class"] >= 1 and rep["term_counts"]["individual"] >= 1
    assert all(t["iri"].startswith("urn:openfdd:ns#") for t in rep["terms"])
    json.dumps(rep)  # serializable


def test_cli_extensions(tmp_path, capsys):
    from open_fdd.ontology_audit.cli import main

    ext = tmp_path / "ext.ttl"
    ext.write_text(TTL, encoding="utf-8")
    assert main(["--extensions", str(ext), "--out", str(tmp_path / "r")]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["complete"] is False and out["issues"]["no_label"] == 1
    saved = json.loads((tmp_path / "r" / "extensions.json").read_text(encoding="utf-8"))
    assert {t["iri"].rsplit("#", 1)[-1] for t in saved["terms"]} >= {"Orphan", "Fault_Hours_Point"}
    assert main(["--extensions"]) == 0  # the shipped vocabulary
    assert "complete" in json.loads(capsys.readouterr().out)
