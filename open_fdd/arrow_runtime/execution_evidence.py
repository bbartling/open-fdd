"""Execution-path metadata for Arrow/DataFusion FDD runs (smoke audits, Rule Lab)."""

from __future__ import annotations

from typing import Any

import pyarrow as pa

from .arrays import as_array
from .confirmation import CONFIRMATION_ENGINE

COMPUTATION_PATH_ARROW = "pyarrow_compute"
COMPUTATION_PATH_DATAFUSION = "datafusion_sql"
COMPUTATION_PATH_PYTHON_LIST = "python_list"


def mask_type_name(mask: pa.Array | pa.ChunkedArray) -> str:
    arr = as_array(mask)
    if isinstance(mask, pa.ChunkedArray):
        return f"ChunkedArray[{arr.type}]"
    return f"Array[{arr.type}]"


def build_execution_evidence(
    *,
    table: pa.Table,
    mask: pa.Array | pa.ChunkedArray,
    backend: str,
    computation_path: str,
    confirmation_applied: bool,
) -> dict[str, Any]:
    """Structured evidence that core FDD crunching used Arrow/DataFusion, not Python lists."""
    chunks = table.chunks if hasattr(table, "chunks") else table.to_batches()
    return {
        "backend": backend,
        "input_table_type": type(table).__name__,
        "input_schema": str(table.schema),
        "result_mask_type": mask_type_name(mask),
        "computation_path": computation_path,
        "confirmation_applied": confirmation_applied,
        "confirmation_engine": CONFIRMATION_ENGINE if confirmation_applied else "none",
        "arrow_num_rows": table.num_rows,
        "arrow_num_columns": table.num_columns,
        "arrow_chunk_count": len(chunks),
        "python_list_warnings": [],
    }


def validate_computation_path(evidence: dict[str, Any]) -> list[str]:
    """Return errors when execution evidence indicates forbidden python_list crunching."""
    errors: list[str] = []
    path = str(evidence.get("computation_path") or "")
    if path == COMPUTATION_PATH_PYTHON_LIST:
        errors.append("FDD computation_path is python_list (forbidden for core crunching)")
    if path not in (COMPUTATION_PATH_ARROW, COMPUTATION_PATH_DATAFUSION, "none", ""):
        errors.append(f"unknown computation_path: {path!r}")
    return errors
