"""Run proof (#1608): is the equipment a rule judges proven running?

One contract, ``sql/fdd/run_proof.json`` (shipped inside ``fdd-catalog.json`` as ``run_proof``), read by every engine:
the NF hook (``nf-app/static/run-proof.js`` is this module's twin), the SQL packs (history column ``run_proof``) and the
pandas rules (column ``run-proof``). Nothing here reads a point name; everything comes from the model.

Resolution, in order (first hit wins):

1. the equipment's own proof: a bound status role (fan / pump / chilled-water pump / chiller / compressor), then a bound
   command role (fan / pump / condenser pump / tower fan), in the order of ``own`` in the contract;
2. the proof of the equipment that FEEDS it, one hop: its ``airRef`` / ``chilledWaterRef`` / ``hotWaterRef`` target, then a
   ``isFedBy`` target, then any equipment that lists it under ``feeds`` (RDF: ``brick:isFedBy`` / ``brick:feeds``), each
   feeder judged by its own proof (tier 1);
3. none: a gated rule is SKIPPED with reason ``no_run_proof``.

The pure function :func:`resolve_run_proof` works on :class:`ProofNode` objects, which come from an NF model
(:func:`nodes_from_model`) or from the Turtle export (:func:`nodes_from_graph`, rdflib), so both give the same answer.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

SKIP_REASON = "no_run_proof"
RUN_PROOF_COLUMN = "run-proof"


def spec(catalog: Mapping | None = None) -> dict:
    """The run-proof contract (``fdd-catalog.json`` -> ``run_proof``)."""
    if catalog is None:
        from open_fdd.nf.model import load_catalog

        catalog = load_catalog()
    return dict(catalog["run_proof"])


# ---------------------------------------------------------------------------- pure resolution
@dataclass
class ProofNode:
    """One equipment as the resolver sees it."""

    id: str
    site: str = ""
    aliases: tuple[str, ...] = ()                    # other names a ref may use (display name, uuid)
    refs: dict[str, str] = field(default_factory=dict)  # airRef / chilledWaterRef / hotWaterRef -> target id
    is_fed_by: tuple[str, ...] = ()
    feeds: tuple[str, ...] = ()
    roles: frozenset[str] = frozenset()              # roles with at least one bound point

    def names(self) -> set[str]:
        return {self.id, *self.aliases} - {""}


@dataclass(frozen=True)
class RunProof:
    """``found`` False = no proof (SKIPPED ``no_run_proof``). ``tier`` own | feeder; ``source`` status | command."""

    found: bool
    tier: str = ""
    source: str = ""
    role: str = ""
    equip: str = ""        # the equipment that carries the proof (the feeder, for tier feeder)
    via: str = ""          # self | airRef | chilledWaterRef | hotWaterRef | isFedBy | feeds

    @property
    def reason(self) -> str:
        return "" if self.found else SKIP_REASON


NONE = RunProof(False)


def _ref_id(v: Any) -> str:
    return str(v or "").strip().lstrip("@")


def _own(node: ProofNode, own: Mapping[str, Iterable[str]]) -> tuple[str, str] | None:
    for source in ("status", "command"):
        for role in own[source]:
            if role in node.roles:
                return source, role
    return None


def resolve_run_proof(node: ProofNode, nodes: Iterable[ProofNode], contract: Mapping) -> RunProof:
    """The proof of ``node`` (see the module docstring). ``nodes`` = every equipment of the model."""
    own = contract["own"]
    hit = _own(node, own)
    if hit:
        return RunProof(True, "own", hit[0], hit[1], node.id, "self")
    site_nodes = [n for n in nodes if n.site == node.site]
    pool = [n for n in site_nodes if n is not node]

    def find(target: str) -> list[ProofNode]:
        t = _ref_id(target)
        # count across the whole site, the requester included: an ambiguous ref (one name, several equipment) binds
        # nothing, and a ref that names the requester itself is not a feeder
        hits = [n for n in site_nodes if t in n.names()] if t else []
        return hits if len(hits) == 1 and hits[0] is not node else []

    feeders: list[tuple[str, ProofNode]] = []
    for ref in contract["feeders"]["refs"]:
        feeders += [(ref, n) for n in find(node.refs.get(ref, ""))]
    for target in node.is_fed_by:
        feeders += [("isFedBy", n) for n in find(target)]
    mine = node.names()
    feeders += [("feeds", n) for n in pool if mine & {_ref_id(x) for x in n.feeds}]
    for via, feeder in feeders:
        hit = _own(feeder, own)
        if hit:
            return RunProof(True, "feeder", hit[0], hit[1], feeder.id, via)
    return NONE


# ---------------------------------------------------------------------------- nodes from an NF model
def _split(v: Any) -> tuple[str, ...]:
    if isinstance(v, (list, tuple)):
        return tuple(_ref_id(x) for x in v if _ref_id(x))
    return tuple(_ref_id(x) for x in str(v or "").split(",") if _ref_id(x))


def nodes_from_model(model, catalog: Mapping | None = None) -> list[ProofNode]:
    """:class:`ProofNode` per equipment of an ``open_fdd.nf.model.Model`` (roles bound exactly like the rules bind them)."""
    from open_fdd.nf.model import bind_roles, equip_pool, id_of, load_catalog

    cat = catalog or load_catalog()
    c = spec(cat)
    wanted = [r for g in c["own"].values() for r in g]
    out = []
    for e in model.equips:
        a = e.get("attrs") or {}
        bound = bind_roles(wanted, equip_pool(e, model), cat)
        out.append(ProofNode(
            id=id_of(e), site=a.get("siteRef", ""),
            aliases=tuple(x for x in (e.get("name"), e.get("uuid"), a.get("dis")) if x),
            refs={r: _ref_id(a.get(r)) for r in c["feeders"]["refs"] if a.get(r)},
            is_fed_by=_split(a.get("isFedBy")), feeds=_split(a.get("feeds")),
            roles=frozenset(r for r, pts in bound.items() if pts)))
    return out


# ---------------------------------------------------------------------------- nodes from the Turtle export (RDF)
def nodes_from_graph(graph, catalog: Mapping | None = None) -> list[ProofNode]:
    """:class:`ProofNode` per ``phIoT:equip`` of an rdflib graph of the app's Turtle export.

    Refs are the ``phIoT:airRef`` / ``phIoT:chilledWaterRef`` / ``phIoT:hotWaterRef`` triples; links are
    ``brick:isFedBy`` / ``brick:feeds``. A point fills a role by its ``local:nfClass`` (or, with no class, by carrying every
    marker of the role), the same rule as ``bindRoles``.
    """
    from rdflib import RDF, RDFS, URIRef

    from open_fdd.nf.model import load_catalog

    cat = catalog or load_catalog()
    c = spec(cat)
    wanted = [r for g in c["own"].values() for r in g]
    tail = lambda u: re.split(r"[#/:]", str(u))[-1]  # noqa: E731
    by_tail: dict[str, list[URIRef]] = {}
    for p in set(graph.predicates()):
        by_tail.setdefault(tail(p), []).append(p)

    def objs(s, name):
        return [o for p in by_tail.get(name, []) for o in graph.objects(s, p)]

    equips = [s for s in set(graph.subjects(RDF.type, None)) if any(tail(t) == "equip" for t in graph.objects(s, RDF.type))]
    label = lambda s: str(next(iter(graph.objects(s, RDFS.label)), tail(s)))  # noqa: E731

    def identities(subjects) -> dict:
        # a label is a display name, not an identity. It is used only when no other subject shares it AND it cannot
        # be mistaken for another subject's own name; otherwise the subject's own name (or its full IRI when even that
        # is shared) is the identity, so a precise RDF reference never lands on the wrong equipment or merges two sites
        subjects = list(subjects)
        labels: dict[str, int] = {}
        tails: dict[str, int] = {}
        for x in subjects:
            labels[label(x)] = labels.get(label(x), 0) + 1
            tails[tail(x)] = tails.get(tail(x), 0) + 1
        out = {}
        for x in subjects:
            lb, tl = label(x), tail(x)
            if labels[lb] == 1 and (lb == tl or lb not in tails):
                out[x] = lb
            else:
                out[x] = tl if tails[tl] == 1 and tl not in labels else str(x)
        return out

    sites = identities({x for s in equips for x in objs(s, "siteRef")})
    site_of = lambda s: next((sites[x] for x in objs(s, "siteRef")), "")  # noqa: E731
    ident = identities(equips)
    points: dict[Any, list[URIRef]] = {}
    for pt in set(graph.subjects(RDF.type, None)):
        if any(tail(t) == "point" for t in graph.objects(pt, RDF.type)):
            for eq in objs(pt, "equipRef"):
                points.setdefault(eq, []).append(pt)

    def roles_of(eq) -> frozenset[str]:
        got = set()
        for pt in points.get(eq, []):
            cls = {str(o) for o in objs(pt, "nfClass")}
            tags = {tail(o) for o in objs(pt, "hasTag")}
            for role in wanted:
                d = cat["roles"].get(role)
                if d and ((cls & set(d["classes"])) or (d["markers"] and set(d["markers"]) <= tags)):
                    got.add(role)
        return frozenset(got)

    def ref_target(o) -> str:
        return ident.get(o) or tail(o)

    out = []
    for eq in sorted(equips, key=str):
        out.append(ProofNode(
            id=ident[eq], site=site_of(eq), aliases=(tail(eq),),
            refs={r: ref_target(next(iter(objs(eq, r)))) for r in c["feeders"]["refs"] if objs(eq, r)},
            is_fed_by=tuple(ref_target(o) for o in objs(eq, "isFedBy")),
            feeds=tuple(ref_target(o) for o in objs(eq, "feeds")),
            roles=roles_of(eq)))
    return out


# ---------------------------------------------------------------------------- pandas frames
def derive_run_proof(df, catalog: Mapping | None = None):
    """``(series | None, source)``: the frame's ``run-proof`` column when it carries data, else the equipment's OWN proof
    taken from its status / command columns (tier 1 of the resolution), else ``(None, "")``.

    A frame stamped ``df.attrs["run_proof_resolved"] = True`` was already resolved by the binding layer (the NF hook, the
    parity dataset): only its ``run-proof`` column counts, so a frame that merely HAS a status column does not turn
    "no proof bound" into a proof.

    The series keeps the source's scale (0/1 status or a 0-1 command fraction); a sample is running when it is above
    ``threshold``. Feeding-equipment proof (tier 2) is resolved where the model is known (the NF hook, ``nodes_from_*``)
    and delivered as the ``run-proof`` column.
    """
    import pandas as pd

    from open_fdd.nf.model import column_for

    c = spec(catalog)
    if RUN_PROOF_COLUMN in df.columns and df[RUN_PROOF_COLUMN].notna().any():
        return pd.to_numeric(df[RUN_PROOF_COLUMN], errors="coerce"), RUN_PROOF_COLUMN
    if df.attrs.get("run_proof_resolved"):
        return None, ""            # the binding layer already resolved this equipment and found no proof: nothing to derive
    for group in ("status", "command"):
        for role in c["own"][group]:
            col = column_for(role)
            if col in df.columns and df[col].notna().any():
                return pd.to_numeric(df[col], errors="coerce"), col
    return None, ""


def proof_on(series, threshold: float | None = None):
    """Running mask: above the threshold; a missing sample is not proof."""
    thr = spec()["threshold"] if threshold is None else threshold
    return series.fillna(0).gt(thr)


# ---------------------------------------------------------------------------- which rules are gated
def run_proof_gated_ids() -> frozenset[str]:
    """Pandas rule ids that carry the run-proof gate (catalog ``run_proof: gated``; SQL ids mapped to their pandas twin)."""
    from open_fdd.nf.model import load_catalog
    from open_fdd.parity.pandas_ref import PANDAS_ID

    return frozenset(PANDAS_ID.get(r["id"], r["id"]) for r in load_catalog()["rules"] if r.get("run_proof") == "gated")


def run_proof_gate_on(rule_id: str, params: Mapping, gates_on: bool = True) -> bool:
    """True when this rule is gated, the gates are on and ``require_run_proof`` (alias ``require_operational_gate``) is on."""
    if not gates_on or rule_id not in run_proof_gated_ids():
        return False
    value = params.get("require_run_proof", params.get("require_operational_gate", 1.0))
    try:
        return float(value) >= 0.5
    except (TypeError, ValueError):
        return True


def sweep_gate_mask(d, p: Mapping):
    """Running mask for the SV sweeps: all True with the gate off (``require_run_proof`` 0), else ``proof_on`` of the frame's
    run proof; with no proof at all, nothing is running (the runner SKIPPED the rule before this point)."""
    import pandas as pd

    value = p.get("require_run_proof", p.get("require_operational_gate", 1.0))
    try:
        if float(value) < 0.5:
            return pd.Series(True, index=d.index)
    except (TypeError, ValueError):
        pass
    series, _ = derive_run_proof(d)
    return pd.Series(False, index=d.index) if series is None else proof_on(series).reindex(d.index).fillna(False)
