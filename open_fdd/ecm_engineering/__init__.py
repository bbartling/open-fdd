"""Open-FDD ECM engineering toolkit."""
from .algorithms import calculate, list_calculators
from .crosscheck import crosscheck
from .finance import npv, simple_payback
from .job import ECMJob
from .provenance import EvidenceValue, ProvenanceClass
from .workbook import OpenFDDECMWorkbook, create_workbook

__all__ = [
    "calculate",
    "list_calculators",
    "crosscheck",
    "npv",
    "simple_payback",
    "ECMJob",
    "EvidenceValue",
    "ProvenanceClass",
    "OpenFDDECMWorkbook",
    "create_workbook",
]

__version__ = "4.0.0"
