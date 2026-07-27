"""Typed structures for Engineering Findings (JSON-serializable)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class Classification(str, Enum):
    STRONGLY_SUPPORTED = "STRONGLY_SUPPORTED"
    PROBABLE = "PROBABLE"
    INCONCLUSIVE = "INCONCLUSIVE"
    LIKELY_FALSE_POSITIVE = "LIKELY_FALSE_POSITIVE"
    DATA_QUALITY = "DATA_QUALITY"
    NOT_ACTIONABLE = "NOT_ACTIONABLE"


# Evidence score → category thresholds (configurable / tested)
SCORE_THRESHOLDS = {
    Classification.STRONGLY_SUPPORTED: 80,
    Classification.PROBABLE: 60,
    Classification.INCONCLUSIVE: 40,
    Classification.LIKELY_FALSE_POSITIVE: 20,
}


def classification_from_score(score: float) -> Classification:
    if score >= SCORE_THRESHOLDS[Classification.STRONGLY_SUPPORTED]:
        return Classification.STRONGLY_SUPPORTED
    if score >= SCORE_THRESHOLDS[Classification.PROBABLE]:
        return Classification.PROBABLE
    if score >= SCORE_THRESHOLDS[Classification.INCONCLUSIVE]:
        return Classification.INCONCLUSIVE
    if score >= SCORE_THRESHOLDS[Classification.LIKELY_FALSE_POSITIVE]:
        return Classification.LIKELY_FALSE_POSITIVE
    return Classification.DATA_QUALITY


@dataclass
class EvidenceItem:
    kind: str  # support | contradict | context | mapping | sensor | peer
    text: str
    weight: float = 0.0
    source: str = ""
    values: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CandidateDetection:
    """A raw rule hit or dump-derived detection — not yet a finding."""

    building: str
    equipment_id: str
    equipment_type: str
    rule_id: str
    rule_label: str = ""
    status: str = "FAULT"
    fault_hours: float | None = None
    fault_pct: float | None = None
    sample_count: int = 0
    missing_roles: list[str] = field(default_factory=list)
    notes: str = ""
    ecm_flag: str | None = None
    parent_equipment: str | None = None
    analysis_period: str = ""
    telemetry_spot: dict[str, Any] = field(default_factory=dict)
    extras: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.equipment_id}|{self.rule_id}"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


@dataclass
class EvidencePacket:
    candidate_key: str
    identity: dict[str, Any]
    rule_evidence: dict[str, Any]
    mapping_evidence: dict[str, Any]
    telemetry_evidence: dict[str, Any]
    context: dict[str, Any]
    sensor_quality: dict[str, Any]
    corroboration: list[EvidenceItem] = field(default_factory=list)
    contradiction: list[EvidenceItem] = field(default_factory=list)
    peer_summary: dict[str, Any] = field(default_factory=dict)
    items: list[EvidenceItem] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_key": self.candidate_key,
            "identity": self.identity,
            "rule_evidence": self.rule_evidence,
            "mapping_evidence": self.mapping_evidence,
            "telemetry_evidence": self.telemetry_evidence,
            "context": self.context,
            "sensor_quality": self.sensor_quality,
            "corroboration": [i.to_dict() for i in self.corroboration],
            "contradiction": [i.to_dict() for i in self.contradiction],
            "peer_summary": self.peer_summary,
            "items": [i.to_dict() for i in self.items],
        }


@dataclass
class FindingAssessment:
    candidate_key: str
    classification: Classification
    score: float
    score_breakdown: dict[str, float]
    supporting: list[str] = field(default_factory=list)
    contradicting: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    likely_causes: list[str] = field(default_factory=list)
    field_verification: list[str] = field(default_factory=list)
    common_mode_review: bool = False
    requires_more_evidence: bool = False
    review_passes: int = 0

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["classification"] = self.classification.value
        return d


@dataclass
class EngineeringFinding:
    finding_id: str
    title: str
    classification: Classification
    priority: int
    why_it_matters: str
    observed_behavior: str
    evidence_bullets: list[str]
    contradicting_evidence: list[str]
    likely_causes: list[str]
    field_verification: list[str]
    possible_corrective: list[str]
    rule_ids: list[str]
    equipment_ids: list[str]
    systems: list[str]
    chart_spec: dict[str, Any] | None = None
    chart_path: str | None = None
    day_zoom_path: str | None = None
    day_zoom_label: str | None = None
    day_zoom_skip_reason: str | None = None
    candidate_keys: list[str] = field(default_factory=list)
    automated_assessment: dict[str, Any] = field(default_factory=dict)
    engineer_override: dict[str, Any] | None = None
    include_in_report: bool = True
    data_confidence_notes: list[str] = field(default_factory=list)

    @property
    def effective_classification(self) -> Classification:
        if self.engineer_override and self.engineer_override.get("classification"):
            try:
                return Classification(self.engineer_override["classification"])
            except ValueError:
                pass
        return self.classification

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["classification"] = self.classification.value
        d["effective_classification"] = self.effective_classification.value
        # BUG-022 alias for agents expecting day_zoom_error
        d["day_zoom_error"] = self.day_zoom_skip_reason
        return d


@dataclass
class ReportArtifacts:
    building: str
    analysis_period: str
    generated_at: str
    findings: list[EngineeringFinding]
    suppressed: list[dict[str, Any]]
    candidates: list[dict[str, Any]]
    assessments: list[dict[str, Any]]
    data_quality: list[dict[str, Any]]
    comfort_summary: dict[str, Any]
    metrics: dict[str, Any]
    field_checklist: list[str]
    assumptions: dict[str, Any]
    quality_gate: dict[str, Any]
    charts: list[dict[str, Any]] = field(default_factory=list)
    overview_settings: dict[str, Any] = field(default_factory=dict)
    overview_charts: list[dict[str, Any]] = field(default_factory=list)
    fault_inventory: dict[str, Any] = field(default_factory=dict)
    disclaimer: str = (
        "Open-FDD / Vibe 19 educational analysis. Findings are telemetry-based "
        "and advisory; physical verification remains a human/field activity."
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "building": self.building,
            "analysis_period": self.analysis_period,
            "generated_at": self.generated_at,
            "findings": [f.to_dict() for f in self.findings],
            "suppressed": self.suppressed,
            "candidates": self.candidates,
            "assessments": self.assessments,
            "data_quality": self.data_quality,
            "comfort_summary": self.comfort_summary,
            "metrics": self.metrics,
            "field_checklist": self.field_checklist,
            "assumptions": self.assumptions,
            "quality_gate": self.quality_gate,
            "charts": self.charts,
            "overview_settings": self.overview_settings,
            "overview_charts": self.overview_charts,
            "fault_inventory": self.fault_inventory,
            "disclaimer": self.disclaimer,
        }
