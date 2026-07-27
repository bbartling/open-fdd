"""Cluster assessments into prioritized EngineeringFinding objects."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from open_fdd.reporting.models import (
    CandidateDetection,
    Classification,
    EngineeringFinding,
    EvidencePacket,
    FindingAssessment,
)
from open_fdd.reporting.narrative import (
    finding_title,
    observed_behavior,
    why_it_matters,
)
from open_fdd.reporting.rule_meta import is_duct_static_rule
from open_fdd.reporting.scope import (
    FindingScope,
    filter_candidates,
    sort_key_for_finding,
    equipment_system,
)

CLIENT_CLASSIFICATIONS = {
    Classification.STRONGLY_SUPPORTED,
    Classification.PROBABLE,
    Classification.INCONCLUSIVE,
}

MAX_PRIORITY_FINDINGS = 7


def cluster_and_prioritize(
    candidates: list[CandidateDetection],
    packets: dict[str, EvidencePacket],
    assessments: dict[str, FindingAssessment],
    *,
    max_findings: int = MAX_PRIORITY_FINDINGS,
    scope: FindingScope | None = None,
) -> tuple[list[EngineeringFinding], list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (priority findings, suppressed rows, data_quality rows)."""
    # Scope filter affects ranking inputs (BUG-019) — not a post-DOCX filter.
    scoped = filter_candidates(candidates, scope)
    scoped_keys = {c.key for c in scoped}
    by_key = {c.key: c for c in scoped}
    suppressed: list[dict[str, Any]] = []
    data_quality: list[dict[str, Any]] = []

    for c in candidates:
        if c.key in scoped_keys:
            continue
        a = assessments.get(c.key)
        suppressed.append(
            {
                "candidate_key": c.key,
                "classification": (a.classification.value if a else "OUT_OF_SCOPE"),
                "score": a.score if a else None,
                "reasons": [f"Out of report scope ({_scope_label(scope)})"],
                "equipment_id": c.equipment_id,
                "rule_id": c.rule_id,
            }
        )

    # Group keys for clustering
    clusters: dict[str, list[str]] = defaultdict(list)
    for key, a in assessments.items():
        c = by_key.get(key)
        if not c:
            continue
        if a.classification in {Classification.LIKELY_FALSE_POSITIVE, Classification.NOT_ACTIONABLE}:
            suppressed.append(
                {
                    "candidate_key": key,
                    "classification": a.classification.value,
                    "score": a.score,
                    "reasons": a.reasons,
                    "equipment_id": c.equipment_id,
                    "rule_id": c.rule_id,
                }
            )
            continue
        if a.classification == Classification.DATA_QUALITY:
            data_quality.append(
                {
                    "candidate_key": key,
                    "classification": a.classification.value,
                    "score": a.score,
                    "reasons": a.reasons,
                    "equipment_id": c.equipment_id,
                    "rule_id": c.rule_id,
                    "mean_zone_t": (packets.get(key).sensor_quality or {}).get("mean_zone_t")
                    if packets.get(key)
                    else None,
                }
            )
            # Still may surface as a DQ finding if high impact
            clusters[_cluster_id(c, a)].append(key)
            continue
        clusters[_cluster_id(c, a)].append(key)

    findings: list[EngineeringFinding] = []
    fid = 0
    ranked_keys = sorted(
        clusters.keys(),
        key=lambda ck: -_cluster_score(clusters[ck], assessments),
    )

    for ck in ranked_keys:
        keys = clusters[ck]
        members = [by_key[k] for k in keys if k in by_key]
        assesses = [assessments[k] for k in keys if k in assessments]
        if not members or not assesses:
            continue
        best = max(assesses, key=lambda x: x.score)
        if best.classification not in CLIENT_CLASSIFICATIONS and best.classification != Classification.DATA_QUALITY:
            continue
        # Skip weak DQ noise unless implausible sensor
        if best.classification == Classification.DATA_QUALITY and best.score < 10:
            continue

        fid += 1
        equip_ids = sorted({m.equipment_id for m in members})
        rule_ids = sorted({m.rule_id for m in members})
        systems = sorted({equipment_system(m.equipment_type, m.rule_id) for m in members})

        # Common-mode VAV: one finding
        title = finding_title(members, best)
        evidence_bullets: list[str] = []
        # Prefer the top-scoring member's own evidence (avoid cross-rule bleed).
        primary = max(zip(assesses, members), key=lambda pair: pair[0].score)
        for text in primary[0].supporting[:4]:
            if _evidence_relevant(text, primary[1].rule_id):
                evidence_bullets.append(text)
        evidence_bullets = _uniq(evidence_bullets)[:6]
        contradict = _uniq([x for a in assesses for x in a.contradicting])[:4]
        causes = _uniq([x for a in assesses for x in a.likely_causes])[:4]
        # Drop duct-static field checks unless this finding is a duct-static rule
        field_raw = _uniq([x for a in assesses for x in a.field_verification])
        if not any(is_duct_static_rule(m.rule_id) for m in members):
            field_raw = [x for x in field_raw if "duct static" not in x.lower()]
            causes = [c for c in causes if "duct static" not in c.lower()]
        field = field_raw[:5]

        chart_spec = _chart_spec_for(members[0], packets.get(members[0].key))

        findings.append(
            EngineeringFinding(
                finding_id=f"F{fid:02d}",
                title=title,
                classification=best.classification,
                priority=fid,
                why_it_matters=why_it_matters(members, best),
                observed_behavior=observed_behavior(members, best, packets),
                evidence_bullets=evidence_bullets or best.reasons[:3],
                contradicting_evidence=contradict or ["None material found in automated review"],
                likely_causes=causes,
                field_verification=field,
                possible_corrective=_corrective(best, members),
                rule_ids=rule_ids,
                equipment_ids=equip_ids,
                systems=systems,
                chart_spec=chart_spec,
                candidate_keys=keys,
                automated_assessment=best.to_dict(),
                data_confidence_notes=best.reasons[:3],
            )
        )

    boost = bool(scope and scope.boost_terminal)
    findings.sort(key=lambda f: sort_key_for_finding(f, boost_terminal=boost))
    for i, f in enumerate(findings, 1):
        f.priority = i
        f.finding_id = f"F{i:02d}"

    primary = findings[:max_findings]
    for f in findings[max_findings:]:
        suppressed.append(
            {
                "candidate_key": ",".join(f.candidate_keys),
                "classification": f.classification.value,
                "score": f.automated_assessment.get("score"),
                "reasons": [f"Deprioritized beyond top {max_findings}: {f.title}"],
                "equipment_id": ",".join(f.equipment_ids),
                "rule_id": ",".join(f.rule_ids),
            }
        )
    return primary, suppressed, data_quality


def _scope_label(scope: FindingScope | None) -> str:
    if scope is None:
        return "none"
    parts = []
    if scope.systems:
        parts.append("systems=" + ",".join(scope.systems))
    if scope.equipment_prefixes:
        parts.append("prefix=" + ",".join(scope.equipment_prefixes))
    if scope.rule_ids:
        parts.append("rules=" + ",".join(scope.rule_ids))
    return "; ".join(parts) or "none"


def _cluster_id(c: CandidateDetection, a: FindingAssessment) -> str:
    if c.rule_id == "FAN-OFF-STATIC" or (c.extras or {}).get("fan_off_anomaly"):
        return f"static|{c.equipment_id}"
    if a.classification == Classification.DATA_QUALITY:
        return f"dq|{c.equipment_id}|{c.rule_id}"
    # Peer epidemic of same rule → one cluster
    if a.common_mode_review and c.rule_id.startswith("VAV"):
        return f"common|{c.rule_id}"
    if c.rule_id.startswith("CHW") and a.common_mode_review:
        return f"chw|{c.rule_id}"
    # Same equipment + related VAV airflow family
    if c.rule_id in {"VAV-5", "VAV-4", "VAV-7", "SV-RANGE"}:
        return f"vavflow|{c.equipment_id}"
    return f"solo|{c.equipment_id}|{c.rule_id}"


def _cluster_score(keys: list[str], assessments: dict[str, FindingAssessment]) -> float:
    return max((assessments[k].score for k in keys if k in assessments), default=0.0)


def _cls_rank(c: Classification) -> int:
    order = {
        Classification.STRONGLY_SUPPORTED: 5,
        Classification.PROBABLE: 4,
        Classification.DATA_QUALITY: 3,
        Classification.INCONCLUSIVE: 2,
        Classification.LIKELY_FALSE_POSITIVE: 1,
        Classification.NOT_ACTIONABLE: 0,
    }
    return order.get(c, 0)


def _system(equipment_type: str, rule_id: str) -> str:
    """Back-compat alias — prefer ``equipment_system``."""
    return equipment_system(equipment_type, rule_id)


def _chart_spec_for(c: CandidateDetection, packet: EvidencePacket | None) -> dict[str, Any] | None:
    if c.rule_id == "FAN-OFF-STATIC" or (c.extras or {}).get("fan_off_anomaly"):
        fo = (c.extras or {}).get("fan_off_anomaly") or {}
        return {
            "kind": "fan_off_static",
            "equipment_id": c.equipment_id,
            "fan_off_p50": fo.get("fan_off_p50"),
            "fan_on_p50": fo.get("fan_on_p50"),
            "units": fo.get("units") or "in. w.c.",
        }
    if c.rule_id in {"VAV-5", "VAV5"}:
        spot = (packet.telemetry_evidence if packet else {}).get("spot") or c.telemetry_spot
        return {
            "kind": "vav5_damper_flow",
            "equipment_id": c.equipment_id,
            "damper": spot.get("damper") or spot.get("damper-position"),
            "airflow": spot.get("zone-airflow") or spot.get("airflow"),
        }
    if c.rule_id.startswith("VAV-1") or "comfort" in (c.rule_label or "").lower():
        return {"kind": "comfort_rank", "equipment_id": c.equipment_id}
    return {"kind": "fault_hours_bar", "equipment_id": c.equipment_id, "rule_id": c.rule_id, "fault_hours": c.fault_hours}


def _corrective(best: FindingAssessment, members: list[CandidateDetection]) -> list[str]:
    if best.classification in {Classification.STRONGLY_SUPPORTED, Classification.PROBABLE}:
        if any(m.rule_id == "FAN-OFF-STATIC" for m in members):
            return [
                "After verifying zero/reference tubing, recalibrate or replace the duct static sensor if still wrong"
            ]
        if any(m.rule_id in {"VAV-5", "VAV5"} for m in members):
            return [
                "Inspect damper linkage and commanded vs actual position; if linkage is OK, validate airflow sensor zero/calibration"
            ]
    return ["Do not replace equipment solely from this telemetry review — complete field verification first"]


def _uniq(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in items:
        if not x or x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out


def _evidence_relevant(text: str, rule_id: str) -> bool:
    t = (text or "").lower()
    if "duct static fan-off" in t or "fan-off static" in t:
        return is_duct_static_rule(rule_id)
    if "related rule fan-off-static" in t or "related rule ahu-ducthi" in t:
        return is_duct_static_rule(rule_id)
    return True
