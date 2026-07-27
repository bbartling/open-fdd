"""Build evidence packets for candidate detections (deterministic)."""

from __future__ import annotations

from typing import Any

from open_fdd.reporting.models import CandidateDetection, EvidenceItem, EvidencePacket
from open_fdd.reporting.rule_meta import is_duct_static_rule

NEAR_CONTINUOUS_PCT = 95.0
IMPLAUSIBLE_ZONE_T_F = 40.0  # mean below this → instrumentation, not comfort
FAN_OFF_STATIC_RATIO = 2.0  # off p50 >> on p50


def build_evidence_packet(
    cand: CandidateDetection,
    *,
    peer_counts: dict[str, int] | None = None,
    fleet_size: int | None = None,
    comfort_row: dict[str, Any] | None = None,
    fan_off_row: dict[str, Any] | None = None,
    related_rules: list[CandidateDetection] | None = None,
) -> EvidencePacket:
    """Assemble a serializable evidence packet for one candidate."""
    peer_counts = peer_counts or {}
    related_rules = related_rules or []
    items: list[EvidenceItem] = []
    corroboration: list[EvidenceItem] = []
    contradiction: list[EvidenceItem] = []

    identity = {
        "building": cand.building,
        "equipment_id": cand.equipment_id,
        "equipment_type": cand.equipment_type,
        "parent_equipment": cand.parent_equipment,
        "rule_id": cand.rule_id,
        "rule_label": cand.rule_label or cand.rule_id,
        "analysis_period": cand.analysis_period,
    }

    fault_pct = float(cand.fault_pct) if cand.fault_pct is not None else None
    fault_hours = float(cand.fault_hours) if cand.fault_hours is not None else None
    near_cont = fault_pct is not None and fault_pct >= NEAR_CONTINUOUS_PCT

    rule_evidence = {
        "status": cand.status,
        "fault_hours": fault_hours,
        "fault_pct": fault_pct,
        "sample_count": cand.sample_count,
        "near_continuous": near_cont,
        "notes": cand.notes,
        "ecm_flag": cand.ecm_flag,
    }
    if fault_hours is not None:
        items.append(
            EvidenceItem(
                "support",
                f"{fault_hours:.0f} fault hours"
                + (f" ({fault_pct:.1f}% of active)" if fault_pct is not None else ""),
                weight=min(10.0, (fault_hours or 0) / 300.0),
                source="rule",
            )
        )

    mapping_evidence = {
        "missing_roles": list(cand.missing_roles),
        "mapping_sufficient": not bool(cand.missing_roles),
    }
    if cand.missing_roles:
        contradiction.append(
            EvidenceItem(
                "contradict",
                f"Missing mapped roles: {', '.join(cand.missing_roles)}",
                weight=-15.0,
                source="mapping",
            )
        )

    spot = dict(cand.telemetry_spot or {})
    telemetry_evidence = {"spot": spot}
    sensor_quality: dict[str, Any] = {"issues": []}
    context: dict[str, Any] = {}

    # VAV-5 style: damper closed + non-zero flow (0.0 is a valid reading — do not use `or`)
    damper = _first_num(spot, ("damper", "damper-position", "damper_pct"))
    flow = _first_num(spot, ("zone-airflow", "airflow", "flow"))
    zone_t = _first_num(spot, ("zone-air-temp", "zone_t", "mean_zone_t"))

    if cand.rule_id in {"VAV-5", "VAV5"} or "airflow" in (cand.rule_label or "").lower():
        if damper is not None and flow is not None:
            telemetry_evidence["damper_pct"] = damper
            telemetry_evidence["airflow"] = flow
            if damper <= 5.0 and flow >= 50.0:
                msg = f"Damper≈{damper:.1f}% with measured airflow≈{flow:.0f} — supports bias/feedback issue"
                corroboration.append(EvidenceItem("support", msg, weight=20.0, source="telemetry", values={"damper": damper, "flow": flow}))
                items.append(corroboration[-1])
            elif damper <= 5.0 and flow < 5.0:
                msg = f"Damper≈{damper:.1f}% and airflow≈{flow:.0f} — condition may not reconstruct (possible FP / gate)"
                contradiction.append(EvidenceItem("contradict", msg, weight=-20.0, source="telemetry", values={"damper": damper, "flow": flow}))
                items.append(contradiction[-1])

    if comfort_row:
        context["comfort"] = comfort_row
        mean_t = _num(comfort_row.get("mean_zone_t") or comfort_row.get("mean_T"))
        if mean_t is not None and mean_t < IMPLAUSIBLE_ZONE_T_F:
            sensor_quality["issues"].append("implausible_zone_temperature")
            sensor_quality["mean_zone_t"] = mean_t
            contradiction.append(
                EvidenceItem(
                    "sensor",
                    f"Zone temperature mean ≈{mean_t:.1f}°F is physically implausible — instrumentation/data quality",
                    weight=-25.0,
                    source="comfort",
                    values={"mean_zone_t": mean_t},
                )
            )
            items.append(contradiction[-1])
        if comfort_row.get("flag_dead_sensor") or comfort_row.get("dead_sensor?") or comfort_row.get("outlier"):
            sensor_quality["issues"].append("dead_or_outlier_zone_sensor")

    if zone_t is not None and zone_t < IMPLAUSIBLE_ZONE_T_F:
        sensor_quality["issues"].append("implausible_zone_temperature_spot")
        sensor_quality["spot_zone_t"] = zone_t

    # Fan-off static anomaly: only score duct-static rules. Other rules on the same
    # AHU get a context note only — avoids identical "duct static" evidence on every finding.
    if fan_off_row and fan_off_row.get("equipment_id") == cand.equipment_id:
        context["fan_off_static"] = fan_off_row
        off_p = _num(fan_off_row.get("fan_off_p50"))
        on_p = _num(fan_off_row.get("fan_on_p50"))
        if off_p is not None and on_p is not None and on_p > 0 and off_p >= max(1.0, FAN_OFF_STATIC_RATIO * on_p):
            msg = (
                f"Duct static fan-OFF p50≈{off_p:.2f} vs fan-ON≈{on_p:.2f} "
                f"{fan_off_row.get('units') or 'in. w.c.'} — strong instrumentation suspicion"
            )
            if is_duct_static_rule(cand.rule_id):
                corroboration.append(
                    EvidenceItem(
                        "support",
                        msg,
                        weight=25.0,
                        source="sensor_stats",
                        values={"fan_off_p50": off_p, "fan_on_p50": on_p},
                    )
                )
                items.append(corroboration[-1])
                sensor_quality["issues"].append("fan_off_static_anomaly")
            else:
                context["fan_off_static_note"] = msg

    # Fan-off anomaly as its own synthetic candidate uses extras
    if cand.extras.get("fan_off_anomaly"):
        fo = cand.extras["fan_off_anomaly"]
        off_p = _num(fo.get("fan_off_p50"))
        on_p = _num(fo.get("fan_on_p50"))
        if off_p is not None and on_p is not None:
            corroboration.append(
                EvidenceItem(
                    "support",
                    f"Fan-off static {off_p:.2f} vs fan-on {on_p:.2f}",
                    weight=25.0,
                    source="sensor_stats",
                    values={"fan_off_p50": off_p, "fan_on_p50": on_p},
                )
            )
            items.append(corroboration[-1])
            sensor_quality["issues"].append("fan_off_static_anomaly")

    same_rule_peers = peer_counts.get(cand.rule_id, 1)
    peer_summary = {
        "rule_id": cand.rule_id,
        "devices_with_same_rule_fault": same_rule_peers,
        "fleet_size": fleet_size,
        "prevalence": (same_rule_peers / fleet_size) if fleet_size and fleet_size > 0 else None,
    }
    if fleet_size and same_rule_peers >= max(5, int(0.4 * fleet_size)):
        contradiction.append(
            EvidenceItem(
                "peer",
                f"Common-mode: {same_rule_peers}/{fleet_size} peers share {cand.rule_id} — prefer one parent finding / check mapping-threshold",
                weight=-15.0,
                source="peer",
            )
        )
        items.append(contradiction[-1])
        peer_summary["common_mode_suspected"] = True

    if near_cont:
        items.append(
            EvidenceItem(
                "context",
                f"Near-continuous fault ({fault_pct:.1f}% active) — requires common-mode / mapping skepticism",
                weight=-10.0,
                source="rule",
            )
        )

    for rel in related_rules:
        if rel.key == cand.key:
            continue
        # Do not let FAN-OFF-STATIC / duct-static synthetic hits corroborate unrelated rules.
        if is_duct_static_rule(rel.rule_id) and not is_duct_static_rule(cand.rule_id):
            continue
        corroboration.append(
            EvidenceItem(
                "support",
                f"Related rule {rel.rule_id} on {rel.equipment_id} ({rel.fault_hours} h)",
                weight=5.0,
                source="cross_rule",
            )
        )

    return EvidencePacket(
        candidate_key=cand.key,
        identity=identity,
        rule_evidence=rule_evidence,
        mapping_evidence=mapping_evidence,
        telemetry_evidence=telemetry_evidence,
        context=context,
        sensor_quality=sensor_quality,
        corroboration=corroboration,
        contradiction=contradiction,
        peer_summary=peer_summary,
        items=items,
    )


def _num(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _first_num(spot: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for k in keys:
        if k in spot and spot[k] is not None and spot[k] != "":
            return _num(spot[k])
    return None
