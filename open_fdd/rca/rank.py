"""Explainable root-cause ranking over upstream HVAC RDF traversal and FDD evidence.

All scoring is heuristic, transparent, computed in SI, and advisory only: it never
modifies rules, tuners, tags, or setpoints. Integrates with 5.0.22 fault-confidence
scores (``p_real``, ``p_false_positive``, ``confidence_label``) so likely false
positives are down-weighted instead of masking real upstream causes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from open_fdd.rca.evidence import (
    DataQualityEvidence,
    EvidenceCollector,
    FaultEvidence,
    NodeEvidence,
    PointDeviation,
)
from open_fdd.rca.graph import GraphNode, TopologyGraph, UpstreamHop, UpstreamTraversal


@dataclass(frozen=True)
class CandidateCause:
    """One ranked candidate root cause for a downstream symptom fault."""

    equipment_id: str
    equipment_iri: str
    rule_id: str
    hop_distance: int
    confidence: float
    share: float
    cause_chain: tuple[str, ...]
    relations: tuple[str, ...]
    downstream_symptoms_explained: int
    p_real: float | None = None
    p_false_positive: float | None = None
    confidence_label: str | None = None
    precedence: str = "unknown"  # before_symptom | concurrent | after_symptom | unknown
    data_quality_caveats: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    score_breakdown: dict[str, float] = field(default_factory=dict)


@dataclass
class CauseTrace:
    """Root-cause trace for one downstream symptom fault episode."""

    symptom_equipment: str
    symptom_rule: str
    symptom_site: str
    symptom_start: str | None
    symptom_end: str | None
    upstream_status: str  # traced | partial_unknown_upstream | unknown_upstream | target_not_found
    unknown_upstream: bool
    unknown_upstream_at: list[str]
    candidates: list[CandidateCause]
    symptom_data_quality: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class CommonCauseRollup:
    """Multiple downstream symptom faults that share a likely upstream root cause."""

    root_equipment: str
    root_rule: str
    confidence: float
    downstream_symptom_count: int
    downstream_equipment: list[str]
    downstream_rules: list[str]
    reasons: list[str]


@dataclass
class RCAReport:
    """Full advisory root-cause analysis result across a set of symptom faults."""

    traces: list[CauseTrace]
    common_causes: list[CommonCauseRollup]
    totals: dict[str, Any]
    advisory: str = "Advisory graph-based root-cause analysis only. Nothing was tuned, tagged, or changed."


def _ts_iso(dt: Any) -> str | None:
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%MZ")


def _collect_for_node(
    collector: EvidenceCollector,
    node: GraphNode,
    symptom: FaultEvidence,
    tolerance: timedelta,
) -> NodeEvidence:
    """Try node_id, then label, then full IRI so callers can key faults by any standard id."""
    for ident in dict.fromkeys((node.node_id, node.label, node.iri)):
        if not ident:
            continue
        ev = collector.collect(
            ident,
            window_start=symptom.start,
            window_end=symptom.end,
            site_id=symptom.site_id or node.site_id,
            tolerance=tolerance,
        )
        if ev.faults or ev.data_quality_flags or ev.point_deviations:
            return ev
    return NodeEvidence(equipment_id=node.node_id)


def _select_symptoms(
    graph: TopologyGraph,
    collector: EvidenceCollector,
    *,
    symptom_equip: str | None = None,
    symptom_rule: str | None = None,
    site_id: str | None = None,
) -> list[FaultEvidence]:
    faults = collector.all_faults()
    if site_id:
        faults = [f for f in faults if not f.site_id or f.site_id == site_id]
    if symptom_equip:
        eq_low = symptom_equip.lower()
        node = graph.resolve_node(symptom_equip, site_id=site_id)
        aliases = {eq_low}
        if node is not None:
            aliases.update({node.node_id.lower(), node.label.lower(), node.iri.lower()})
        faults = [f for f in faults if f.equipment_id.lower() in aliases]
    if symptom_rule:
        r_low = symptom_rule.lower()
        faults = [f for f in faults if f.rule_id.lower() == r_low]
    if symptom_equip or symptom_rule or len(faults) <= 1:
        return faults

    # Default automatic mode: select leaf/downstream faults (those that do not sit strictly upstream
    # of another faulted node) so upstream equipment acts as candidate causes rather than duplicate symptoms.
    faulted_iris: set[str] = set()
    for f in faults:
        n = graph.resolve_node(f.equipment_id, site_id=f.site_id or site_id)
        if n is not None:
            faulted_iris.add(n.iri)

    upstream_of_faulted: set[str] = set()
    for f in faults:
        tr = graph.traverse_upstream(f.equipment_id, site_id=f.site_id or site_id)
        for hop in tr.ancestors:
            if hop.node.iri in faulted_iris:
                upstream_of_faulted.add(hop.node.iri)

    leaf_faults: list[FaultEvidence] = []
    for f in faults:
        n = graph.resolve_node(f.equipment_id, site_id=f.site_id or site_id)
        if n is None or n.iri not in upstream_of_faulted:
            leaf_faults.append(f)
    return leaf_faults or faults


def _score_candidate(
    symptom: FaultEvidence,
    hop: UpstreamHop,
    fault: FaultEvidence | None,
    dq_flags: list[DataQualityEvidence],
    deviations: list[PointDeviation],
    downstream_count: int,
) -> CandidateCause:
    reasons: list[str] = []
    caveats: list[str] = []
    breakdown: dict[str, float] = {}

    if fault is not None:
        base_fault = 0.45 if hop.hop > 0 else 0.25
        conf_factor = 0.70
        if fault.p_real is not None and fault.p_false_positive is not None:
            conf_factor = max(0.05, fault.p_real * (1.0 - 0.7 * fault.p_false_positive))
        elif fault.p_real is not None:
            conf_factor = max(0.05, fault.p_real)

        if fault.confidence_label == "likely_false_positive":
            conf_factor = min(conf_factor, 0.15)
            reasons.append(f"{hop.node.label}: {fault.rule_id} down-weighted (likely_false_positive)")
        elif fault.p_real is not None:
            reasons.append(f"{hop.node.label}: active fault {fault.rule_id} (p_real={fault.p_real:.2f})")
        else:
            reasons.append(f"{hop.node.label}: active fault {fault.rule_id}")

        if fault.is_data_quality:
            conf_factor *= 0.50
            caveats.append(f"fault {fault.rule_id} is a data-quality rule")

        fault_pts = base_fault * conf_factor

        # Temporal precedence
        precedence = "unknown"
        prec_pts = 0.08
        if fault.start is not None and symptom.start is not None:
            if fault.start < symptom.start:
                precedence = "before_symptom"
                prec_pts = 0.20
                delta_min = round((symptom.start - fault.start).total_seconds() / 60.0)
                reasons.append(f"started {delta_min} min before symptom")
            elif fault.start == symptom.start:
                precedence = "concurrent"
                prec_pts = 0.16
                reasons.append("started concurrently with symptom")
            else:
                precedence = "after_symptom"
                prec_pts = 0.02
                reasons.append("started after symptom onset")
    else:
        # Deviation-only upstream candidate (no rule fired, but SI sensor deviation observed)
        fault_pts = 0.0
        precedence = "unknown"
        prec_pts = 0.0
        reasons.append(f"{hop.node.label}: SI point deviation without active rule fault")

    # Common-cause rollup boost when multiple unhappy downstream nodes share this ancestor
    cc_pts = 0.0
    if hop.hop > 0 and downstream_count >= 2:
        cc_pts = min(0.30, 0.12 * (downstream_count - 1))
        reasons.append(f"shared upstream ancestor of {downstream_count} downstream symptoms")

    # SI point deviation support
    dev_pts = 0.0
    non_zero_devs = [d for d in deviations if (d.resolved_deviation_si or 0.0) != 0.0]
    if non_zero_devs:
        dev_pts = 0.06 if fault is not None else 0.16
        sample = non_zero_devs[0]
        val = sample.resolved_deviation_si
        unit = f" {sample.unit}" if sample.unit else ""
        reasons.append(f"SI deviation {sample.role}={val:+.2f}{unit}")

    # Data-quality caveat on the node's sensors
    dq_mult = 1.0
    if dq_flags:
        dq_mult = 0.65
        flag_names = ", ".join(sorted({d.flag for d in dq_flags}))
        caveats.append(f"node has data-quality warnings: {flag_names}")
        reasons.append(f"confidence discounted for data quality ({flag_names})")

    prox_mult = 1.0 if hop.hop <= 1 else 1.0 / (1.0 + 0.12 * (hop.hop - 1))

    raw = (fault_pts + prec_pts + cc_pts + dev_pts) * dq_mult * prox_mult
    confidence = round(max(0.0, min(1.0, raw)), 3)

    breakdown = {
        "fault": round(fault_pts, 3),
        "precedence": round(prec_pts, 3),
        "common_cause": round(cc_pts, 3),
        "deviation": round(dev_pts, 3),
        "dq_multiplier": round(dq_mult, 3),
        "proximity_multiplier": round(prox_mult, 3),
    }

    return CandidateCause(
        equipment_id=hop.node.node_id,
        equipment_iri=hop.node.iri,
        rule_id=fault.rule_id if fault is not None else "SI-DEVIATION",
        hop_distance=hop.hop,
        confidence=confidence,
        share=0.0,
        cause_chain=hop.path,
        relations=hop.relations,
        downstream_symptoms_explained=downstream_count,
        p_real=fault.p_real if fault is not None else None,
        p_false_positive=fault.p_false_positive if fault is not None else None,
        confidence_label=fault.confidence_label if fault is not None else None,
        precedence=precedence,
        data_quality_caveats=tuple(caveats),
        reasons=tuple(reasons),
        score_breakdown=breakdown,
    )


def analyze_rca(
    graph: TopologyGraph,
    collector: EvidenceCollector,
    *,
    symptom_equip: str | None = None,
    symptom_rule: str | None = None,
    site_id: str | None = None,
    include_self: bool = True,
    tolerance: timedelta = timedelta(minutes=30),
    top: int = 5,
) -> RCAReport:
    """Run advisory graph-based RCA across symptom faults and return an ``RCAReport``."""
    symptoms = _select_symptoms(
        graph,
        collector,
        symptom_equip=symptom_equip,
        symptom_rule=symptom_rule,
        site_id=site_id,
    )

    traversals: list[UpstreamTraversal] = [
        graph.traverse_upstream(s.equipment_id, site_id=s.site_id or site_id) for s in symptoms
    ]

    # Common-cause counts: distinct symptom equipment sharing each upstream IRI
    downstream_by_ancestor: dict[str, set[str]] = {}
    for sym, tr in zip(symptoms, traversals):
        sym_key = tr.target.iri if tr.target is not None else f"{sym.site_id}:{sym.equipment_id}"
        for hop in tr.ancestors:
            downstream_by_ancestor.setdefault(hop.node.iri, set()).add(sym_key)

    traces: list[CauseTrace] = []
    rollup_acc: dict[tuple[str, str], dict[str, Any]] = {}
    fp_downweighted = 0
    unknown_count = 0

    for sym, tr in zip(symptoms, traversals):
        if tr.unknown_upstream:
            unknown_count += 1

        sym_dq: list[str] = []
        if tr.target is not None:
            self_ev = _collect_for_node(collector, tr.target, sym, tolerance)
            sym_dq = sorted({d.flag for d in self_ev.data_quality_flags})

        hops_to_check: list[UpstreamHop] = list(tr.ancestors)
        if include_self and tr.target is not None:
            hops_to_check.append(UpstreamHop(node=tr.target, hop=0, path=(tr.target.node_id,), relations=()))

        raw_candidates: list[CandidateCause] = []
        for hop in hops_to_check:
            ev = _collect_for_node(collector, hop.node, sym, tolerance)
            down_n = len(downstream_by_ancestor.get(hop.node.iri, ())) if hop.hop > 0 else 1

            # Exclude the symptom fault itself at hop == 0
            node_faults = [
                f for f in ev.faults if not (hop.hop == 0 and f.rule_id == sym.rule_id)
            ]

            for f in node_faults:
                if f.confidence_label == "likely_false_positive":
                    fp_downweighted += 1
                cand = _score_candidate(sym, hop, f, ev.data_quality_flags, ev.point_deviations, down_n)
                raw_candidates.append(cand)

            if not node_faults and ev.point_deviations and hop.hop > 0:
                has_dev = any((d.resolved_deviation_si or 0.0) != 0.0 for d in ev.point_deviations)
                if has_dev:
                    cand = _score_candidate(sym, hop, None, ev.data_quality_flags, ev.point_deviations, down_n)
                    raw_candidates.append(cand)

        raw_candidates.sort(key=lambda c: (-c.confidence, c.hop_distance, c.equipment_id, c.rule_id))
        top_cands = raw_candidates[: max(1, top)]
        total_conf = sum(c.confidence for c in top_cands)
        normalized: list[CandidateCause] = []
        for c in top_cands:
            share = round(c.confidence / total_conf, 3) if total_conf > 0 else 0.0
            normalized.append(
                CandidateCause(
                    equipment_id=c.equipment_id,
                    equipment_iri=c.equipment_iri,
                    rule_id=c.rule_id,
                    hop_distance=c.hop_distance,
                    confidence=c.confidence,
                    share=share,
                    cause_chain=c.cause_chain,
                    relations=c.relations,
                    downstream_symptoms_explained=c.downstream_symptoms_explained,
                    p_real=c.p_real,
                    p_false_positive=c.p_false_positive,
                    confidence_label=c.confidence_label,
                    precedence=c.precedence,
                    data_quality_caveats=c.data_quality_caveats,
                    reasons=c.reasons,
                    score_breakdown=c.score_breakdown,
                )
            )

        notes: list[str] = []
        if tr.upstream_status == "unknown_upstream":
            notes.append("unknown upstream: no upstream feeder link in RDF model (not guessed).")
        elif tr.upstream_status == "partial_unknown_upstream":
            at = ", ".join(tr.unknown_upstream_at)
            notes.append(f"partial trace — unknown upstream above: {at}.")
        elif tr.upstream_status == "target_not_found":
            notes.append(f"symptom equipment {sym.equipment_id!r} not found in RDF topology graph.")

        if normalized:
            lead = normalized[0]
            if lead.hop_distance > 0:
                key = (lead.equipment_id, lead.rule_id)
                slot = rollup_acc.setdefault(
                    key,
                    {
                        "conf": [],
                        "equips": set(),
                        "rules": set(),
                        "reasons": set(),
                    },
                )
                slot["conf"].append(lead.confidence)
                slot["equips"].add(sym.equipment_id)
                slot["rules"].add(sym.rule_id)
                slot["reasons"].update(lead.reasons)

        traces.append(
            CauseTrace(
                symptom_equipment=sym.equipment_id,
                symptom_rule=sym.rule_id,
                symptom_site=sym.site_id,
                symptom_start=_ts_iso(sym.start),
                symptom_end=_ts_iso(sym.end),
                upstream_status=tr.upstream_status,
                unknown_upstream=tr.unknown_upstream,
                unknown_upstream_at=list(tr.unknown_upstream_at),
                candidates=normalized,
                symptom_data_quality=sym_dq,
                notes=notes,
            )
        )

    rollups: list[CommonCauseRollup] = []
    for (eq_id, rule_id), slot in rollup_acc.items():
        if len(slot["equips"]) >= 2:
            rollups.append(
                CommonCauseRollup(
                    root_equipment=eq_id,
                    root_rule=rule_id,
                    confidence=round(sum(slot["conf"]) / len(slot["conf"]), 3),
                    downstream_symptom_count=len(slot["equips"]),
                    downstream_equipment=sorted(slot["equips"]),
                    downstream_rules=sorted(slot["rules"]),
                    reasons=sorted(slot["reasons"]),
                )
            )
    rollups.sort(key=lambda r: (-r.downstream_symptom_count, -r.confidence, r.root_equipment))

    totals = {
        "symptoms_analyzed": len(traces),
        "traced_with_candidates": sum(1 for t in traces if t.candidates),
        "unknown_upstream_traces": unknown_count,
        "common_cause_groups": len(rollups),
        "false_positives_downweighted": fp_downweighted,
    }
    return RCAReport(traces=traces, common_causes=rollups, totals=totals)