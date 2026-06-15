"""Optional DataFusion SQL rule backend — Arrow in, Arrow fault mask out."""

from __future__ import annotations

import os
import re
import time
import traceback
from dataclasses import dataclass
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc

from .backend import ArrowRuleResult, normalize_fault_mask
from .summary import preview_fault_rows, summarize_arrow_run

TELEMETRY_TABLE = "telemetry"
DEFAULT_FAULT_COLUMN = "fault"

_DATAFUSION_INSTALL_MSG = (
    "DataFusion SQL backend is not installed. Install with: pip install 'open-fdd[datafusion]'"
)

_FORBIDDEN_SQL = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|COPY|ATTACH|DETACH|EXPLAIN|TRUNCATE|GRANT|REVOKE|"
    r"CALL|EXECUTE|PREPARE|MERGE|REPLACE|LOAD|UNLOAD|EXPORT|IMPORT)\b",
    re.IGNORECASE,
)

_FILE_OR_URL = re.compile(
    r"(?:file://|s3://|gs://|hdfs://|https?://|/[\w./-]+\.(?:csv|parquet|json|feather|arrow)\b)",
    re.IGNORECASE,
)

_READ_TABLE_FUNCS = re.compile(
    r"\bread_(?:parquet|csv|json|avro|_ndjson)\s*\(",
    re.IGNORECASE,
)

_FROM_TABLE = re.compile(r"\bFROM\s+([`\w.-]+)", re.IGNORECASE)
_JOIN_TABLE = re.compile(r"\bJOIN\s+([`\w.-]+)", re.IGNORECASE)


def _debug_tracebacks_enabled() -> bool:
    return os.environ.get("OFDD_DEBUG_TRACEBACKS", "").strip().lower() in ("1", "true", "yes")


@dataclass
class DataFusionSqlRule:
    """Restricted SQL rule body executed against the registered ``telemetry`` table."""

    sql: str
    fault_column: str = DEFAULT_FAULT_COLUMN


def datafusion_available() -> bool:
    """Return True when the optional ``datafusion`` PyPI package is importable."""
    try:
        import datafusion  # noqa: F401

        return True
    except ImportError:
        return False


def _strip_sql(sql: str) -> str:
    text = str(sql or "").strip()
    if text.endswith(";"):
        text = text[:-1].strip()
    return text


def lint_datafusion_sql_rule(sql: str, *, fault_column: str = DEFAULT_FAULT_COLUMN) -> dict[str, Any]:
    """Static SQL lint for fault-expression rules (no DataFusion install required)."""
    issues: list[dict[str, Any]] = []
    raw = str(sql or "").strip()
    if not raw:
        return {"ok": False, "issues": [{"message": "SQL is required", "severity": "error"}]}

    cleaned = _strip_sql(raw)
    if ";" in cleaned:
        issues.append({"message": "multiple SQL statements are not allowed", "severity": "error"})
    if not re.match(r"^\s*SELECT\b", cleaned, re.IGNORECASE):
        issues.append({"message": "SQL must be a single SELECT query", "severity": "error"})

    if _FORBIDDEN_SQL.search(cleaned):
        issues.append({"message": "DDL/DML keywords are not allowed in SQL rules", "severity": "error"})

    if _FILE_OR_URL.search(cleaned) or _READ_TABLE_FUNCS.search(cleaned):
        issues.append({"message": "file paths, URLs, and external table reads are not allowed", "severity": "error"})

    for match in _FROM_TABLE.finditer(cleaned):
        tbl = match.group(1).strip("`")
        if tbl.lower() != TELEMETRY_TABLE:
            issues.append(
                {
                    "message": f"SQL may only read FROM {TELEMETRY_TABLE}, not {tbl!r}",
                    "severity": "error",
                }
            )
    for match in _JOIN_TABLE.finditer(cleaned):
        tbl = match.group(1).strip("`")
        if tbl.lower() != TELEMETRY_TABLE:
            issues.append(
                {
                    "message": f"SQL may only JOIN {TELEMETRY_TABLE}, not {tbl!r}",
                    "severity": "error",
                }
            )

    if not re.search(rf"\bFROM\s+{re.escape(TELEMETRY_TABLE)}\b", cleaned, re.IGNORECASE):
        issues.append({"message": f"SQL must read FROM {TELEMETRY_TABLE}", "severity": "error"})

    fault_pat = rf"\bAS\s+{re.escape(fault_column)}\b|,\s*{re.escape(fault_column)}\s*[,)]"
    if not re.search(fault_pat, cleaned, re.IGNORECASE):
        issues.append(
            {
                "message": f"SQL must produce boolean column '{fault_column}'",
                "severity": "error",
            }
        )

    return {"ok": not any(i["severity"] == "error" for i in issues), "issues": issues}


def _import_datafusion():
    try:
        from datafusion import SessionContext
    except ImportError as exc:
        raise RuntimeError(_DATAFUSION_INSTALL_MSG) from exc
    return SessionContext


def _extract_fault_mask(result: pa.Table, *, fault_column: str, expected_len: int) -> pa.ChunkedArray:
    if fault_column not in result.column_names:
        raise ValueError(f"SQL must return a boolean column named '{fault_column}'")
    if result.num_rows != expected_len:
        raise ValueError(f"SQL row count {result.num_rows} != input rows {expected_len}")
    col = result.column(fault_column)
    return normalize_fault_mask(col, expected_len=expected_len)


def run_datafusion_sql_rule(
    sql: str,
    table: pa.Table,
    cfg: dict[str, Any] | None = None,
    *,
    context: dict[str, Any] | None = None,
    rule_id: str = "",
    fault_column: str = DEFAULT_FAULT_COLUMN,
    preview_columns: list[str] | None = None,
    preview_limit: int = 20,
) -> ArrowRuleResult:
    """Execute restricted DataFusion SQL against registered ``telemetry`` table."""
    started = time.perf_counter()
    cfg = dict(cfg or {})
    _ = context or {}
    fault_column = str(fault_column or DEFAULT_FAULT_COLUMN).strip() or DEFAULT_FAULT_COLUMN
    lint = lint_datafusion_sql_rule(sql, fault_column=fault_column)
    if not lint["ok"]:
        msgs = [i["message"] for i in lint["issues"] if i["severity"] == "error"]
        err = "DataFusion SQL invalid:\n" + "\n".join(msgs)
        mask = pa.array([False] * table.num_rows, type=pa.bool_())
        duration_ms = (time.perf_counter() - started) * 1000
        return ArrowRuleResult(
            rule_id=rule_id,
            backend="datafusion_sql",
            row_count=table.num_rows,
            true_count=0,
            false_count=table.num_rows,
            null_count=0,
            duration_ms=duration_ms,
            fault_mask=mask,
            errors=[err],
            summary={"error": err},
        )

    try:
        SessionContext = _import_datafusion()
        import pyarrow.dataset as ds

        ctx = SessionContext()
        ctx.register_table(TELEMETRY_TABLE, ds.InMemoryDataset(table))
        cleaned = _strip_sql(sql)
        df = ctx.sql(cleaned)
        result = df.to_arrow_table()
        mask = _extract_fault_mask(result, fault_column=fault_column, expected_len=table.num_rows)
    except Exception as exc:  # noqa: BLE001
        err = str(exc)
        mask = pa.array([False] * table.num_rows, type=pa.bool_())
        duration_ms = (time.perf_counter() - started) * 1000
        summary: dict[str, Any] = {"error": err}
        if _debug_tracebacks_enabled():
            summary["trace"] = traceback.format_exc(limit=6)
        return ArrowRuleResult(
            rule_id=rule_id,
            backend="datafusion_sql",
            row_count=table.num_rows,
            true_count=0,
            false_count=table.num_rows,
            null_count=0,
            duration_ms=duration_ms,
            fault_mask=mask,
            errors=[err],
            summary=summary,
        )

    from .events import count_mask_values

    counts = count_mask_values(mask)
    duration_ms = (time.perf_counter() - started) * 1000
    summary = summarize_arrow_run(
        table,
        mask,
        rule_id=rule_id,
        site_id=str(cfg.get("site_id") or ""),
        duration_ms=duration_ms,
        backend="datafusion_sql",
    )
    preview = preview_fault_rows(table, mask, columns=preview_columns, limit=preview_limit)
    return ArrowRuleResult(
        rule_id=rule_id,
        backend="datafusion_sql",
        row_count=counts["row_count"],
        true_count=counts["true_count"],
        false_count=counts["false_count"],
        null_count=counts["null_count"],
        duration_ms=duration_ms,
        fault_mask=mask,
        summary=summary,
        preview=preview,
    )


def equivalent_pyarrow_threshold_rule(column: str, threshold: float) -> str:
    """Generate a minimal PyArrow threshold rule for compare/migration helpers."""
    col_lit = repr(column)
    thresh_lit = repr(float(threshold))
    return f"""import pyarrow.compute as pc

def apply_faults_arrow(table, cfg, context=None):
    return pc.greater(table[{col_lit}], {thresh_lit})
"""
