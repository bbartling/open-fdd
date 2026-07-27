"""False-positive / evidence review loop (Passes 1–7) + engineering score."""

from __future__ import annotations

from open_fdd.reporting.evidence import NEAR_CONTINUOUS_PCT
from open_fdd.reporting.models import (
    Classification,
    EvidencePacket,
    FindingAssessment,
    classification_from_score,
)
from open_fdd.reporting.rule_meta import is_duct_static_rule


def review_evidence_packet(
    packet: EvidencePacket,
    *,
    max_passes: int = 3,
) -> FindingAssessment:
    """Deterministic review: calculate first, classify second.

    Score components (explainable, not fake probability):
      Data quality            0–20
      Mapping confidence      0–15
      Operational proof       0–15
      Direct telemetry proof  0–20
      Temporal persistence    0–10
      Independent corroboration 0–15
      Contradiction penalty   0 to -30
      Fleet/common-mode       0 to -20
    """
    breakdown: dict[str, float] = {
        "data_quality": 15.0,
        "mapping": 15.0,
        "operational": 10.0,
        "telemetry": 0.0,
        "temporal": 0.0,
        "corroboration": 0.0,
        "contradiction_penalty": 0.0,
        "fleet_penalty": 0.0,
    }
    supporting: list[str] = []
    contradicting: list[str] = []
    reasons: list[str] = []
    likely_causes: list[str] = []
    field_checks: list[str] = []
    common_mode = False
    passes = 0

    # PASS 1 — DATA TRUST
    passes += 1
    sq = packet.sensor_quality or {}
    issues = list(sq.get("issues") or [])
    if "implausible_zone_temperature" in issues or "implausible_zone_temperature_spot" in issues:
        breakdown["data_quality"] = 0.0
        reasons.append("Implausible zone temperature → DATA_QUALITY, not comfort")
        contradicting.append(next((i.text for i in packet.contradiction if i.kind == "sensor"), "Implausible zone T"))
        return FindingAssessment(
            candidate_key=packet.candidate_key,
            classification=Classification.DATA_QUALITY,
            score=5.0,
            score_breakdown=breakdown,
            supporting=supporting,
            contradicting=contradicting,
            reasons=reasons,
            likely_causes=["Failed, unscaled, or mis-mapped zone temperature sensor"],
            field_verification=["Verify zone sensor wiring, scaling, and units before box troubleshooting"],
            review_passes=passes,
        )
    if "dead_or_outlier_zone_sensor" in issues and packet.identity.get("rule_id", "").startswith("VAV-1"):
        breakdown["data_quality"] = 5.0
        reasons.append("Comfort rule on flagged dead/outlier zone sensor")
        return FindingAssessment(
            candidate_key=packet.candidate_key,
            classification=Classification.DATA_QUALITY,
            score=15.0,
            score_breakdown=breakdown,
            reasons=reasons,
            likely_causes=["Untrustworthy zone sensor"],
            field_verification=["Validate zone-air-temp before comfort work orders"],
            review_passes=passes,
        )

    # PASS 2 — MAPPING / OPERATIONAL
    passes += 1
    if not packet.mapping_evidence.get("mapping_sufficient", True):
        breakdown["mapping"] = 0.0
        contradicting.extend(i.text for i in packet.contradiction if i.source == "mapping")
        reasons.append("Insufficient role mapping")
        return FindingAssessment(
            candidate_key=packet.candidate_key,
            classification=Classification.INCONCLUSIVE,
            score=25.0,
            score_breakdown=breakdown,
            contradicting=contradicting,
            reasons=reasons,
            field_verification=["Complete required role mappings and re-run"],
            requires_more_evidence=True,
            review_passes=passes,
        )

    # PASS 3 — CONDITION RECONSTRUCTION (telemetry)
    passes += 1
    for item in packet.corroboration:
        if item.source in {"telemetry", "sensor_stats"}:
            breakdown["telemetry"] = min(20.0, breakdown["telemetry"] + abs(item.weight))
            supporting.append(item.text)
    for item in packet.contradiction:
        if item.source == "telemetry":
            breakdown["contradiction_penalty"] += item.weight  # negative
            contradicting.append(item.text)
            reasons.append("Telemetry does not reconstruct the rule condition")

    # PASS 4 — TEMPORAL
    re_ = packet.rule_evidence or {}
    fh = re_.get("fault_hours")
    fp = re_.get("fault_pct")
    if fh is not None:
        breakdown["temporal"] = min(10.0, float(fh) / 200.0)
        supporting.append(f"{fh:.0f} fault hours")
    near = bool(re_.get("near_continuous")) or (fp is not None and float(fp) >= NEAR_CONTINUOUS_PCT)
    if near:
        common_mode = True
        reasons.append("Near-continuous activation — elevated skepticism")
        breakdown["fleet_penalty"] -= 5.0

    # PASS 5 — CORROBORATION
    for item in packet.corroboration:
        if item.source in {"cross_rule", "support"} or item.kind == "support":
            if item.text not in supporting:
                supporting.append(item.text)
            if item.source == "cross_rule":
                breakdown["corroboration"] = min(15.0, breakdown["corroboration"] + 5.0)

    if "fan_off_static_anomaly" in issues and is_duct_static_rule(
        str(packet.identity.get("rule_id") or "")
    ):
        breakdown["telemetry"] = max(breakdown["telemetry"], 20.0)
        breakdown["corroboration"] = min(15.0, breakdown["corroboration"] + 10.0)
        likely_causes.append("Bad / stuck / mis-scaled duct static sensor or reference tubing")
        field_checks.append(
            f"{packet.identity.get('equipment_id')} — verify duct static zero with supply fan proven OFF; compare to fan-ON"
        )

    # PASS 6 — CONTRADICTION / PEER
    peer = packet.peer_summary or {}
    if peer.get("common_mode_suspected"):
        common_mode = True
        breakdown["fleet_penalty"] -= 15.0
        contradicting.append(next((i.text for i in packet.contradiction if i.source == "peer"), "Peer epidemic"))
        reasons.append("Peer/common-mode pattern — avoid mass work orders")
        likely_causes.append("Shared mapping, threshold, or upstream cause rather than N independent failures")

    for item in packet.contradiction:
        if item.source not in {"telemetry", "mapping", "peer"}:
            breakdown["contradiction_penalty"] += item.weight
            contradicting.append(item.text)

    # Strong VAV-5 reconstruction without contradiction
    rule_id = str(packet.identity.get("rule_id") or "")
    if rule_id in {"VAV-5", "VAV5"} and breakdown["telemetry"] >= 15 and breakdown["contradiction_penalty"] >= -5:
        likely_causes.extend(
            [
                "Airflow sensor zero/bias",
                "Damper position feedback unreliable",
                "Damper linkage issue (verify before replace)",
            ]
        )
        field_checks.append(
            f"{packet.identity.get('equipment_id')} — command damper closed; verify measured airflow against handheld/reference"
        )

    # Near-100% CHW / plant without compressor proof in packet → inconclusive skepticism
    if near and rule_id.startswith("CHW") and breakdown["telemetry"] < 10:
        reasons.append("Near-100% plant rule without independent compressor proof in evidence packet")
        breakdown["operational"] = 5.0
        breakdown["fleet_penalty"] -= 10.0
        likely_causes.append("Verify compressor-status mapping before treating as continuous chiller operation")
        field_checks.append(
            f"{packet.identity.get('equipment_id')} — confirm compressor/status proof vs pump-only signals"
        )

    # PASS 7 — SCORE → CLASSIFICATION
    passes += 1
    raw = sum(breakdown.values())
    score = max(0.0, min(100.0, raw))

    # Hard overrides
    if near and breakdown["telemetry"] < 10 and breakdown["corroboration"] < 5:
        # Near-100% without corroboration must NOT be STRONGLY_SUPPORTED
        classification = Classification.INCONCLUSIVE if score >= 40 else Classification.LIKELY_FALSE_POSITIVE
        reasons.append("Near-continuous detection without corroboration → not auto-confirmed")
    elif contradicting and breakdown["telemetry"] <= 0 and "does not reconstruct" in " ".join(reasons).lower():
        classification = Classification.LIKELY_FALSE_POSITIVE
    else:
        classification = classification_from_score(score)
        if near and classification == Classification.STRONGLY_SUPPORTED and breakdown["telemetry"] < 15:
            classification = Classification.PROBABLE
            reasons.append("Downgraded from strongly supported due to near-continuous + weak telemetry proof")

    if not field_checks:
        field_checks.append(
            f"Re-check {packet.identity.get('equipment_id')} / {rule_id} in FDD Plots with gates and swim lanes"
        )

    if not likely_causes and classification in {
        Classification.STRONGLY_SUPPORTED,
        Classification.PROBABLE,
    }:
        likely_causes.append(packet.rule_evidence.get("ecm_flag") or "See rule evidence; verify in field")

    return FindingAssessment(
        candidate_key=packet.candidate_key,
        classification=classification,
        score=round(score, 1),
        score_breakdown={k: round(v, 1) for k, v in breakdown.items()},
        supporting=supporting[:8],
        contradicting=contradicting[:8],
        reasons=reasons,
        likely_causes=[c for c in likely_causes if c][:5],
        field_verification=field_checks[:5],
        common_mode_review=common_mode,
        requires_more_evidence=classification == Classification.INCONCLUSIVE and passes < max_passes,
        review_passes=passes,
    )
