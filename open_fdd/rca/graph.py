"""RDF topology loader and upstream traversal for HVAC root-cause analysis (RCA).

The feeder graph is ASHRAE 223P: equipment and other connectables, connection points,
and ``s223:Connection`` (the connection between connectables). Direction follows
outlet connection point → connection → inlet connection point, plus
``s223:connectedTo`` / ``s223:connectedFrom`` and ``s223:connectsFrom`` /
``s223:connectsTo``. A zone is not itself the connectable: traversal follows
``s223:hasDomainSpace`` to member spaces and nested zones, then their physical
feeders. Membership is not stored as a feeder edge. Properties on equipment are
matched to ``roles/openfdd-roles.json``.

Haystack tags are an optional overlay for labels, site membership and point
ownership. They are stored as Haystack defs 4.0.0 IRIs
(``https://project-haystack.org/def/<vocab>/4.0.0#<name>``). Unversioned Haystack
IRIs are rewritten to that form on load and are not used as feeder edges.

SPARQL property paths run on pyoxigraph 0.5.13. rdflib 7.6.0 parses Turtle only.

Sparse graphs report ``unknown_upstream`` instead of guessing a missing link.
A known limit: equipment ownership is not inferred from ``s223:cnx`` alone when
the model has no ``s223:hasConnectionPoint``.
"""

from __future__ import annotations

import re
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from open_fdd.ontology_audit.terms import PREFIXES, split_iri

S223 = PREFIXES["s223"]
S223_IMPORT = "http://data.ashrae.org/standard223/1.0/model/all"
HAYSTACK_VERSION = "4.0.0"
RDF_NS = PREFIXES["rdf"]
RDFS_NS = PREFIXES["rdfs"]
QUDT_NS = PREFIXES["qudt"]
QK_NS = PREFIXES["quantitykind"]

_HAYSTACK_IRI = re.compile(
    r"^https?://(?:www\.)?project-haystack\.org/def/([A-Za-z0-9]+)/(?:[0-9][0-9.]*#)?(.+)$"
)


def versioned_haystack_iri(iri: str) -> str:
    """Rewrite a Haystack def IRI to the pinned 4.0.0 hash form."""
    match = _HAYSTACK_IRI.match(iri)
    if not match:
        return iri
    return f"https://project-haystack.org/def/{match.group(1)}/{HAYSTACK_VERSION}#{match.group(2)}"


def _haystack_ns(vocab: str) -> str:
    return f"https://project-haystack.org/def/{vocab}/{HAYSTACK_VERSION}#"


PH = _haystack_ns("ph")
PH_IOT = _haystack_ns("phIoT")

SOURCE_ROOT_MARKERS = frozenset(
    {
        "chiller",
        "boiler",
        "plant",
        "chilledwaterplant",
        "hotwaterplant",
        "chilled-water-plant",
        "hot-water-plant",
        "coolingtower",
        "cooling_tower",
        "weatherstation",
        "weather",
        "meter",
        "mainsupply",
    }
)

POINT_MARKERS = frozenset({"point", "sensor", "cmd", "sp", "property", "observableproperty"})

# Schema/vocabulary IRIs that appear in bundled ontology dumps, not site instances.
VOCAB_IRI_PREFIXES = (
    "https://project-haystack.org/def/",
    "https://brickschema.org/schema/",
    "http://data.ashrae.org/standard223",
    "http://www.w3.org/",
    "http://purl.org/dc/",
    "http://xmlns.com/foaf/",
)

# Predicate local names (any namespace) that carry alternate equipment/point identifiers.
ALIAS_PREDICATE_LOCAL_NAMES = frozenset(
    {
        "equipmentid",
        "equipid",
        "pointid",
        "sourceref",
        "openfddkey",
        "id",
        "ref",
        "navname",
        "hastimeseriesid",
        "siteid",
    }
)
SITE_ID_PREDICATE_LOCAL_NAMES = frozenset({"siteid", "site_id"})

UPSTREAM_PATH_SPARQL_TEMPLATE = """PREFIX s223: <http://data.ashrae.org/standard223#>
SELECT DISTINCT ?upstream WHERE {{
  ?upstream (s223:connectedTo | ^s223:connectedFrom)+ <{target_iri}> .
}}"""

SparqlRunner = Callable[[str], list[dict[str, str]]]


@dataclass(frozen=True)
class GraphNode:
    """Equipment, space, weather station, or point node in the site RDF graph."""

    iri: str
    node_id: str
    label: str
    site_id: str = ""
    site_iri: str = ""
    equip_types: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    is_source_root: bool = False
    is_point: bool = False
    aliases: tuple[str, ...] = ()
    site_ids: tuple[str, ...] = ()
    property_roles: tuple[str, ...] = ()
    aspects: tuple[str, ...] = ()


@dataclass(frozen=True)
class UpstreamEdge:
    """Directed edge from ``upstream_iri`` feeding ``downstream_iri``."""

    upstream_iri: str
    downstream_iri: str
    predicate: str
    inferred: bool = False
    confidence: float | None = None
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class UpstreamHop:
    """Reachable upstream ancestor with shortest hop count and path from symptom."""

    node: GraphNode
    hop: int
    path: tuple[str, ...]  # ordered upstream -> ... -> symptom node_id
    relations: tuple[str, ...]
    inferred: bool = False
    edge_confidences: tuple[float, ...] = ()
    topology_source: str = "modeled"


@dataclass
class UpstreamTraversal:
    """Result of walking upstream from a symptom equipment or node."""

    target_query: str
    target: GraphNode | None
    ancestors: list[UpstreamHop] = field(default_factory=list)
    unknown_upstream: bool = False
    upstream_status: str = "traced"  # traced | traced_inferred | partial_unknown_upstream | unknown_upstream | target_not_found
    unknown_upstream_at: list[str] = field(default_factory=list)
    sparql_ancestors: list[str] = field(default_factory=list)
    topology_source: str = "modeled"
    inferred_edges_used: int = 0


def _norm_token(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum() or ch in ("-", "_"))


def _local_id(iri: str) -> str:
    _, name = split_iri(iri)
    # Handle urn:openfdd:example:plant:ahu-1 style IRIs where split_iri splits on ':'
    return name


def _is_source_root(equip_types: Iterable[str], tags: Iterable[str]) -> bool:
    for item in (*equip_types, *tags):
        tok = _norm_token(split_iri(item)[1])
        if tok in SOURCE_ROOT_MARKERS or tok.replace("_", "").replace("-", "") in SOURCE_ROOT_MARKERS:
            return True
    return False


def _is_point(equip_types: Iterable[str], tags: Iterable[str]) -> bool:
    for item in (*equip_types, *tags):
        tok = _norm_token(split_iri(item)[1])
        if tok in POINT_MARKERS or tok.endswith(
            ("property", "_sensor", "_setpoint", "_command", "_status", "_alarm", "_point", "sensor", "setpoint")
        ):
            return True
        if tok.endswith("connectionpoint"):
            return True
    return False


def _pred_local_name(iri: str) -> str:
    return split_iri(iri)[1]


def _is_vocab_iri(iri: str) -> bool:
    lower = iri.lower()
    return any(lower.startswith(prefix) for prefix in VOCAB_IRI_PREFIXES)


def _identifier_forms(value: str) -> tuple[str, ...]:
    """Exact identifier plus Haystack forms with a leading ``@`` stripped."""
    text = value.strip()
    if not text:
        return ()
    forms = [text]
    if text.startswith("@"):
        forms.append(text[1:])
    return tuple(dict.fromkeys(forms))


def _unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(v for v in values if v))


class TopologyGraph:
    """Normalized RDF + adjacency index for multi-vocabulary upstream HVAC traversal."""

    def __init__(
        self,
        nodes: dict[str, GraphNode],
        upstream_edges: dict[str, list[UpstreamEdge]],
        *,
        rdflib_graph: Any = None,
        sparql_triples: list[tuple[str, str, str]] | None = None,
        members: dict[str, tuple[str, ...]] | None = None,
    ) -> None:
        self.nodes = nodes
        self.upstream_edges = upstream_edges
        self.rdflib_graph = rdflib_graph
        self.sparql_triples = list(sparql_triples or [])
        self.members = {k: tuple(v) for k, v in (members or {}).items()}
        self._sparql_store: Any = None
        self._sparql_import_failed = False
        self._alias_exact: dict[str, list[str]] = {}
        self._alias_ci: dict[str, list[str]] = {}
        for iri, node in nodes.items():
            for key in (node.iri, node.node_id, node.label, *node.aliases):
                self._index_alias(key, iri)

    def _index_alias(self, key: str, iri: str) -> None:
        if not key:
            return
        bucket = self._alias_exact.setdefault(key, [])
        if iri not in bucket:
            bucket.append(iri)
        low = key.lower()
        bucket_ci = self._alias_ci.setdefault(low, [])
        if iri not in bucket_ci:
            bucket_ci.append(iri)

    def _site_tokens(self, node: GraphNode, *, _seen: frozenset[str] | None = None) -> set[str]:
        tokens = {node.site_id, _local_id(node.site_iri), *node.site_ids}
        out = {t.lower() for t in tokens if t}
        if out:
            return out
        seen = set(_seen or ())
        if node.iri in seen:
            return set()
        seen.add(node.iri)
        owner_sets: list[set[str]] = []
        for edge in self.upstream_edges.get(node.iri, ()):
            parent = self.nodes.get(edge.upstream_iri)
            if parent is None or parent.iri in seen:
                continue
            parent_tokens = self._site_tokens(parent, _seen=frozenset(seen))
            if parent_tokens:
                owner_sets.append(parent_tokens)
        if not owner_sets:
            return set()
        return set.intersection(*owner_sets)

    def _filter_iris_by_site(self, iris: list[str], site_id: str | None) -> list[str]:
        if not site_id:
            return list(iris)
        wanted = site_id.lower()
        return [iri for iri in iris if wanted in self._site_tokens(self.nodes[iri])]

    def iris_matching_alias(
        self,
        identifier: str,
        *,
        site_id: str | None = None,
        ignore_case: bool = False,
    ) -> list[str]:
        """Return IRIs whose aliases match ``identifier``, optionally case-insensitively."""
        if not identifier:
            return []
        if ignore_case:
            iris = list(self._alias_ci.get(identifier.lower(), ()))
        else:
            iris = list(self._alias_exact.get(identifier, ()))
            if identifier in self.nodes and identifier not in iris:
                iris.insert(0, identifier)
        return self._filter_iris_by_site(iris, site_id)

    def with_inferred_edges(self, inferred_edges: Iterable[Any]) -> TopologyGraph:
        """Return a new TopologyGraph adding inferred edges without mutating this graph."""
        nodes = dict(self.nodes)
        edges: dict[str, list[UpstreamEdge]] = {k: list(v) for k, v in self.upstream_edges.items()}
        existing_pairs = {
            (e.upstream_iri, e.downstream_iri)
            for edge_list in edges.values()
            for e in edge_list
        }
        for inf in inferred_edges:
            up_iri = str(inf.upstream_iri)
            dn_iri = str(inf.downstream_iri)
            if not up_iri or not dn_iri or up_iri == dn_iri:
                continue
            if (up_iri, dn_iri) in existing_pairs:
                continue
            existing_pairs.add((up_iri, dn_iri))
            if up_iri not in nodes:
                uid = getattr(inf, "upstream_id", "") or _local_id(up_iri)
                ulab = getattr(inf, "upstream_label", "") or uid
                nodes[up_iri] = GraphNode(iri=up_iri, node_id=uid, label=ulab)
            if dn_iri not in nodes:
                did = getattr(inf, "downstream_id", "") or _local_id(dn_iri)
                dlab = getattr(inf, "downstream_label", "") or did
                nodes[dn_iri] = GraphNode(iri=dn_iri, node_id=did, label=dlab)
            pred = getattr(inf, "predicate", "s223:connectedTo") or "s223:connectedTo"
            edges.setdefault(dn_iri, []).append(
                UpstreamEdge(
                    upstream_iri=up_iri,
                    downstream_iri=dn_iri,
                    predicate=f"{pred} (inferred)",
                    inferred=True,
                    confidence=getattr(inf, "confidence", None),
                    evidence=tuple(getattr(inf, "evidence", ()) or ()),
                )
            )
        return TopologyGraph(
            nodes=nodes,
            upstream_edges=edges,
            rdflib_graph=self.rdflib_graph,
            sparql_triples=self.sparql_triples,
            members=self.members,
        )

    @classmethod
    def from_rdflib(cls, graph: Any) -> TopologyGraph:
        """Build a ``TopologyGraph`` from an ``rdflib.Graph``.

        Haystack IRIs are rewritten to defs 4.0.0. Feeder edges come from 223P
        connections. Haystack ``siteRef``, ``hasTag`` and ``dis`` stay as lookup
        and display. ``equipRef`` and ``s223:hasProperty`` record point ownership.
        """
        from rdflib import Graph, Literal, URIRef

        from open_fdd.rca.role_index import match_property_pattern

        def fix(node: Any) -> Any:
            if isinstance(node, URIRef):
                return URIRef(versioned_haystack_iri(str(node)))
            return node

        g = Graph()
        for prefix, ns in graph.namespaces():
            ns_s = str(ns)
            g.bind(prefix, URIRef(versioned_haystack_iri(ns_s) if "project-haystack.org" in ns_s else ns_s), override=True, replace=True)
        for s, p, o in graph:
            g.add((fix(s), fix(p), fix(o) if isinstance(o, URIRef) else o))

        rdf_type = URIRef(RDF_NS + "type")
        rdfs_label = URIRef(RDFS_NS + "label")
        has_tag = URIRef(PH + "hasTag")
        site_ref = URIRef(PH_IOT + "siteRef")
        dis_pred = URIRef(PH + "dis")
        has_cp = URIRef(S223 + "hasConnectionPoint")
        cnx = URIRef(S223 + "cnx")
        connects_from = URIRef(S223 + "connectsFrom")
        connects_to = URIRef(S223 + "connectsTo")
        connected_to = URIRef(S223 + "connectedTo")
        connected_from = URIRef(S223 + "connectedFrom")
        has_property = URIRef(S223 + "hasProperty")
        has_domain = URIRef(S223 + "hasDomainSpace")
        of_medium = URIRef(S223 + "ofMedium")
        has_medium = URIRef(S223 + "hasMedium")
        has_aspect = URIRef(S223 + "hasAspect")
        has_qk = URIRef(QUDT_NS + "hasQuantityKind")
        equip_ref = URIRef(PH_IOT + "equipRef")
        outlet_cp = URIRef(S223 + "OutletConnectionPoint")
        inlet_cp = URIRef(S223 + "InletConnectionPoint")

        label_preds = (rdfs_label, dis_pred)
        entities: set[str] = set()
        types_by_s: dict[str, list[str]] = {}
        tags_by_s: dict[str, list[str]] = {}
        labels_by_pred: dict[str, dict[str, list[str]]] = {str(pred): {} for pred in label_preds}
        sites_by_s: dict[str, str] = {}
        aliases_by_s: dict[str, list[str]] = {}
        site_ids_literal_by_s: dict[str, list[str]] = {}
        sparql_triples: list[tuple[str, str, str]] = []
        aspects_by_s: dict[str, set[str]] = {}
        mediums_by_s: dict[str, set[str]] = {}
        qk_by_s: dict[str, set[str]] = {}

        for s, p, o in g:
            if not isinstance(s, URIRef):
                continue
            s_iri = str(s)
            if isinstance(o, URIRef):
                sparql_triples.append((s_iri, str(p), str(o)))
            if p == rdf_type and isinstance(o, URIRef):
                entities.add(s_iri)
                types_by_s.setdefault(s_iri, []).append(str(o))
            elif p == has_tag and isinstance(o, URIRef):
                entities.add(s_iri)
                tags_by_s.setdefault(s_iri, []).append(str(o))
            elif p in label_preds and isinstance(o, Literal):
                entities.add(s_iri)
                labels_by_pred[str(p)].setdefault(s_iri, []).append(str(o))
            elif p == site_ref and isinstance(o, URIRef):
                entities.add(s_iri)
                sites_by_s[s_iri] = str(o)
            elif p == has_aspect and isinstance(o, URIRef):
                aspects_by_s.setdefault(s_iri, set()).add(str(o))
            elif p in (of_medium, has_medium) and isinstance(o, URIRef):
                mediums_by_s.setdefault(s_iri, set()).add(str(o))
            elif p == has_qk and isinstance(o, URIRef):
                qk_by_s.setdefault(s_iri, set()).add(str(o))
            elif isinstance(o, Literal):
                local = _pred_local_name(str(p)).lower()
                if local in ALIAS_PREDICATE_LOCAL_NAMES:
                    entities.add(s_iri)
                    aliases_by_s.setdefault(s_iri, []).append(str(o))
                if local in SITE_ID_PREDICATE_LOCAL_NAMES:
                    entities.add(s_iri)
                    site_ids_literal_by_s.setdefault(s_iri, []).append(str(o))

        edges: dict[str, list[UpstreamEdge]] = {}
        seen_edges: set[tuple[str, str, str]] = set()
        derived_connected: set[tuple[str, str]] = set()

        def add_edge(upstream: str, downstream: str, label: str) -> None:
            if not upstream or not downstream or upstream == downstream:
                return
            entities.add(upstream)
            entities.add(downstream)
            key = (upstream, downstream, label)
            if key in seen_edges:
                return
            seen_edges.add(key)
            edges.setdefault(downstream, []).append(
                UpstreamEdge(upstream_iri=upstream, downstream_iri=downstream, predicate=label)
            )
            if label.startswith("s223:") and (upstream, downstream) not in derived_connected:
                derived_connected.add((upstream, downstream))
                sparql_triples.append((upstream, S223 + "connectedTo", downstream))

        def neighbors(node: URIRef, pred: URIRef) -> list[URIRef]:
            found = [o for o in g.objects(node, pred) if isinstance(o, URIRef)]
            found.extend(s for s in g.subjects(pred, node) if isinstance(s, URIRef) and s not in found)
            return found

        for s, p, o in g:
            if not (isinstance(s, URIRef) and isinstance(o, URIRef)):
                continue
            if p == connected_to:
                add_edge(str(s), str(o), "s223:connectedTo")
            elif p == connected_from:
                add_edge(str(o), str(s), "s223:connectedFrom")

        for conn in set(g.subjects(connects_from, None)) & set(g.subjects(connects_to, None)):
            ups = [str(o) for o in g.objects(conn, connects_from) if isinstance(o, URIRef)]
            dns = [str(o) for o in g.objects(conn, connects_to) if isinstance(o, URIRef)]
            for upstream in ups:
                for downstream in dns:
                    add_edge(upstream, downstream, "s223:Connection")

        cp_owner: dict[str, str] = {}
        for equip, _, cp in g.triples((None, has_cp, None)):
            if isinstance(equip, URIRef) and isinstance(cp, URIRef):
                cp_owner[str(cp)] = str(equip)
        for cp_out in g.subjects(rdf_type, outlet_cp):
            out_s = str(cp_out)
            if out_s not in cp_owner:
                continue
            for conn in neighbors(cp_out, cnx):
                for cp_in in neighbors(conn, cnx):
                    in_s = str(cp_in)
                    if in_s == out_s or in_s not in cp_owner:
                        continue
                    if (cp_in, rdf_type, inlet_cp) in g or (URIRef(in_s), rdf_type, inlet_cp) in g:
                        add_edge(cp_owner[out_s], cp_owner[in_s], "s223:cnx")

        for equip, _, prop in g.triples((None, has_property, None)):
            if isinstance(equip, URIRef) and isinstance(prop, URIRef):
                add_edge(str(equip), str(prop), "s223:hasProperty")
        for point, _, equip in g.triples((None, equip_ref, None)):
            if isinstance(point, URIRef) and isinstance(equip, URIRef):
                add_edge(str(equip), str(point), "phIoT:equipRef")

        roles_by_equip: dict[str, list[str]] = {}
        roles_by_node: dict[str, list[str]] = {}
        for equip, _, prop in list(g.triples((None, has_property, None))):
            if not (isinstance(equip, URIRef) and isinstance(prop, URIRef)):
                continue
            prop_s = str(prop)
            role = match_property_pattern(
                types=set(types_by_s.get(prop_s, ())),
                aspects=set(aspects_by_s.get(prop_s, ())),
                mediums=set(mediums_by_s.get(prop_s, ())),
                quantity_kinds=set(qk_by_s.get(prop_s, ())),
                equip_types=set(types_by_s.get(str(equip), ())),
            )
            if role and role not in roles_by_equip.setdefault(str(equip), []):
                roles_by_equip[str(equip)].append(role)
            if role and role not in roles_by_node.setdefault(prop_s, []):
                roles_by_node[prop_s].append(role)

        members: dict[str, list[str]] = {}
        for zone, _, space in g.triples((None, has_domain, None)):
            if isinstance(zone, URIRef) and isinstance(space, URIRef):
                entities.add(str(zone))
                entities.add(str(space))
                bucket = members.setdefault(str(zone), [])
                if str(space) not in bucket:
                    bucket.append(str(space))

        edge_iris: set[str] = set()
        for edge_list in edges.values():
            for edge in edge_list:
                edge_iris.add(edge.upstream_iri)
                edge_iris.add(edge.downstream_iri)

        def display_label(iri: str, node_id: str) -> str:
            for pred in label_preds:
                vals = sorted(set(labels_by_pred[str(pred)].get(iri, ())))
                if vals:
                    return vals[0]
            return node_id

        nodes: dict[str, GraphNode] = {}
        for iri in sorted(entities):
            if _is_vocab_iri(iri) and iri not in edge_iris:
                continue
            eq_types = tuple(sorted(set(types_by_s.get(iri, ()))))
            tags = tuple(sorted(set(tags_by_s.get(iri, ()))))
            site_iri = sites_by_s.get(iri, "")
            site_id_tokens: list[str] = []
            if site_iri:
                site_id_tokens.append(display_label(site_iri, _local_id(site_iri)))
                site_id_tokens.append(_local_id(site_iri))
                site_id_tokens.extend(site_ids_literal_by_s.get(site_iri, ()))
                site_id_tokens.extend(aliases_by_s.get(site_iri, ()))
            site_id_tokens.extend(site_ids_literal_by_s.get(iri, ()))
            site_id_tokens = list(_unique(site_id_tokens))
            literal_site = (site_ids_literal_by_s.get(iri) or site_ids_literal_by_s.get(site_iri) or [""])[0]
            site_id = literal_site or (display_label(site_iri, _local_id(site_iri)) if site_iri else "")
            node_id = _local_id(iri)
            label = display_label(iri, node_id)
            alias_vals = [node_id, label]
            for pred in label_preds:
                alias_vals.extend(labels_by_pred[str(pred)].get(iri, ()))
            alias_vals.extend(aliases_by_s.get(iri, ()))
            aliases = _unique(form for val in alias_vals for form in _identifier_forms(val))
            nodes[iri] = GraphNode(
                iri=iri,
                node_id=node_id,
                label=label,
                site_id=site_id,
                site_iri=site_iri,
                equip_types=eq_types,
                tags=tags,
                is_source_root=_is_source_root(eq_types, tags),
                is_point=_is_point(eq_types, tags),
                aliases=aliases,
                site_ids=tuple(site_id_tokens),
                property_roles=tuple(roles_by_equip.get(iri) or roles_by_node.get(iri) or ()),
                aspects=tuple(sorted(aspects_by_s.get(iri, ()))),
            )

        return cls(
            nodes=nodes,
            upstream_edges=edges,
            rdflib_graph=g,
            sparql_triples=sparql_triples,
            members={k: tuple(v) for k, v in members.items()},
        )

    def _closed_cycle_frontiers(self, visited: set[str]) -> list[str]:
        """Node ids in a visited component that has incoming links but no escape to an unvisited feeder."""
        if not visited:
            return []
        ids: list[str] = []
        for iri in visited:
            cur = self.nodes.get(iri)
            if cur is None or cur.is_point:
                continue
            incoming = [
                e
                for e in self.upstream_edges.get(iri, ())
                if not (self.nodes.get(e.upstream_iri) and self.nodes[e.upstream_iri].is_point)
            ]
            if any(e.upstream_iri not in visited for e in incoming):
                return []
            if incoming:
                ids.append(cur.node_id)
        return sorted(set(ids))

    def resolve_node(self, identifier: str, *, site_id: str | None = None) -> GraphNode | None:
        """Resolve an equipment/space by IRI, local id, or label, scoped by ``site_id`` when given."""
        if not identifier:
            return None

        forms = _identifier_forms(identifier)
        iris: list[str] = []
        if identifier in self.nodes:
            iris.append(identifier)
        for form in forms:
            for iri in self._alias_exact.get(form, ()):
                if iri not in iris:
                    iris.append(iri)
        scoped = self._filter_iris_by_site(iris, site_id)
        if site_id:
            iris = scoped  # do not fall back to another site
        if len(iris) == 1:
            return self.nodes[iris[0]]
        if len(iris) > 1:
            return None

        ci: list[str] = []
        for form in forms:
            for iri in self._alias_ci.get(form.lower(), ()):
                if iri not in ci:
                    ci.append(iri)
        if site_id:
            ci = self._filter_iris_by_site(ci, site_id)
        if len(ci) == 1:
            return self.nodes[ci[0]]
        return None

    def sparql_upstream(
        self,
        target_iri: str,
        *,
        sparql_runner: SparqlRunner | None = None,
    ) -> list[str]:
        """Run a SPARQL property-path upstream query on pyoxigraph 0.5.13, or a custom runner."""
        query = UPSTREAM_PATH_SPARQL_TEMPLATE.format(target_iri=target_iri)
        if sparql_runner is not None:
            rows = sparql_runner(query)
            return sorted({r["upstream"] for r in rows if r.get("upstream") and r["upstream"] != target_iri})
        if not self.sparql_triples:
            return []
        store = self._oxigraph_store()
        if store is None:
            return []
        hits: set[str] = set()
        for solution in store.query(query):
            term = solution["upstream"]
            value = getattr(term, "value", None)
            if value and value != target_iri:
                hits.add(value)
        return sorted(hits)

    def _oxigraph_store(self) -> Any:
        """Build the pyoxigraph store once for this immutable triple snapshot."""
        if self._sparql_store is not None or self._sparql_import_failed:
            return self._sparql_store
        try:
            import pyoxigraph
        except ImportError:
            self._sparql_import_failed = True
            return None
        store = pyoxigraph.Store()
        for subj, pred, obj in self.sparql_triples:
            store.add(pyoxigraph.Quad(pyoxigraph.NamedNode(subj), pyoxigraph.NamedNode(pred), pyoxigraph.NamedNode(obj)))
        self._sparql_store = store
        return store

    def traverse_upstream(
        self,
        target: str,
        *,
        site_id: str | None = None,
        max_hops: int = 16,
        sparql_runner: SparqlRunner | None = None,
    ) -> UpstreamTraversal:
        """Traverse upstream from ``target`` using SPARQL property paths + Python BFS fallback."""
        node = self.resolve_node(target, site_id=site_id)
        if node is None:
            return UpstreamTraversal(
                target_query=target,
                target=None,
                ancestors=[],
                unknown_upstream=True,
                upstream_status="target_not_found",
                unknown_upstream_at=[target],
            )

        sparql_hits: list[str] = []
        try:
            sparql_hits = self.sparql_upstream(node.iri, sparql_runner=sparql_runner)
        except (ValueError, RuntimeError, LookupError, TypeError, OSError):
            # TODO(5.0.22): surface remote SPARQL endpoint errors as warnings rather than silent fallback.
            sparql_hits = []

        # Python BFS from target upstream, avoiding cycles and preferring modeled edges first
        visited: set[str] = {node.iri}
        ancestors: list[UpstreamHop] = []
        frontier_missing: list[str] = []
        used_inferred_edges: set[tuple[str, str]] = set()
        queue: deque[
            tuple[str, int, tuple[str, ...], tuple[str, ...], tuple[bool, ...], tuple[float, ...]]
        ] = deque([(node.iri, 0, (node.node_id,), (), (), ())])

        while queue:
            cur_iri, hop, path_ids, rels, inf_flags, confs = queue.popleft()
            cur_node = self.nodes.get(cur_iri)
            incoming = sorted(
                [
                    e
                    for e in self.upstream_edges.get(cur_iri, ())
                    if not (self.nodes.get(e.upstream_iri) and self.nodes[e.upstream_iri].is_point)
                ],
                key=lambda e: (e.inferred, -(e.confidence or 0.0), e.predicate, e.upstream_iri),
            )
            # Zone membership expands traversal without counting as a physical feeder.
            member_iris = [m for m in self.members.get(cur_iri, ()) if m not in visited and m != cur_iri]
            if not incoming and not member_iris:
                if cur_node is not None and not cur_node.is_source_root:
                    frontier_missing.append(cur_node.node_id)
                continue
            if hop >= max_hops:
                # The hop budget stopped before feeders were walked. A source root is a completed path.
                if cur_node is not None and not cur_node.is_source_root:
                    frontier_missing.append(cur_node.node_id)
                continue
            for member in member_iris:
                visited.add(member)
                queue.append((member, hop, path_ids, rels, inf_flags, confs))
            for edge in incoming:
                up_iri = edge.upstream_iri
                if up_iri in visited:
                    continue
                visited.add(up_iri)
                up_node = self.nodes.get(
                    up_iri,
                    GraphNode(iri=up_iri, node_id=_local_id(up_iri), label=_local_id(up_iri)),
                )
                new_path = (up_node.node_id, *path_ids)
                new_rels = (edge.predicate, *rels)
                new_inf = (edge.inferred, *inf_flags)
                new_confs = (
                    (edge.confidence if edge.confidence is not None else 0.5, *confs)
                    if edge.inferred
                    else confs
                )
                if edge.inferred:
                    used_inferred_edges.add((up_iri, cur_iri))
                hop_inf = any(new_inf)
                if not hop_inf:
                    hop_src = "modeled"
                elif all(new_inf):
                    hop_src = "inferred, not modeled"
                else:
                    hop_src = "mixed (modeled + inferred, not modeled)"
                ancestors.append(
                    UpstreamHop(
                        node=up_node,
                        hop=hop + 1,
                        path=new_path,
                        relations=new_rels,
                        inferred=hop_inf,
                        edge_confidences=new_confs,
                        topology_source=hop_src,
                    )
                )
                queue.append((up_iri, hop + 1, new_path, new_rels, new_inf, new_confs))

        # Keep unverified SPARQL-only hits in sparql_ancestors (never synthesize unverified paths).

        frontier_unique = sorted(set(frontier_missing))
        reached_source = bool(node.is_source_root or any(h.node.is_source_root for h in ancestors))
        if not reached_source and not frontier_unique:
            cycle_front = self._closed_cycle_frontiers(visited)
            if cycle_front:
                frontier_unique = cycle_front
        any_inf = any(h.inferred for h in ancestors)
        any_mod = any(
            h.topology_source in {"modeled", "mixed (modeled + inferred, not modeled)"}
            for h in ancestors
        )
        if not any_inf:
            trav_source = "modeled"
        elif any_mod:
            trav_source = "mixed (modeled + inferred, not modeled)"
        else:
            trav_source = "inferred, not modeled"

        if not ancestors and not node.is_source_root:
            status = "unknown_upstream"
            unknown = True
        elif frontier_unique:
            status = "partial_unknown_upstream"
            unknown = True
        elif any_inf:
            status = "traced_inferred"
            unknown = True
        else:
            status = "traced"
            unknown = False

        return UpstreamTraversal(
            target_query=target,
            target=node,
            ancestors=ancestors,
            unknown_upstream=unknown,
            upstream_status=status,
            unknown_upstream_at=frontier_unique,
            sparql_ancestors=sparql_hits,
            topology_source=trav_source,
            inferred_edges_used=len(used_inferred_edges),
        )


def _is_existing_file(source: str) -> bool:
    """True when ``source`` is a path to a file. Long or illegal paths fall through to Turtle text."""
    if "\n" in source or len(source) > 240:
        return False
    try:
        return Path(source).is_file()
    except OSError:
        return False


def load_graph(source: Path | str | Any) -> TopologyGraph:
    """Load a ``TopologyGraph`` from a Turtle/RDF file path, Turtle text, or ``rdflib.Graph``."""
    import rdflib

    if isinstance(source, TopologyGraph):
        return source
    if isinstance(source, rdflib.Graph):
        return TopologyGraph.from_rdflib(source)
    if isinstance(source, Path) or (isinstance(source, str) and _is_existing_file(source)):
        from open_fdd.ontology_audit.sources import parse_rdf

        return TopologyGraph.from_rdflib(parse_rdf(Path(source)))
    if isinstance(source, str):
        g = rdflib.Graph()
        g.parse(data=source, format="turtle")
        return TopologyGraph.from_rdflib(g)
    raise TypeError(f"Unsupported RDF graph source: {type(source).__name__}")


def load_graph_from_nf(
    *,
    url: str | None = None,
    env_file: str | None = None,
    via: str | None = None,
    app: str = "full",
) -> TopologyGraph:
    """Optional read-only loader reading the Turtle model from a Normal Framework ``rdf`` hook."""
    import rdflib

    from open_fdd.ontology_audit.nf_adapter import fetch_turtle

    turtle, _ = fetch_turtle(url=url, env_file=env_file, via=via, app=app)
    g = rdflib.Graph()
    g.parse(data=turtle, format="turtle")
    return TopologyGraph.from_rdflib(g)