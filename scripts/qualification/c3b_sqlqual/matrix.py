"""Machine-readable C3 SQL-QUAL acceptance matrix (C3b row)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


SCHEMA = "openfdd-c3-sqlqual-matrix-v1"


@dataclass
class QualCell:
    check_id: str
    status: str  # PASS | FAIL | BLOCKED | PENDING
    comparisons: int = 0
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class QualComponent:
    id: str
    phase: str
    status: str
    checks: int
    comparisons: int
    cells: list[QualCell] = field(default_factory=list)
    c5_pending: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "phase": self.phase,
            "status": self.status,
            "checks": self.checks,
            "comparisons": self.comparisons,
            "c5_pending": list(self.c5_pending),
            "cells": [c.to_dict() for c in self.cells],
        }


@dataclass
class QualMatrix:
    schema: str
    candidate_rev: str
    db_hydrated: bool
    components: list[QualComponent]
    errors: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "candidate_rev": self.candidate_rev,
            "db_hydrated": self.db_hydrated,
            "components": [c.to_dict() for c in self.components],
            "errors": list(self.errors),
        }

    def write_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def rollup_status(cells: list[QualCell]) -> str:
    if any(c.status == "FAIL" for c in cells):
        return "FAIL"
    if any(c.status == "BLOCKED" for c in cells):
        return "BLOCKED"
    if cells and all(c.status == "PENDING" for c in cells):
        return "PENDING"
    if any(c.status == "PENDING" for c in cells):
        # Mixed C3 PASS + explicit C5 PENDING markers
        if any(c.status == "PASS" for c in cells):
            return "PASS"
        return "PENDING"
    return "PASS" if cells else "BLOCKED"


def component_from_cells(
    component_id: str,
    *,
    phase: str,
    cells: list[QualCell],
    c5_pending: tuple[str, ...] = (),
) -> QualComponent:
    comparisons = sum(c.comparisons for c in cells)
    return QualComponent(
        id=component_id,
        phase=phase,
        status=rollup_status(cells),
        checks=len(cells),
        comparisons=comparisons,
        cells=cells,
        c5_pending=c5_pending,
    )
