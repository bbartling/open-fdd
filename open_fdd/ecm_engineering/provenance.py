from __future__ import annotations
from dataclasses import dataclass, asdict
from enum import StrEnum
from typing import Any

class ProvenanceClass(StrEnum):
    MEASURED = "MEASURED"
    MAPPED_BAS = "MAPPED_BAS"
    WEB_WEATHER = "WEB_WEATHER"
    UTILITY_RECORD = "UTILITY_RECORD"
    DRAWING = "DRAWING"
    NAMEPLATE = "NAMEPLATE"
    USER_ENTERED = "USER_ENTERED"
    AUTOSIZED = "AUTOSIZED"
    INFERRED = "INFERRED"
    ARCHETYPE_DEFAULT = "ARCHETYPE_DEFAULT"
    LIBRARY_DEFAULT = "LIBRARY_DEFAULT"
    CALIBRATED = "CALIBRATED"
    VALIDATED = "VALIDATED"
    ENERGYPLUS_SIMULATED = "ENERGYPLUS_SIMULATED"
    DERIVED = "DERIVED"
    UNKNOWN = "UNKNOWN"

@dataclass(frozen=True)
class EvidenceValue:
    value: Any
    provenance: ProvenanceClass
    source: str = ""
    method: str = ""
    confidence: str = "unknown"
    timestamp: str | None = None

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["provenance"] = self.provenance.value
        return data
