"""Calculation trace object for Stage-1 ECM contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class CalculationTrace:
    trace_id: str
    equation_id: str
    equation_text: str
    inputs_used: list[str] = field(default_factory=list)
    intermediate: dict[str, Any] = field(default_factory=dict)
    result: Any = None
    unit: str = ""
    comparison_mode: str = ""
    notes: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = ["CalculationTrace"]
