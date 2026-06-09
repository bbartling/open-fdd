"""Canonical fault metadata schema (Grade-A)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


SEVERITIES = frozenset({"info", "low", "medium", "high", "critical"})
CATEGORIES = frozenset({
    "energy",
    "comfort",
    "reliability",
    "maintenance",
    "indoor_air_quality",
    "healthcare_risk",
    "data_quality",
    "controls_integrity",
})
FAMILIES = frozenset({
    "AHU", "VAV", "RTU", "DOAS", "FCU", "FPU", "CHL", "CHW", "CTW", "BLR", "HWS",
    "PMP", "HX", "ERV", "CRS", "DATA", "CTRL", "BACNET", "BUILDING", "GEO", "HP",
})


@dataclass
class StandardsCrosswalk:
    ornl_lbnl_taxonomy: str = ""
    ashrae_g36_reference_type: str = ""
    ashrae_207_reference_type: str = ""
    brick_classes: list[str] = field(default_factory=list)
    haystack_tags: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> StandardsCrosswalk:
        raw = raw or {}
        return cls(
            ornl_lbnl_taxonomy=str(raw.get("ornl_lbnl_taxonomy") or ""),
            ashrae_g36_reference_type=str(raw.get("ashrae_g36_reference_type") or ""),
            ashrae_207_reference_type=str(raw.get("ashrae_207_reference_type") or ""),
            brick_classes=list(raw.get("brick_classes") or []),
            haystack_tags=list(raw.get("haystack_tags") or []),
        )


@dataclass
class TuningParams:
    thresholds: dict[str, float] = field(default_factory=dict)
    deadbands: dict[str, float] = field(default_factory=dict)
    minimum_runtime_minutes: float | None = None
    persistence_minutes: float | None = None
    confidence_min: float | None = None
    seasonal_applicability: str = ""
    occupancy_applicability: str = ""

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> TuningParams:
        raw = raw or {}
        return cls(
            thresholds={k: float(v) for k, v in (raw.get("thresholds") or {}).items()},
            deadbands={k: float(v) for k, v in (raw.get("deadbands") or {}).items()},
            minimum_runtime_minutes=_float_or_none(raw.get("minimum_runtime_minutes")),
            persistence_minutes=_float_or_none(raw.get("persistence_minutes")),
            confidence_min=_float_or_none(raw.get("confidence_min")),
            seasonal_applicability=str(raw.get("seasonal_applicability") or ""),
            occupancy_applicability=str(raw.get("occupancy_applicability") or ""),
        )


@dataclass
class OperatorGuidance:
    plain_english_summary: str = ""
    why_it_matters: str = ""
    likely_fix_by_role: dict[str, str] = field(default_factory=dict)
    technician_checks: list[str] = field(default_factory=list)
    engineer_roi_notes: str = ""
    commissioning_notes: str = ""

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> OperatorGuidance:
        raw = raw or {}
        return cls(
            plain_english_summary=str(raw.get("plain_english_summary") or ""),
            why_it_matters=str(raw.get("why_it_matters") or ""),
            likely_fix_by_role=dict(raw.get("likely_fix_by_role") or {}),
            technician_checks=list(raw.get("technician_checks") or []),
            engineer_roi_notes=str(raw.get("engineer_roi_notes") or ""),
            commissioning_notes=str(raw.get("commissioning_notes") or ""),
        )


@dataclass
class FaultDefinition:
    code: str
    canonical_id: str
    family: str
    system_type: str
    subsystem: str
    component: str
    fault_mode: str
    symptom: str
    title: str
    likely_causes: list[str]
    severity_default: str
    category: str
    required_point_roles: list[str]
    optional_point_roles: list[str] = field(default_factory=list)
    rule_template_id: str = ""
    rule_doc_path: str = ""
    related_faults: list[str] = field(default_factory=list)
    suppresses_faults: list[str] = field(default_factory=list)
    suppressed_by_faults: list[str] = field(default_factory=list)
    legacy_aliases: list[str] = field(default_factory=list)
    standards_crosswalk: StandardsCrosswalk = field(default_factory=StandardsCrosswalk)
    tuning_params: TuningParams = field(default_factory=TuningParams)
    evidence_fields: list[str] = field(default_factory=list)
    operator_guidance: OperatorGuidance = field(default_factory=OperatorGuidance)

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.code:
            errors.append("code required")
        if not self.canonical_id or "." not in self.canonical_id:
            errors.append(f"canonical_id must be dotted semantic id: {self.canonical_id!r}")
        if self.family.upper() not in FAMILIES:
            errors.append(f"unknown family: {self.family}")
        if self.severity_default not in SEVERITIES:
            errors.append(f"invalid severity: {self.severity_default}")
        if self.category not in CATEGORIES:
            errors.append(f"invalid category: {self.category}")
        if not self.required_point_roles:
            errors.append("required_point_roles must be non-empty")
        if not self.rule_template_id:
            errors.append("rule_template_id required")
        return errors

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> FaultDefinition:
        return cls(
            code=str(raw["code"]),
            canonical_id=str(raw["canonical_id"]),
            family=str(raw.get("family") or raw["code"].split("-", 1)[0]).upper(),
            system_type=str(raw.get("system_type") or ""),
            subsystem=str(raw.get("subsystem") or ""),
            component=str(raw.get("component") or ""),
            fault_mode=str(raw.get("fault_mode") or ""),
            symptom=str(raw.get("symptom") or ""),
            title=str(raw.get("title") or raw["code"]),
            likely_causes=list(raw.get("likely_causes") or []),
            severity_default=str(raw.get("severity_default") or "medium"),
            category=str(raw.get("category") or "energy"),
            required_point_roles=list(raw.get("required_point_roles") or []),
            optional_point_roles=list(raw.get("optional_point_roles") or []),
            rule_template_id=str(raw.get("rule_template_id") or ""),
            rule_doc_path=str(raw.get("rule_doc_path") or ""),
            related_faults=list(raw.get("related_faults") or []),
            suppresses_faults=list(raw.get("suppresses_faults") or []),
            suppressed_by_faults=list(raw.get("suppressed_by_faults") or []),
            legacy_aliases=list(raw.get("legacy_aliases") or []),
            standards_crosswalk=StandardsCrosswalk.from_dict(raw.get("standards_crosswalk")),
            tuning_params=TuningParams.from_dict(raw.get("tuning_params")),
            evidence_fields=list(raw.get("evidence_fields") or []),
            operator_guidance=OperatorGuidance.from_dict(raw.get("operator_guidance")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "canonical_id": self.canonical_id,
            "family": self.family,
            "system_type": self.system_type,
            "subsystem": self.subsystem,
            "component": self.component,
            "fault_mode": self.fault_mode,
            "symptom": self.symptom,
            "title": self.title,
            "likely_causes": self.likely_causes,
            "severity_default": self.severity_default,
            "category": self.category,
            "required_point_roles": self.required_point_roles,
            "optional_point_roles": self.optional_point_roles,
            "rule_template_id": self.rule_template_id,
            "rule_doc_path": self.rule_doc_path,
            "related_faults": self.related_faults,
            "suppresses_faults": self.suppresses_faults,
            "suppressed_by_faults": self.suppressed_by_faults,
            "legacy_aliases": self.legacy_aliases,
            "standards_crosswalk": {
                "ornl_lbnl_taxonomy": self.standards_crosswalk.ornl_lbnl_taxonomy,
                "ashrae_g36_reference_type": self.standards_crosswalk.ashrae_g36_reference_type,
                "ashrae_207_reference_type": self.standards_crosswalk.ashrae_207_reference_type,
                "brick_classes": self.standards_crosswalk.brick_classes,
                "haystack_tags": self.standards_crosswalk.haystack_tags,
            },
            "tuning_params": {
                "thresholds": self.tuning_params.thresholds,
                "deadbands": self.tuning_params.deadbands,
                "minimum_runtime_minutes": self.tuning_params.minimum_runtime_minutes,
                "persistence_minutes": self.tuning_params.persistence_minutes,
                "confidence_min": self.tuning_params.confidence_min,
                "seasonal_applicability": self.tuning_params.seasonal_applicability,
                "occupancy_applicability": self.tuning_params.occupancy_applicability,
            },
            "evidence_fields": self.evidence_fields,
            "operator_guidance": {
                "plain_english_summary": self.operator_guidance.plain_english_summary,
                "why_it_matters": self.operator_guidance.why_it_matters,
                "likely_fix_by_role": self.operator_guidance.likely_fix_by_role,
                "technician_checks": self.operator_guidance.technician_checks,
                "engineer_roi_notes": self.operator_guidance.engineer_roi_notes,
                "commissioning_notes": self.operator_guidance.commissioning_notes,
            },
        }


def _float_or_none(val: Any) -> float | None:
    if val is None or val == "":
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None
