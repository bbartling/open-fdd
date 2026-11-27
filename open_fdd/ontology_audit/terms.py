"""Term index over loaded vocabularies: exact URI lookup (with Haystack IRI normalization) and lexical candidates."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

# Published Project Haystack defs. The canonical IRI is versioned; an unversioned export IRI maps to it.
HAYSTACK_VERSION = "4.0.0"
# Local name starts with a letter so a namespace ending in ``4.0.0#`` is not read as a term.
HAYSTACK_RE = re.compile(
    r"^https?://(?:www\.)?project-haystack\.org/def/([A-Za-z0-9]+)/(?:[0-9][0-9.]*#)?([A-Za-z][A-Za-z0-9_-]*)$")
HAYSTACK_NS_RE = re.compile(
    r"^(https?://(?:www\.)?project-haystack\.org/def/[A-Za-z0-9]+/)(?:[0-9][0-9.]*#)?$")

# Well-known prefixes for CURIEs in a requirements sheet (``brick:Supply_Air_Temperature_Sensor``).
PREFIXES = {
    "brick": "https://brickschema.org/schema/Brick#",
    "ref": "https://brickschema.org/schema/Brick/ref#",
    "tag": "https://brickschema.org/schema/BrickTag#",
    "s223": "http://data.ashrae.org/standard223#",
    "ph": f"https://project-haystack.org/def/ph/{HAYSTACK_VERSION}#",
    "phIoT": f"https://project-haystack.org/def/phIoT/{HAYSTACK_VERSION}#",
    "phScience": f"https://project-haystack.org/def/phScience/{HAYSTACK_VERSION}#",
    "phIct": f"https://project-haystack.org/def/phIct/{HAYSTACK_VERSION}#",
    "qudt": "http://qudt.org/schema/qudt/",
    "unit": "http://qudt.org/vocab/unit/",
    "quantitykind": "http://qudt.org/vocab/quantitykind/",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    "owl": "http://www.w3.org/2002/07/owl#",
    "sh": "http://www.w3.org/ns/shacl#",
    "skos": "http://www.w3.org/2004/02/skos/core#",
    "schema": "https://schema.org/",
    "ofdd": "urn:openfdd:ns#",
}

CLASS_TYPES = {
    "http://www.w3.org/2002/07/owl#Class", "http://www.w3.org/2000/01/rdf-schema#Class",
    "http://data.ashrae.org/standard223#Class",
}
PROPERTY_TYPES = {
    "http://www.w3.org/1999/02/22-rdf-syntax-ns#Property", "http://www.w3.org/2002/07/owl#ObjectProperty",
    "http://www.w3.org/2002/07/owl#DatatypeProperty", "http://www.w3.org/2002/07/owl#AnnotationProperty",
    "http://data.ashrae.org/standard223#Relation",
}
SHAPE_TYPES = {"http://www.w3.org/ns/shacl#NodeShape", "http://www.w3.org/ns/shacl#PropertyShape"}
LABELS = ("http://www.w3.org/2000/01/rdf-schema#label", "http://www.w3.org/2004/02/skos/core#prefLabel")
DEFINITIONS = ("http://www.w3.org/2004/02/skos/core#definition", "http://www.w3.org/2000/01/rdf-schema#comment")
STOPWORDS = {"a", "an", "and", "the", "of", "for", "to", "in", "on", "or", "by", "with", "is", "per", "its", "from",
             "as", "at", "be", "each", "that", "this", "which", "it", "one", "two"}


def haystack_iri(library: str, local: str = "") -> str:
    """Versioned Haystack def IRI: ``https://project-haystack.org/def/<library>/4.0.0#<local>``."""
    return f"https://project-haystack.org/def/{library}/{HAYSTACK_VERSION}#{local}"


def canonical_iri(iri: str) -> str:
    """Haystack def IRIs in the published 4.0.0 form (``.../def/phIoT/4.0.0#ahu``).

    An unversioned IRI (``.../def/phIoT/ahu``) and any other defs version map to that form.
    """
    m = HAYSTACK_RE.match(iri)
    return haystack_iri(m.group(1), m.group(2)) if m else iri


def canonical_namespace(ns: str) -> str:
    """A Haystack prefix namespace in the same versioned form, or ``ns`` unchanged."""
    m = HAYSTACK_NS_RE.match(ns)
    if m:
        library = m.group(1).rstrip("/").rsplit("/", 1)[-1]
        return haystack_iri(library)
    return canonical_iri(ns) if HAYSTACK_RE.match(ns) else ns


def split_iri(iri: str) -> tuple[str, str]:
    """``(namespace, local name)``: split after the last ``#``, else the last ``/``, else the last ``:``."""
    for sep in ("#", "/", ":"):
        i = iri.rfind(sep)
        if i >= 0 and i < len(iri) - 1:
            return iri[: i + 1], iri[i + 1:]
    return "", iri


def expand(value: str) -> str:
    """Expand a CURIE with a well-known prefix; full IRIs (and ``<...>``) pass through."""
    value = value.strip().strip("<>")
    if not value or "://" in value or value.startswith("urn:"):
        return value
    prefix, _, local = value.partition(":")
    return PREFIXES[prefix] + local if local and prefix in PREFIXES else value


def tokens(text: str) -> set[str]:
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text or "")
    return {t for t in re.split(r"[^A-Za-z0-9]+", text.lower()) if t and t not in STOPWORDS}


@dataclass(frozen=True)
class Term:
    iri: str
    kind: str
    label: str
    definition: str
    source: str
    vocabulary: str
    version: str
    sha256: str

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def _first_literal(graph, subject, predicates: Iterable[str]) -> str:
    from rdflib import Literal, URIRef

    for pred in predicates:
        values = [o for o in graph.objects(subject, URIRef(pred)) if isinstance(o, Literal)]
        if values:
            values.sort(key=lambda o: (o.language not in (None, "en"), str(o)))
            return " ".join(str(values[0]).split())
    return ""


class TermIndex:
    """Declared terms of the loaded sources (a subject with an ``rdf:type`` inside the source's namespaces)."""

    def __init__(self, terms: dict[str, Term], owners: list[tuple[str, Any]]):
        self.terms = terms
        self._owners = owners  # (canonical namespace prefix, LoadedSource), longest first
        self._tokens = {iri: tokens(t.label) | tokens(split_iri(iri)[1]) for iri, t in terms.items()}

    @classmethod
    def build(cls, sources: Iterable[Any]) -> "TermIndex":
        from rdflib import RDF, URIRef

        terms: dict[str, Term] = {}
        owners: list[tuple[str, Any]] = []
        for src in sources:
            for ns in src.namespaces:
                owners.append((canonical_iri(ns), src))
            if not src.loaded:
                continue
            g = src.graph
            spaces = [canonical_iri(ns) for ns in src.namespaces]
            for subject in sorted({s for s in g.subjects(RDF.type, None) if isinstance(s, URIRef)}, key=str):
                iri = canonical_iri(str(subject))
                if spaces and not any(iri.startswith(ns) for ns in spaces):
                    continue
                if iri in terms:
                    continue
                types = {str(t) for t in g.objects(subject, RDF.type)}
                kind = ("class" if types & CLASS_TYPES else "property" if types & PROPERTY_TYPES
                        else "shape" if types & SHAPE_TYPES else "individual")
                terms[iri] = Term(iri=iri, kind=kind, label=_first_literal(g, subject, LABELS),
                                  definition=_first_literal(g, subject, DEFINITIONS)[:500], source=src.name,
                                  vocabulary=src.vocabulary, version=src.version, sha256=src.sha256)
        owners.sort(key=lambda kv: (-len(kv[0]), not kv[1].loaded))
        return cls(terms, owners)

    def lookup(self, iri: str) -> Term | None:
        return self.terms.get(canonical_iri(expand(iri)))

    def owner(self, iri: str):
        """The source whose namespace the IRI is in (loaded or not), else None."""
        iri = canonical_iri(expand(iri))
        for ns, src in self._owners:
            if iri.startswith(ns):
                return src
        return None

    def candidates(self, text: str, limit: int = 3, min_score: float = 0.34) -> list[tuple[float, Term]]:
        """Lexical candidates by token overlap (Jaccard). A match is a lead for review, never evidence of meaning."""
        want = tokens(text)
        if not want:
            return []
        scored = []
        for iri, toks in self._tokens.items():
            if not toks or not (want & toks):
                continue
            score = len(want & toks) / len(want | toks)
            if score >= min_score:
                scored.append((round(score, 3), iri))
        scored.sort(key=lambda kv: (-kv[0], kv[1]))
        return [(score, self.terms[iri]) for score, iri in scored[:limit]]
