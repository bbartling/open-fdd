"""Open-FDD ECM engineering toolkit."""
from .algorithms import calculate, list_calculators
from .crosscheck import crosscheck
from .finance import npv, simple_payback
from .job import ECMJob, list_ecm_modules
from .provenance import EvidenceValue, ProvenanceClass
from .workbook import OpenFDDECMWorkbook, create_workbook
from .contracts import (
    EngineeringInput,
    MeasureResultMeta,
    validate_engineering_inputs,
    validate_simulation_evidence,
)
from .calc_trace import CalculationTrace
from .stage2_workbook import build_stage2_workbook

__all__ = [
    "calculate",
    "list_calculators",
    "list_ecm_modules",
    "crosscheck",
    "npv",
    "simple_payback",
    "ECMJob",
    "EvidenceValue",
    "ProvenanceClass",
    "OpenFDDECMWorkbook",
    "create_workbook",
    "EngineeringInput",
    "MeasureResultMeta",
    "validate_engineering_inputs",
    "validate_simulation_evidence",
    "CalculationTrace",
    "build_stage2_workbook",
]
