"""Stage-1 ECM contracts: dual-rail inputs, scopes, evidence, publication previews."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class ResultScope(StrEnum):
    WHOLE_BUILDING = "whole_building"
    MODEL_AIR_SYSTEM = "model_air_system"
    PHYSICAL_AHU = "physical_ahu"
    FLOOR_PROXY = "floor_proxy"
    ZONE_PROXY = "zone_proxy"
    PLANT = "plant"
    METER = "meter"


class AllocationStatus(StrEnum):
    NOT_ALLOCATED = "not_allocated"
    DIRECTLY_METERED = "directly_metered"
    MODEL_METERED = "model_metered"
    ENGINEERING_ALLOCATION = "engineering_allocation"
    PROXY_ALLOCATION = "proxy_allocation"


class ComparisonMode(StrEnum):
    VS_COMMON_BASELINE = "vs_common_baseline"
    SEQUENTIAL_INCREMENT = "sequential_increment"
    EXPLICIT_PACKAGE = "explicit_package"
    MEASURED_PRE_POST = "measured_pre_post"


class AdditiveStatus(StrEnum):
    NON_ADDITIVE = "non_additive"
    ADDITIVE_WITHIN_DEFINED_BOUNDARY = "additive_within_defined_boundary"
    EXPLICIT_PACKAGE_RESULT = "explicit_package_result"
    SEQUENTIAL_INCREMENT = "sequential_increment"


class InteractionStatus(StrEnum):
    NOT_EVALUATED = "not_evaluated"
    ESTIMATED = "estimated"
    SIMULATED = "simulated"
    MEASURED = "measured"


class InputRail(StrEnum):
    SPREADSHEET = "spreadsheet"
    ENERGYPLUS = "energyplus"
    SHARED = "shared"


class SourceType(StrEnum):
    MEASURED = "measured"
    BAS_DERIVED = "BAS_derived"
    UTILITY_BILL = "utility_bill"
    INTERVAL_METER = "interval_meter"
    TAB_REPORT = "TAB_report"
    NAMEPLATE = "nameplate"
    DESIGN_DOCUMENT = "design_document"
    CONTRACTOR_QUOTE = "contractor_quote"
    ENERGYPLUS_AUTOSIZED = "EnergyPlus_autosized"
    ENERGYPLUS_DERIVED = "EnergyPlus_derived"
    PUBLIC_BENCHMARK = "public_benchmark"
    ENGINEERING_ASSUMPTION = "engineering_assumption"
    AGENT_INFERRED = "agent_inferred"
    HUMAN_ENTERED = "human_entered"
    SYNTHETIC_REHEARSAL = "synthetic_rehearsal"


class AssumptionMethod(StrEnum):
    NAMEPLATE = "nameplate"
    EIO_AUTOSIZE = "eio_autosize"
    AMY_CALENDAR_HOURS = "amy_calendar_hours"
    FLH_FROM_CASCADE = "flh_from_cascade"
    BIN_METHOD = "bin_method"
    TAB_REPORT = "tab_report"
    OPERATOR_ENTRY = "operator_entry"
    ENGINEERING_JUDGMENT = "engineering_judgment"
    UNKNOWN = "unknown"


_NEEDS_ASSUMPTION_NOTE = frozenset(
    {
        SourceType.AGENT_INFERRED,
        SourceType.ENGINEERING_ASSUMPTION,
        SourceType.ENERGYPLUS_DERIVED,
        SourceType.SYNTHETIC_REHEARSAL,
    }
)


@dataclass
class EngineeringInput:
    input_id: str
    display_name: str
    value: Any
    unit: str
    rail: InputRail
    source_type: SourceType
    confidence: str = "unknown"
    editable: bool = True
    validation_status: str = "ok"
    validation_message: str = ""
    assumption_note: str = ""
    assumption_method: AssumptionMethod = AssumptionMethod.UNKNOWN
    linked_measure_ids: list[str] = field(default_factory=list)
    source_reference: str = ""
    notes: str = ""

    def requires_assumption_note(self) -> bool:
        if self.source_type in _NEEDS_ASSUMPTION_NOTE:
            return True
        # Hour / FLH style inputs always need a note when agent- or judgment-derived.
        lid = self.input_id.lower()
        if "hour" in lid or lid.endswith("_flh") or "hours_saved" in lid:
            return self.source_type != SourceType.MEASURED and self.source_type != SourceType.HUMAN_ENTERED
        return False

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["rail"] = self.rail.value
        d["source_type"] = self.source_type.value
        d["assumption_method"] = self.assumption_method.value
        return d


@dataclass
class MeasureResultMeta:
    measure_id: str
    result_scope: ResultScope
    allocation_status: AllocationStatus
    comparison_mode: ComparisonMode
    additive_status: AdditiveStatus
    interaction_status: InteractionStatus = InteractionStatus.NOT_EVALUATED
    baseline_run_id: str = ""
    proposed_run_id: str = ""
    preceding_run_id: str | None = None
    package_id: str | None = None
    physical_system_id: str | None = None
    model_object_ids: list[str] = field(default_factory=list)
    overlap_groups: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        for key, enum_val in (
            ("result_scope", self.result_scope),
            ("allocation_status", self.allocation_status),
            ("comparison_mode", self.comparison_mode),
            ("additive_status", self.additive_status),
            ("interaction_status", self.interaction_status),
        ):
            d[key] = enum_val.value
        return d


EVIDENCE_SCHEMA_VERSION = "ecm_simulation_evidence_v1"


def validate_engineering_inputs(inputs: list[EngineeringInput]) -> list[str]:
    """Return validation issues (empty = ok)."""
    issues: list[str] = []
    for inp in inputs:
        src_ref = (inp.source_reference or "").lower()
        if inp.source_type == SourceType.MEASURED and "energyplus" in src_ref:
            issues.append(
                f"{inp.input_id}: EnergyPlus-derived values must not be labeled measured"
            )
        if inp.source_type == SourceType.MEASURED and inp.rail == InputRail.ENERGYPLUS:
            issues.append(
                f"{inp.input_id}: EnergyPlus rail values must not be labeled measured"
            )
        if inp.requires_assumption_note() and not (inp.assumption_note or "").strip():
            issues.append(
                f"{inp.input_id}: assumption_note required for {inp.source_type.value} / estimated hours"
            )
    return issues


def validate_measure_meta(meta: MeasureResultMeta) -> list[str]:
    issues: list[str] = []
    if (
        meta.result_scope == ResultScope.PHYSICAL_AHU
        and meta.allocation_status == AllocationStatus.NOT_ALLOCATED
    ):
        issues.append(
            f"{meta.measure_id}: physical_ahu requires allocation evidence "
            f"(allocation_status != not_allocated)"
        )
    if (
        meta.additive_status == AdditiveStatus.EXPLICIT_PACKAGE_RESULT
        and meta.comparison_mode == ComparisonMode.VS_COMMON_BASELINE
        and not meta.package_id
    ):
        issues.append(
            f"{meta.measure_id}: explicit package result needs package_id "
            "(independent vs_baseline rows are non_additive)"
        )
    return issues


def validate_simulation_evidence(doc: dict[str, Any], *, strict: bool = True) -> list[str]:
    """Validate vibe20 ecm_simulation_evidence.json shape."""
    issues: list[str] = []
    if not isinstance(doc, dict):
        return ["evidence root must be an object"]
    ver = doc.get("schema_version")
    if ver != EVIDENCE_SCHEMA_VERSION:
        issues.append(
            f"schema_version must be {EVIDENCE_SCHEMA_VERSION!r}, got {ver!r}"
        )
    for key in ("project", "facility", "baseline", "model", "individual_measures"):
        if key not in doc:
            issues.append(f"missing required top-level key: {key}")
    if strict:
        known = {
            "schema_version",
            "project",
            "facility",
            "baseline",
            "calibration",
            "model",
            "weather",
            "equipment_autosizing",
            "individual_measures",
            "package_runs",
            "sequential_cascades",
            "run_artifacts",
            "warnings",
        }
        for k in doc:
            if k not in known:
                issues.append(f"unknown field (strict): {k}")
    measures = doc.get("individual_measures") or []
    if not isinstance(measures, list):
        issues.append("individual_measures must be a list")
    else:
        for i, m in enumerate(measures):
            if not isinstance(m, dict):
                issues.append(f"individual_measures[{i}] must be an object")
                continue
            for req in ("measure_id", "run_id", "baseline_run_id", "comparison_mode", "result_scope"):
                if req not in m:
                    issues.append(f"individual_measures[{i}] missing {req}")
            if m.get("result_scope") == ResultScope.PHYSICAL_AHU.value:
                if m.get("allocation_status") in (None, AllocationStatus.NOT_ALLOCATED.value):
                    issues.append(
                        f"individual_measures[{i}]: physical_ahu without allocation evidence"
                    )
    return issues


def list_missing_inputs(inputs: list[EngineeringInput]) -> list[str]:
    missing: list[str] = []
    for inp in inputs:
        if inp.value is None or inp.value == "":
            missing.append(inp.input_id)
        elif inp.validation_status == "missing":
            missing.append(inp.input_id)
    return missing


__all__ = [
    "ResultScope",
    "AllocationStatus",
    "ComparisonMode",
    "AdditiveStatus",
    "InteractionStatus",
    "InputRail",
    "SourceType",
    "AssumptionMethod",
    "EngineeringInput",
    "MeasureResultMeta",
    "EVIDENCE_SCHEMA_VERSION",
    "validate_engineering_inputs",
    "validate_measure_meta",
    "validate_simulation_evidence",
    "list_missing_inputs",
]
