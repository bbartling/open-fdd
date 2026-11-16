"""Read-only model doctor: which terms a building graph uses, where they come from, and identity / history checks.

Every class (``rdf:type`` object), predicate and Haystack tag (``ph:hasTag`` object) the graph uses is classified:

* ``standard``: RDF / RDFS / OWL / SHACL / SKOS / schema.org / QUDT / Brick / ASHRAE 223 / Project Haystack;
* ``open-fdd``: ``urn:openfdd:ns#`` (and the legacy ``https://open-fdd.dev/model#``) plus the terms the Open-FDD NF
  export writes in the graph's ``local:`` namespace (``nfClass``, ``ruleRef``, ``ofddRole``, the history stores);
* ``site-specific``: everything else (for example a site's own marker tags).

A standard term is ``defined`` / ``undefined`` against the loaded snapshot of its vocabulary, else ``unchecked``.
Haystack IRIs are compared in one form, so the NF export's unversioned ``.../def/phIoT/ahu`` matches the defs file's
``.../def/phIoT/4.0.0#ahu``.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from importlib.resources import files
from typing import Any

from open_fdd.ontology_audit.terms import TermIndex, canonical_iri, split_iri

BUILTIN_NAMESPACES = (
    "http://www.w3.org/1999/02/22-rdf-syntax-ns#", "http://www.w3.org/2000/01/rdf-schema#",
    "http://www.w3.org/2002/07/owl#", "http://www.w3.org/2001/XMLSchema#", "http://www.w3.org/ns/shacl#",
    "http://www.w3.org/2004/02/skos/core#", "http://purl.org/dc/terms/", "https://schema.org/", "http://schema.org/",
)
STANDARD_NAMESPACES = BUILTIN_NAMESPACES + (
    "https://brickschema.org/schema/", "http://data.ashrae.org/standard223", "https://project-haystack.org/def/",
    "http://qudt.org/", "https://w3id.org/rec#",
)
OPENFDD_NAMESPACES = ("urn:openfdd:ns#", "https://open-fdd.dev/model#")
# Terms the Open-FDD NF export (shared/static/model.js) writes in the graph's local: namespace.
OPENFDD_LOCAL_TERMS = {"nfClass", "ruleRef", "ofddRole", "store_nf", "store_timescaledb"}

H = "https://project-haystack.org/def/"
REF = "https://brickschema.org/schema/Brick/ref#"
COMPETENCY_QUERIES: dict[str, str] = {
    "equipment_points": f"""
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX phIoT: <{H}phIoT/>
PREFIX ref: <{REF}>
SELECT ?equip ?equipLabel ?point ?pointLabel ?historyId WHERE {{
  ?point phIoT:equipRef ?equip .
  OPTIONAL {{ ?equip rdfs:label ?equipLabel }}
  OPTIONAL {{ ?point rdfs:label ?pointLabel }}
  OPTIONAL {{ ?point ref:hasExternalReference/ref:hasTimeseriesId ?historyId }}
}} ORDER BY ?equipLabel ?pointLabel ?point""",
    "ahu_discharge_air_temp_sensors": f"""
PREFIX ph: <{H}ph/>
PREFIX phIoT: <{H}phIoT/>
PREFIX phScience: <{H}phScience/>
PREFIX ref: <{REF}>
SELECT ?equip ?point ?historyId WHERE {{
  ?equip ph:hasTag phIoT:ahu .
  ?point phIoT:equipRef ?equip ; ph:hasTag phIoT:sensor, phIoT:discharge, phScience:air, phScience:temp .
  OPTIONAL {{ ?point ref:hasExternalReference/ref:hasTimeseriesId ?historyId }}
}} ORDER BY ?equip ?point""",
    "fault_results": f"""
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX phIoT: <{H}phIoT/>
PREFIX ref: <{REF}>
SELECT ?point ?rule ?equip ?historyId WHERE {{
  ?point ?ruleProp ?rule .
  FILTER(STRENDS(STR(?ruleProp), "ruleRef"))
  OPTIONAL {{ ?point phIoT:equipRef ?equip }}
  OPTIONAL {{ ?point ref:hasExternalReference/ref:hasTimeseriesId ?historyId }}
}} ORDER BY ?rule ?point""",
    "non_haystack_tags": f"""
PREFIX ph: <{H}ph/>
SELECT ?tag (COUNT(?entity) AS ?uses) WHERE {{
  ?entity ph:hasTag ?tag .
  FILTER(!STRSTARTS(STR(?tag), "{H}"))
}} GROUP BY ?tag ORDER BY ?tag""",
}


def normalize_graph(graph):
    """A copy with every Haystack IRI in canonical form (the source graph is not changed)."""
    from rdflib import Graph, URIRef

    def fix(node):
        return URIRef(canonical_iri(str(node))) if isinstance(node, URIRef) else node

    out = Graph()
    for prefix, ns in graph.namespaces():
        out.bind(prefix, canonical_iri(str(ns)) if "project-haystack.org" in str(ns) else ns, override=True,
                 replace=True)
    for s, p, o in graph:
        out.add((fix(s), fix(p), fix(o)))
    return out


def run_query(graph, name_or_sparql: str) -> list[dict[str, str]]:
    """Run a named competency query (or any SPARQL SELECT) on the normalized graph; rows of strings."""
    query = COMPETENCY_QUERIES.get(name_or_sparql, name_or_sparql)
    result = normalize_graph(graph).query(query)
    names = [str(v) for v in result.vars]
    return [{n: ("" if row[i] is None else str(row[i])) for i, n in enumerate(names)} for row in result]


def _openfdd_vocab_terms() -> set[str]:
    from rdflib import Graph, RDF, URIRef

    text = files("open_fdd.ecm_engineering").joinpath("data/ofdd_engineering_quantities_v1.ttl").read_text(
        encoding="utf-8")
    g = Graph().parse(data=text, format="turtle")
    return {str(s) for s in g.subjects(RDF.type, None) if isinstance(s, URIRef)}


@dataclass
class DoctorReport:
    triples: int
    local_namespace: str
    terms: list[dict[str, Any]] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    points: int = 0
    role_bindings: list[dict[str, Any]] = field(default_factory=list)
    queries: dict[str, list[dict[str, str]]] = field(default_factory=dict)
    sources: list[dict[str, Any]] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        c = Counter(f"{t['classification']}/{t['defined']}" for t in self.terms)
        return dict(sorted(c.items()))

    def to_dict(self) -> dict[str, Any]:
        return {"triples": self.triples, "local_namespace": self.local_namespace, "counts": self.counts(),
                "points": self.points, "problems": self.problems, "terms": self.terms,
                "role_bindings": self.role_bindings, "queries": self.queries, "sources": self.sources}


def _local_namespace(graph, local_ns: str | None) -> str:
    if local_ns:
        return local_ns
    for prefix, ns in graph.namespaces():
        if prefix == "local":
            return str(ns)
    return ""


def doctor(graph, sources: list | None = None, *, local_ns: str | None = None) -> DoctorReport:
    """Inventory and check a building graph. ``sources`` (from ``load_sources``) lets standard terms be checked."""
    from rdflib import RDF, BNode, URIRef

    sources = sources or []
    index = TermIndex.build(sources)
    g = normalize_graph(graph)
    local = _local_namespace(graph, local_ns)
    has_tag = URIRef(H + "ph/hasTag")
    typed = {s for s in g.subjects(RDF.type, None) if not isinstance(s, BNode)}
    ofdd_vocab = _openfdd_vocab_terms()

    used: dict[tuple[str, str], int] = Counter()
    for s, p, o in g:
        used[(str(p), "predicate")] += 1
        if p == RDF.type and isinstance(o, URIRef):
            used[(str(o), "class")] += 1
        elif p == has_tag and isinstance(o, URIRef):
            used[(str(o), "tag")] += 1

    report = DoctorReport(triples=len(g), local_namespace=local,
                          sources=[{k: v for k, v in s.to_dict().items() if k != "namespaces"} for s in sources])
    for (iri, role), uses in sorted(used.items()):
        ns, name = split_iri(iri)
        if iri.startswith(OPENFDD_NAMESPACES) or (local and iri.startswith(local) and
                                                    iri[len(local):] in OPENFDD_LOCAL_TERMS):
            cls = "open-fdd"
            defined = "defined" if (iri in ofdd_vocab or iri[len(local):] in OPENFDD_LOCAL_TERMS) else "undefined"
            vocab = "Open-FDD"
        elif iri.startswith(STANDARD_NAMESPACES):
            cls = "standard"
            owner = index.owner(iri)
            if iri.startswith(BUILTIN_NAMESPACES):
                defined, vocab = "builtin", ns
            elif owner is None or not owner.loaded:
                defined, vocab = "unchecked", owner.vocabulary if owner else ns
            else:
                defined = "defined" if index.lookup(iri) is not None else "undefined"
                vocab = f"{owner.vocabulary} {owner.version}"
        else:
            cls, vocab = "site-specific", "local" if local and iri.startswith(local) else ns
            defined = "declared in graph" if URIRef(iri) in typed else "undefined"
        report.terms.append({"iri": iri, "name": name, "used_as": role, "uses": uses, "classification": cls,
                             "vocabulary": vocab, "defined": defined})
        if defined == "undefined":
            report.problems.append(f"undefined {cls} {role}: {iri}")

    # identity and history links
    ts_owner: dict[str, list[str]] = defaultdict(list)
    point_cls = URIRef(H + "phIoT/point")
    points = sorted({s for s in g.subjects(RDF.type, point_cls)}, key=str)
    report.points = len(points)
    ext, tsid = URIRef(REF + "hasExternalReference"), URIRef(REF + "hasTimeseriesId")
    for pt in points:
        ids = [str(i) for r in g.objects(pt, ext) for i in g.objects(r, tsid)]
        if not ids:
            report.problems.append(f"point without a history reference: {pt}")
        for i in set(ids):
            ts_owner[i].append(str(pt))
    for i, owners in sorted(ts_owner.items()):
        if len(owners) > 1:
            report.problems.append(f"history id {i} shared by {len(owners)} points: {', '.join(sorted(owners))}")
    for s, p, o in g:
        if str(p).endswith("Ref") and isinstance(o, URIRef) and o not in typed and str(p).startswith(H):
            report.problems.append(f"dangling reference: {s} {split_iri(str(p))[1]} {o}")

    # explicit Open-FDD roles: several sensors may share one role on one equipment and keep their own identity
    role_prop = URIRef(local + "ofddRole") if local else None
    if role_prop is not None:
        by_role: dict[tuple[str, str], list[str]] = defaultdict(list)
        for pt, role in g.subject_objects(role_prop):
            equip = next(iter(g.objects(pt, URIRef(H + "phIoT/equipRef"))), None)
            by_role[(str(equip or ""), str(role))].append(str(pt))
        report.role_bindings = [{"equip": e, "role": r, "points": sorted(p)} for (e, r), p in sorted(by_role.items())]

    for name in COMPETENCY_QUERIES:
        report.queries[name] = run_query(graph, name)
    report.problems.sort()
    return report
