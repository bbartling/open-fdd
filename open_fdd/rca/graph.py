"""RDF topology loader and upstream traversal for HVAC root-cause analysis (RCA).

Supports Brick (``brick:feeds`` / ``brick:isFedBy``), ASHRAE 223P (``s223:connectedTo`` /
``s223:connectedFrom`` / ``s223:Connection`` / connection points), and Project Haystack
(``phIoT:airRef``, ``phIoT:chilledWaterRef``, ``phIoT:hotWaterRef``, ``phIoT:equipRef``,
``phIoT:weatherStationRef``). Reuses ``open_fdd.ontology_audit`` for safe offline RDF
parsing and Haystack IRI normalization.

Sparse / incomplete graphs are expected in real buildings: when a node or chain ends
without an upstream feeder link on a non-source equipment, traversal reports
``unknown_upstream`` instead of guessing links.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from open_fdd.ontology_audit.terms import PREFIXES, split_iri

BRICK = PREFIXES["brick"]
S223 = PREFIXES["s223"]
PH = PREFIXES["ph"]
PH_IOT = PREFIXES["phIoT"]
RDF_NS = PREFIXES["rdf"]
RDFS_NS = PREFIXES["rdfs"]

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

UPSTREAM_PATH_SPARQL_TEMPLATE = """PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX s223: <http://data.ashrae.org/standard223#>
PREFIX phIoT: <https://project-haystack.org/def/phIoT/>
SELECT DISTINCT ?upstream WHERE {{
  ?upstream (
    brick:feeds | ^brick:isFedBy |
    s223:connectedTo | ^s223:connectedFrom |
    ^phIoT:airRef | ^phIoT:chilledWaterRef | ^phIoT:hotWaterRef |
    ^phIoT:weatherStationRef | ^phIoT:equipRef
  )+ <{target_iri}> .
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


@dataclass(frozen=True)
class UpstreamEdge:
    """Directed edge from ``upstream_iri`` feeding ``downstream_iri``."""

    upstream_iri: str
    downstream_iri: str
    predicate: str


@dataclass(frozen=True)
class UpstreamHop:
    """Reachable upstream ancestor with shortest hop count and path from symptom."""

    node: GraphNode
    hop: int
    path: tuple[str, ...]  # ordered upstream -> ... -> symptom node_id
    relations: tuple[str, ...]


@dataclass
class UpstreamTraversal:
    """Result of walking upstream from a symptom equipment or node."""

    target_query: str
    target: GraphNode | None
    ancestors: list[UpstreamHop] = field(default_factory=list)
    unknown_upstream: bool = False
    upstream_status: str = "traced"  # traced | partial_unknown_upstream | unknown_upstream | target_not_found
    unknown_upstream_at: list[str] = field(default_factory=list)
    sparql_ancestors: list[str] = field(default_factory=list)


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
        if tok in POINT_MARKERS:
            return True
    return False


class TopologyGraph:
    """Normalized RDF + adjacency index for multi-vocabulary upstream HVAC traversal."""

    def __init__(
        self,
        nodes: dict[str, GraphNode],
        upstream_edges: dict[str, list[UpstreamEdge]],
        *,
        rdflib_graph: Any = None,
    ) -> None:
        self.nodes = nodes
        self.upstream_edges = upstream_edges
        self.rdflib_graph = rdflib_graph

    @classmethod
    def from_rdflib(cls, graph: Any) -> TopologyGraph:
        """Build a ``TopologyGraph`` from an ``rdflib.Graph`` (normalizing Haystack IRIs)."""
        from rdflib import Literal, URIRef

        from open_fdd.ontology_audit.doctor import normalize_graph

        g = normalize_graph(graph)

        rdf_type = URIRef(RDF_NS + "type")
        rdfs_label = URIRef(RDFS_NS + "label")
        has_tag = URIRef(PH + "hasTag")
        site_ref = URIRef(PH_IOT + "siteRef")
        dis_pred = URIRef(PH + "dis")

        # Collect all candidate entity IRIs appearing in types, labels, or topology predicates
        entities: set[str] = set()
        types_by_s: dict[str, list[str]] = {}
        tags_by_s: dict[str, list[str]] = {}
        labels_by_s: dict[str, str] = {}
        sites_by_s: dict[str, str] = {}

        for s, p, o in g:
            if not isinstance(s, URIRef):
                continue
            s_iri = str(s)
            if p == rdf_type and isinstance(o, URIRef):
                entities.add(s_iri)
                types_by_s.setdefault(s_iri, []).append(str(o))
            elif p == has_tag and isinstance(o, URIRef):
                entities.add(s_iri)
                tags_by_s.setdefault(s_iri, []).append(str(o))
            elif p in (rdfs_label, dis_pred) and isinstance(o, Literal):
                entities.add(s_iri)
                labels_by_s.setdefault(s_iri, str(o))
            elif p == site_ref and isinstance(o, URIRef):
                entities.add(s_iri)
                sites_by_s[s_iri] = str(o)

        edges: dict[str, list[UpstreamEdge]] = {}
        seen_edges: set[tuple[str, str, str]] = set()

        def add_edge(upstream: str, downstream: str, label: str) -> None:
            if upstream == downstream:
                return
            entities.add(upstream)
            entities.add(downstream)
            key = (upstream, downstream, label)
            if key not in seen_edges:
                seen_edges.add(key)
                edges.setdefault(downstream, []).append(
                    UpstreamEdge(upstream_iri=upstream, downstream_iri=downstream, predicate=label)
                )

        # 1. Direct Brick / 223P / Haystack relationships
        feeds_p = URIRef(BRICK + "feeds")
        is_fed_by_p = URIRef(BRICK + "isFedBy")
        s223_to = URIRef(S223 + "connectedTo")
        s223_from = URIRef(S223 + "connectedFrom")
        air_ref = URIRef(PH_IOT + "airRef")
        chw_ref = URIRef(PH_IOT + "chilledWaterRef")
        hw_ref = URIRef(PH_IOT + "hotWaterRef")
        wx_ref = URIRef(PH_IOT + "weatherStationRef")
        equip_ref = URIRef(PH_IOT + "equipRef")

        for s, p, o in g:
            if not (isinstance(s, URIRef) and isinstance(o, URIRef)):
                continue
            if p == feeds_p:
                add_edge(str(s), str(o), "brick:feeds")
            elif p == is_fed_by_p:
                add_edge(str(o), str(s), "brick:isFedBy")
            elif p == s223_to:
                add_edge(str(s), str(o), "s223:connectedTo")
            elif p == s223_from:
                add_edge(str(o), str(s), "s223:connectedFrom")
            elif p == air_ref:
                add_edge(str(o), str(s), "phIoT:airRef")
            elif p == chw_ref:
                add_edge(str(o), str(s), "phIoT:chilledWaterRef")
            elif p == hw_ref:
                add_edge(str(o), str(s), "phIoT:hotWaterRef")
            elif p == wx_ref:
                add_edge(str(o), str(s), "phIoT:weatherStationRef")
            elif p == equip_ref:
                add_edge(str(o), str(s), "phIoT:equipRef")

        # 2. ASHRAE 223P Connection (conn s223:connectsFrom upstream ; s223:connectsTo downstream)
        connects_from = URIRef(S223 + "connectsFrom")
        connects_to = URIRef(S223 + "connectsTo")
        has_cp = URIRef(S223 + "hasConnectionPoint")
        cnx = URIRef(S223 + "cnx")
        outlet_cp = URIRef(S223 + "OutletConnectionPoint")
        inlet_cp = URIRef(S223 + "InletConnectionPoint")

        for conn in set(g.subjects(connects_from, None)) & set(g.subjects(connects_to, None)):
            ups = [str(o) for o in g.objects(conn, connects_from) if isinstance(o, URIRef)]
            dns = [str(o) for o in g.objects(conn, connects_to) if isinstance(o, URIRef)]
            for u in ups:
                for d in dns:
                    add_edge(u, d, "s223:Connection")

        # 3. ASHRAE 223P ConnectionPoint -> Connection -> ConnectionPoint
        cp_owner: dict[str, str] = {}
        for equip, _, cp in g.triples((None, has_cp, None)):
            if isinstance(equip, URIRef) and isinstance(cp, URIRef):
                cp_owner[str(cp)] = str(equip)
        for cp_out in g.subjects(rdf_type, outlet_cp):
            out_s = str(cp_out)
            if out_s not in cp_owner:
                continue
            for conn in g.objects(cp_out, cnx):
                for cp_in in g.objects(conn, cnx):
                    in_s = str(cp_in)
                    if in_s == out_s or in_s not in cp_owner:
                        continue
                    if (cp_in, rdf_type, inlet_cp) in g or (cp_out, rdf_type, outlet_cp) in g:
                        add_edge(cp_owner[out_s], cp_owner[in_s], "s223:cnx")

        # Build GraphNode objects
        nodes: dict[str, GraphNode] = {}
        for iri in sorted(entities):
            eq_types = tuple(sorted(set(types_by_s.get(iri, ()))))
            tags = tuple(sorted(set(tags_by_s.get(iri, ()))))
            site_iri = sites_by_s.get(iri, "")
            site_id = labels_by_s.get(site_iri, _local_id(site_iri)) if site_iri else ""
            node_id = _local_id(iri)
            label = labels_by_s.get(iri, node_id)
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
            )

        return cls(nodes=nodes, upstream_edges=edges, rdflib_graph=g)

    def resolve_node(self, identifier: str, *, site_id: str | None = None) -> GraphNode | None:
        """Resolve an equipment/space by IRI, local id, or label, scoped by ``site_id`` when given."""
        if not identifier:
            return None
        if identifier in self.nodes:
            return self.nodes[identifier]

        candidates = list(self.nodes.values())
        if site_id:
            scoped = [n for n in candidates if n.site_id == site_id or _local_id(n.site_iri) == site_id]
            if scoped:
                candidates = scoped

        # Exact node_id match first, then case-insensitive node_id, then label
        by_id = [n for n in candidates if n.node_id == identifier]
        if len(by_id) == 1:
            return by_id[0]
        if len(by_id) > 1:
            return None  # ambiguous across sites when site_id omitted

        ident_low = identifier.lower()
        by_id_ci = [n for n in candidates if n.node_id.lower() == ident_low]
        if len(by_id_ci) == 1:
            return by_id_ci[0]

        by_label = [n for n in candidates if n.label.lower() == ident_low]
        if len(by_label) == 1:
            return by_label[0]
        return None

    def sparql_upstream(
        self,
        target_iri: str,
        *,
        sparql_runner: SparqlRunner | None = None,
    ) -> list[str]:
        """Run a SPARQL property-path upstream query against local rdflib or a custom runner."""
        query = UPSTREAM_PATH_SPARQL_TEMPLATE.format(target_iri=target_iri)
        if sparql_runner is not None:
            rows = sparql_runner(query)
            return sorted({r["upstream"] for r in rows if r.get("upstream") and r["upstream"] != target_iri})
        if self.rdflib_graph is None:
            return []
        res = self.rdflib_graph.query(query)
        return sorted({str(row[0]) for row in res if row[0] is not None and str(row[0]) != target_iri})

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

        # Python BFS from target upstream, avoiding cycles and recording shortest paths + edge provenance
        visited: set[str] = {node.iri}
        ancestors: list[UpstreamHop] = []
        frontier_missing: list[str] = []
        queue: deque[tuple[str, int, tuple[str, ...], tuple[str, ...]]] = deque(
            [(node.iri, 0, (node.node_id,), ())]
        )

        while queue:
            cur_iri, hop, path_ids, rels = queue.popleft()
            cur_node = self.nodes.get(cur_iri)
            incoming = [
                e for e in self.upstream_edges.get(cur_iri, ())
                if not (self.nodes.get(e.upstream_iri) and self.nodes[e.upstream_iri].is_point)
            ]
            if not incoming:
                if cur_node is not None and not cur_node.is_source_root:
                    frontier_missing.append(cur_node.node_id)
                continue
            if hop >= max_hops:
                continue
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
                ancestors.append(
                    UpstreamHop(node=up_node, hop=hop + 1, path=new_path, relations=new_rels)
                )
                queue.append((up_iri, hop + 1, new_path, new_rels))

        # Include any extra ancestors returned only by an external SPARQL runner
        seen_iris = {h.node.iri for h in ancestors} | {node.iri}
        for hit_iri in sparql_hits:
            if hit_iri not in seen_iris:
                up_node = self.nodes.get(
                    hit_iri,
                    GraphNode(iri=hit_iri, node_id=_local_id(hit_iri), label=_local_id(hit_iri)),
                )
                ancestors.append(
                    UpstreamHop(
                        node=up_node,
                        hop=1,
                        path=(up_node.node_id, node.node_id),
                        relations=("sparql:upstream",),
                    )
                )

        frontier_unique = sorted(set(frontier_missing))
        if not ancestors and not node.is_source_root:
            status = "unknown_upstream"
            unknown = True
        elif frontier_unique:
            status = "partial_unknown_upstream"
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
        )


def load_graph(source: Path | str | Any) -> TopologyGraph:
    """Load a ``TopologyGraph`` from a Turtle/RDF file path, Turtle text, or ``rdflib.Graph``."""
    import rdflib

    if isinstance(source, TopologyGraph):
        return source
    if isinstance(source, rdflib.Graph):
        return TopologyGraph.from_rdflib(source)
    if isinstance(source, Path) or (isinstance(source, str) and "\n" not in source and Path(source).is_file()):
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