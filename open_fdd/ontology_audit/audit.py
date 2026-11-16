"""Per-requirement coverage statuses with evidence. Lexical similarity never marks a requirement as covered."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from open_fdd.ontology_audit.requirements import Requirement
from open_fdd.ontology_audit.terms import TermIndex, canonical_iri, expand

STATUSES = {
    "VERIFIED_TERM": "the candidate URI is declared in a loaded, pinned snapshot (not a semantic endorsement)",
    "MAPPING_REVIEW": "the candidate URI is in a loaded vocabulary's namespace but not declared there",
    "CANDIDATE_REVIEW": "no URI given; lexical candidates found for a reviewer to check",
    "EXTENSION_REVIEW": "no standard term found or the URI is an Open-FDD / local term: a possible extension",
    "SOURCE_UNAVAILABLE": "the vocabulary needed to check this is not loaded (missing, unreadable or hash mismatch)",
}
OPENFDD_NAMESPACES = ("urn:openfdd:ns#", "https://open-fdd.dev/model#")


@dataclass
class AuditRow:
    row: int
    category: str
    requirement: str
    candidate_uri: str
    status: str
    reason: str
    term_kind: str = ""
    label: str = ""
    evidence: str = ""
    source: str = ""
    vocabulary: str = ""
    version: str = ""
    sha256: str = ""
    candidates: list[dict[str, Any]] = field(default_factory=list)
    graph_uses: int | None = None
    reviewer_notes: str = ""
    reviewer_decision: str = ""

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def _from_term(row: AuditRow, term) -> None:
    row.term_kind, row.label, row.evidence = term.kind, term.label, term.definition
    row.source, row.vocabulary, row.version, row.sha256 = term.source, term.vocabulary, term.version, term.sha256


def _graph_uses(graph, iri: str) -> int:
    """Uses as predicate or object; ``graph`` is already normalized (canonical Haystack IRIs)."""
    from rdflib import URIRef

    u = URIRef(canonical_iri(iri))
    return sum(1 for _ in graph.triples((None, None, u))) + sum(1 for _ in graph.triples((None, u, None)))


def audit_requirements(requirements: Iterable[Requirement], sources: list, graph=None, *,
                       candidate_limit: int = 3) -> list[AuditRow]:
    """Check each requirement against the loaded sources (and count its URI's uses in ``graph`` when given)."""
    index = TermIndex.build(sources)
    if graph is not None:
        from open_fdd.ontology_audit.doctor import normalize_graph

        graph = normalize_graph(graph)
    any_loaded = any(s.loaded for s in sources)
    out = []
    for req in requirements:
        uri = expand(req.candidate_uri) if req.candidate_uri else ""
        row = AuditRow(row=req.row, category=req.category, requirement=req.requirement, candidate_uri=uri,
                       status="", reason="", reviewer_notes=req.reviewer_notes,
                       reviewer_decision=req.extra.get("reviewer_decision", ""))
        if uri and graph is not None:
            row.graph_uses = _graph_uses(graph, uri)
        if uri and uri.startswith(OPENFDD_NAMESPACES):
            row.status, row.reason = "EXTENSION_REVIEW", "Open-FDD term: an application extension, review before use"
        elif uri:
            term = index.lookup(uri)
            owner = index.owner(uri)
            if term is not None:
                row.status, row.reason = "VERIFIED_TERM", f"declared as {term.kind} in {term.vocabulary} {term.version}"
                _from_term(row, term)
            elif owner is not None and not owner.loaded:
                row.status, row.reason = "SOURCE_UNAVAILABLE", f"{owner.vocabulary}: {owner.detail}"
                row.source, row.vocabulary, row.version = owner.name, owner.vocabulary, owner.version
            elif owner is not None:
                row.status, row.reason = "MAPPING_REVIEW", f"not declared in {owner.vocabulary} {owner.version}"
                row.source, row.vocabulary, row.version, row.sha256 = (owner.name, owner.vocabulary, owner.version,
                                                                       owner.sha256)
            elif not any_loaded:
                row.status, row.reason = "SOURCE_UNAVAILABLE", "no vocabulary loaded"
            else:
                row.status, row.reason = "EXTENSION_REVIEW", "namespace is not one of the loaded vocabularies"
        elif not any_loaded:
            row.status, row.reason = "SOURCE_UNAVAILABLE", "no vocabulary loaded to search"
        if not uri or row.status in {"MAPPING_REVIEW", "EXTENSION_REVIEW"} and not uri.startswith(OPENFDD_NAMESPACES):
            if any_loaded:
                hits = index.candidates(f"{req.requirement} {req.description}", limit=candidate_limit)
                row.candidates = [{"iri": t.iri, "score": s, "label": t.label, "kind": t.kind, "vocabulary": t.vocabulary}
                                  for s, t in hits]
                if not uri:
                    row.status = "CANDIDATE_REVIEW" if hits else "EXTENSION_REVIEW"
                    row.reason = ("lexical candidates only: check the meaning" if hits
                                  else "no standard term found by label")
        out.append(row)
    return out


def summary(rows: list[AuditRow]) -> dict[str, int]:
    counts = {k: 0 for k in STATUSES}
    for r in rows:
        counts[r.status] = counts.get(r.status, 0) + 1
    return counts
