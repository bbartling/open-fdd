"""Definition-completeness check for Open-FDD ontology extension terms (#1569, policy items 1, 2 and 5).

The Open-FDD extension policy says every term Open-FDD mints lives in an Open-FDD namespace, extends a standard
concept and has a complete definition. This check reads an extension graph (default: the shipped
``ofdd_engineering_quantities_v1.ttl``) and reports, per declared term:

* ``kind``: ``class``, ``property`` or ``individual`` (an enum member such as a quantity kind);
* ``parents`` and ``standard_root``: the ``rdfs:subClassOf`` / ``rdfs:subPropertyOf`` chain (``rdf:type`` for an
  individual), followed through Open-FDD terms until it reaches a standard namespace;
* ``issues``:

  - ``minted_in_standard_namespace``: the graph declares a class or property inside Brick, 223P, Haystack, QUDT or
    another standard namespace;
  - ``no_standard_parent``: a class or property whose chain never reaches a standard concept;
  - ``no_label`` / ``no_definition``: a class or property lacking ``rdfs:label`` / ``skos:definition`` (or
    ``rdfs:comment``);
  - ``undeclared_type``: an individual whose type is neither declared in the graph nor standard.

It is read-only and offline. It reports; it does not choose the namespace or rewrite the vocabulary (that contract
belongs to the #1569 ontology/RDF owner).
"""
from __future__ import annotations

from importlib.resources import files
from typing import Any

from open_fdd.ontology_audit.doctor import BUILTIN_NAMESPACES, OPENFDD_NAMESPACES, STANDARD_NAMESPACES

RDF_NS = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
RDFS_NS = "http://www.w3.org/2000/01/rdf-schema#"
OWL_NS = "http://www.w3.org/2002/07/owl#"
SKOS_NS = "http://www.w3.org/2004/02/skos/core#"
CLASS_TYPES = {RDFS_NS + "Class", OWL_NS + "Class"}
PROPERTY_TYPES = {RDF_NS + "Property", OWL_NS + "ObjectProperty", OWL_NS + "DatatypeProperty",
                  OWL_NS + "AnnotationProperty"}
SKIP_TYPES = {OWL_NS + "Ontology"}
DOMAIN_STANDARD = tuple(ns for ns in STANDARD_NAMESPACES if ns not in BUILTIN_NAMESPACES)
ISSUES = ("minted_in_standard_namespace", "no_standard_parent", "no_label", "no_definition", "undeclared_type")


def shipped_vocabulary():
    """The packaged Open-FDD engineering-quantities vocabulary as an rdflib graph."""
    from rdflib import Graph

    text = files("open_fdd.ecm_engineering").joinpath("data/ofdd_engineering_quantities_v1.ttl").read_text(
        encoding="utf-8")
    return Graph().parse(data=text, format="turtle")


def check_extensions(graph, namespaces: tuple[str, ...] = OPENFDD_NAMESPACES) -> dict[str, Any]:
    """Per-term completeness records and issue counts for the extension terms ``graph`` declares."""
    from rdflib import RDF, RDFS, URIRef

    skos_def, rdfs_sub_p = URIRef(SKOS_NS + "definition"), RDFS.subPropertyOf

    def types(s) -> set[str]:
        return {str(o) for o in graph.objects(s, RDF.type)}

    def is_ext(iri: str) -> bool:
        return iri.startswith(namespaces)

    def chain(s, kind: str) -> tuple[list[str], str | None]:
        pred = RDFS.subClassOf if kind == "class" else rdfs_sub_p if kind == "property" else RDF.type
        seen, parents, frontier = {str(s)}, [], [s]
        while frontier:
            nxt = []
            for node in frontier:
                for o in graph.objects(node, pred):
                    iri = str(o)
                    if iri in seen:
                        continue
                    seen.add(iri)
                    parents.append(iri)
                    if iri.startswith(STANDARD_NAMESPACES):
                        return parents, iri
                    if is_ext(iri):
                        nxt.append(o)
            # an individual's ofdd type continues through that class's subClassOf chain
            pred = RDFS.subClassOf if kind == "individual" else pred
            frontier = nxt
        return parents, None

    terms: list[dict[str, Any]] = []
    declared = {str(s) for s in graph.subjects(RDF.type, None) if isinstance(s, URIRef)}
    for s in sorted({s for s in graph.subjects(RDF.type, None) if isinstance(s, URIRef)}, key=str):
        iri, ts = str(s), types(s)
        if ts & SKIP_TYPES:
            continue
        kind = "class" if ts & CLASS_TYPES else "property" if ts & PROPERTY_TYPES else "individual"
        if iri.startswith(DOMAIN_STANDARD):
            if kind != "individual":
                terms.append({"iri": iri, "kind": kind, "issues": ["minted_in_standard_namespace"]})
            continue
        if not is_ext(iri):
            continue
        parents, root = chain(s, kind)
        label = next(iter(graph.objects(s, RDFS.label)), None)
        definition = next(iter(graph.objects(s, skos_def)), None) or next(iter(graph.objects(s, RDFS.comment)), None)
        issues = []
        if kind == "individual":
            if not any(t in declared or t.startswith(STANDARD_NAMESPACES) for t in ts):
                issues.append("undeclared_type")
        else:
            if root is None or root.startswith(BUILTIN_NAMESPACES):
                issues.append("no_standard_parent")
            if label is None:
                issues.append("no_label")
            if definition is None:
                issues.append("no_definition")
        terms.append({"iri": iri, "kind": kind, "parents": parents, "standard_root": root,
                      "label": None if label is None else str(label),
                      "has_definition": definition is not None, "issues": issues})
    counts = {k: sum(1 for t in terms if k in t["issues"]) for k in ISSUES}
    by_kind = {k: sum(1 for t in terms if t["kind"] == k) for k in ("class", "property", "individual")}
    return {"namespaces": list(namespaces), "terms": terms, "term_counts": by_kind, "issue_counts": counts,
            "complete": not any(counts.values()),
            "note": "report only: the namespace choice and vocabulary edits belong to the #1569 ontology owner"}
