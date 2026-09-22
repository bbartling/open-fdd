"""Open-FDD ECM engineering toolkit."""
from .algorithms import calculate, list_calculators
from .crosscheck import crosscheck
from .finance import npv, simple_payback
from .honesty_status import MeasureHonestyStatus, classify_measure_status
from .job import ECMJob, list_ecm_modules
from .provenance import EvidenceValue, ProvenanceClass
from .workbook import OpenFDDECMWorkbook, create_workbook
from .contracts import (
    EngineeringInput,
    MeasureResultMeta,
    validate_engineering_inputs,
    validate_simulation_evidence,
)
from .context_envelope import (
    ECM_CONTEXT_SCHEMA_VERSION,
    EcmContext,
    ReadinessStatus,
    assess_screening_gaps,
    combine_schedule_then_fan_reset,
    validate_ecm_context,
)
from .calc_trace import CalculationTrace
from .stage2_workbook import build_stage2_workbook
from .g14 import (
    G14Score,
    cvrmse_pct,
    g14_thresholds,
    nmbe_pct,
    score_g14,
    score_g14_fuels,
    score_g14_monthly,
)


def build_honesty_workbook(*args, **kwargs):
    from .honesty_export import build_honesty_workbook as _build

    return _build(*args, **kwargs)


def fit_changepoint(*args, **kwargs):
    from .changepoint import fit_changepoint as _fit

    return _fit(*args, **kwargs)


def select_changepoint(*args, **kwargs):
    from .changepoint import select_changepoint as _select

    return _select(*args, **kwargs)


def option_c_savings(*args, **kwargs):
    from .changepoint import option_c_savings as _opt

    return _opt(*args, **kwargs)


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
    "ECM_CONTEXT_SCHEMA_VERSION",
    "EcmContext",
    "ReadinessStatus",
    "assess_screening_gaps",
    "combine_schedule_then_fan_reset",
    "validate_ecm_context",
    "CalculationTrace",
    "build_stage2_workbook",
    "build_honesty_workbook",
    "MeasureHonestyStatus",
    "classify_measure_status",
    "G14Score",
    "nmbe_pct",
    "cvrmse_pct",
    "g14_thresholds",
    "score_g14",
    "score_g14_monthly",
    "score_g14_fuels",
    "fit_changepoint",
    "select_changepoint",
    "option_c_savings",
]
