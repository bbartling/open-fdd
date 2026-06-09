"""Portable interval summary schema for central portfolio ingestion (pandas allowed here)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

OPERATOR_STATUSES = frozenset({
    "new",
    "acknowledged",
    "assigned",
    "snoozed",
    "resolved",
    "false_positive",
    "tuning_needed",
})


@dataclass
class FaultIntervalSummary:
    site_id: str
    building_id: str
    equipment_id: str
    equipment_family: str
    timestamp_start: str
    timestamp_end: str
    rule_pack_version: str
    open_fdd_version: str
    fault_code: str
    canonical_id: str
    severity: str
    confidence: float
    active_minutes: float
    percent_active: float
    occurrence_count: int
    first_seen: str
    last_seen: str
    evidence_json: dict[str, Any] = field(default_factory=dict)
    tuning_version: str = ""
    tuning_params_hash: str = ""
    operator_status: str = "new"
    estimated_energy_impact: str = ""
    estimated_comfort_impact: str = ""
    estimated_maintenance_impact: str = ""
    estimated_healthcare_risk: str = ""
    override_count_p8: int = 0
    stale_point_count: int = 0
    missing_point_count: int = 0
    dashboard_url_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.fault_code:
            errors.append("fault_code required")
        if not self.canonical_id:
            errors.append("canonical_id required")
        if self.operator_status not in OPERATOR_STATUSES:
            errors.append(f"invalid operator_status: {self.operator_status}")
        return errors


@dataclass
class TuningProposal:
    proposal_id: str
    generated_at: str
    site_id: str
    equipment_id: str
    fault_code: str
    canonical_id: str
    current_tuning: dict[str, Any]
    proposed_tuning: dict[str, Any]
    reason: str
    supporting_evidence: dict[str, Any]
    expected_effect: str
    risk_level: str
    rollback_plan: str
    approval_status: str = "draft"
    created_by: str = "ai_agent"
    reviewed_by: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
