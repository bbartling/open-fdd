"""Rules Lab helpers — server-side DataFusion SQL validate/preview/compare."""

from __future__ import annotations

import re
import time
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc

from open_fdd.arrow_runtime.backend import run_arrow_rule
from open_fdd.arrow_runtime.datafusion_backend import (
    datafusion_available,
    lint_datafusion_sql_rule,
    run_datafusion_sql_rule,
)
from open_fdd.arrow_runtime.rules import detect_rule_backend

from .data_loader import load_arrow_table_for_run
from .rule_store import RuleStore
from .security import debug_tracebacks_enabled


def _trim_table(table: pa.Table, *, limit: int, lookback_hours: float) -> pa.Table:
    if lookback_hours > 0 and "timestamp" in table.column_names:
        from open_fdd.arrow_runtime.features import arrow_time_filter
        import datetime as _dt

        cutoff = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=lookback_hours)
        table = arrow_time_filter(table, "timestamp", cutoff, None)
    if limit and table.num_rows > limit:
        table = table.slice(max(0, table.num_rows - limit), min(limit, table.num_rows))
    return table


def load_lab_sample_table(
    site_id: str,
    *,
    limit: int = 500,
    lookback_hours: float = 24,
) -> tuple[pa.Table, str]:
    """Load a bounded Arrow telemetry sample for Rules Lab validate/preview."""
    table, origin = load_arrow_table_for_run(site_id)
    if not isinstance(table, pa.Table):
        table = pa.Table.from_pandas(table)
    table = _trim_table(table, limit=limit, lookback_hours=lookback_hours)
    return table, origin


def _sql_column_ref(name: str) -> str:
    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name):
        return name
    return '"' + name.replace('"', '""') + '"'


def _column_kind(name: str, kinds: dict[str, str]) -> str:
    if name in kinds:
        return kinds[name]
    if name in ("timestamp", "ts"):
        return "time"
    if name in ("site_id", "equipment_id"):
        return "meta"
    return "value"


def build_rule_lab_data_context(
    *,
    site_id: str,
    limit: int = 200,
    lookback_hours: float = 24,
) -> dict[str, Any]:
    """Column names and usage hints for PyArrow + DataFusion SQL rules."""
    from .timeseries_api import list_plot_series

    table, origin = load_lab_sample_table(site_id, limit=limit, lookback_hours=lookback_hours)
    meta = list_plot_series(site_id)
    labels = dict(meta.get("labels") or {})
    kinds = dict(meta.get("kinds") or {})
    columns: list[dict[str, str]] = []
    for name in table.column_names:
        columns.append(
            {
                "name": name,
                "label": str(labels.get(name) or name),
                "kind": _column_kind(name, kinds),
                "sql_ref": _sql_column_ref(name),
                "arrow_ref": f'table[{name!r}]',
            }
        )
    return {
        "site_id": site_id,
        "data_source": origin,
        "row_count": int(table.num_rows),
        "sql_table": "telemetry",
        "columns": columns,
        "series_options": meta.get("series_options") or [],
        "equipment_groups": meta.get("equipment_groups") or [],
    }


def _result_payload(result, *, site_id: str = "", data_source: str = "") -> dict[str, Any]:
    payload = result.as_dict()
    payload["ok"] = not result.errors
    payload["site_id"] = site_id
    payload["data_source"] = data_source
    if result.errors:
        payload["error"] = result.errors[0]
        if debug_tracebacks_enabled() and isinstance(result.summary, dict):
            payload["details"] = result.summary.get("trace") or result.summary.get("error")
    return payload


def compare_fault_mask_stats(
    left_mask: pa.Array | pa.ChunkedArray,
    right_mask: pa.Array | pa.ChunkedArray,
) -> tuple[int, int, pa.Array | pa.ChunkedArray]:
    """Count matching/mismatching rows with null-aware semantics.

    null vs null counts as a match; null vs true/false counts as a mismatch.
    """
    equal_raw = pc.equal(left_mask, right_mask)
    both_null = pc.and_(pc.is_null(left_mask), pc.is_null(right_mask))
    equal = pc.fill_null(pc.or_(pc.fill_null(equal_raw, False), both_null), False)
    mismatch = pc.invert(equal)
    mismatch_count = int(pc.sum(pc.cast(mismatch, pa.int64())).as_py() or 0)
    matching = len(left_mask) - mismatch_count
    return matching, mismatch_count, mismatch


def validate_datafusion_sql(
    *,
    sql: str,
    fault_column: str = "fault",
    site_id: str,
    limit: int = 500,
    lookback_hours: float = 24,
) -> dict[str, Any]:
    """Lint and optionally execute SQL against latest site telemetry."""
    lint = lint_datafusion_sql_rule(sql, fault_column=fault_column)
    if not lint["ok"]:
        msgs = [i["message"] for i in lint["issues"] if i["severity"] == "error"]
        return {
            "ok": False,
            "backend": "datafusion_sql",
            "error": msgs[0] if msgs else "SQL validation failed",
            "details": "\n".join(msgs),
            "issues": lint["issues"],
        }
    if not datafusion_available():
        return {
            "ok": False,
            "backend": "datafusion_sql",
            "error": "DataFusion SQL backend is not installed on this Open-FDD runtime.",
            "details": "Install the optional extra: pip install 'open-fdd[datafusion]'",
            "datafusion_installed": False,
        }
    table, origin = load_lab_sample_table(site_id, limit=limit, lookback_hours=lookback_hours)
    result = run_datafusion_sql_rule(
        sql,
        table,
        {"site_id": site_id},
        rule_id="lab-validate",
        fault_column=fault_column,
    )
    if result.errors:
        return {
            "ok": False,
            "backend": "datafusion_sql",
            "error": result.errors[0],
            "details": result.summary.get("trace") if debug_tracebacks_enabled() else result.errors[0],
            "row_count": result.row_count,
        }
    return {
        "ok": True,
        "backend": "datafusion_sql",
        "columns": list(table.column_names),
        "fault_column": fault_column,
        "row_count": result.row_count,
        "true_count": result.true_count,
        "false_count": result.false_count,
        "null_count": result.null_count,
        "preview": result.preview,
        "data_source": origin,
        "duration_ms": result.duration_ms,
        "datafusion_installed": True,
    }


def preview_datafusion_sql(
    *,
    sql: str,
    fault_column: str = "fault",
    site_id: str,
    limit: int = 500,
    lookback_hours: float = 24,
) -> dict[str, Any]:
    started = time.time()
    out = validate_datafusion_sql(
        sql=sql,
        fault_column=fault_column,
        site_id=site_id,
        limit=limit,
        lookback_hours=lookback_hours,
    )
    out["ms"] = int((time.time() - started) * 1000)
    if out.get("ok"):
        total = int(out.get("row_count") or 0)
        true_n = int(out.get("true_count") or 0)
        out["fault_rate_pct"] = round(100.0 * true_n / total, 2) if total else 0.0
    return out


def compare_rule_backends(
    *,
    left: dict[str, Any],
    right: dict[str, Any],
    site_id: str,
    limit: int = 1000,
    lookback_hours: float = 24,
) -> dict[str, Any]:
    """Compare PyArrow and DataFusion SQL fault masks on the same telemetry sample."""
    table, origin = load_lab_sample_table(site_id, limit=limit, lookback_hours=lookback_hours)
    left_backend = str(left.get("backend") or "").strip()
    right_backend = str(right.get("backend") or "").strip()

    def _run_side(side: dict[str, Any], backend: str):
        if backend == "datafusion_sql":
            if not datafusion_available():
                raise ValueError(
                    "DataFusion SQL backend is not installed. Install with: pip install 'open-fdd[datafusion]'"
                )
            sql = str(side.get("sql") or "").strip()
            fault_column = str(side.get("fault_column") or "fault")
            return run_datafusion_sql_rule(
                sql,
                table,
                {"site_id": site_id},
                rule_id="lab-compare",
                fault_column=fault_column,
            )
        if backend == "arrow":
            code = str(side.get("code") or "").strip()
            rule_id = str(side.get("rule_id") or "").strip()
            if rule_id and not code:
                rule = RuleStore().get(rule_id) or {}
                code = str(rule.get("code") or "")
            if not code:
                raise ValueError("arrow compare requires code or rule_id")
            return run_arrow_rule(code, table, dict(side.get("config") or {}), rule_id=rule_id or "compare")
        raise ValueError(f"unsupported compare backend: {backend}")

    try:
        left_result = _run_side(left, left_backend)
        right_result = _run_side(right, right_backend)
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "error": str(exc),
            "details": str(exc) if debug_tracebacks_enabled() else None,
            "data_source": origin,
        }

    if left_result.errors or right_result.errors:
        return {
            "ok": False,
            "error": (left_result.errors or right_result.errors)[0],
            "left_backend": left_backend,
            "right_backend": right_backend,
            "data_source": origin,
        }

    left_mask = left_result.fault_mask
    right_mask = right_result.fault_mask
    if len(left_mask) != len(right_mask):
        return {
            "ok": False,
            "error": f"mask length mismatch {len(left_mask)} vs {len(right_mask)}",
            "data_source": origin,
        }

    matching, mismatch_count, mismatch = compare_fault_mask_stats(left_mask, right_mask)

    mismatches_preview: list[dict[str, Any]] = []
    if mismatch_count > 0:
        idx = pc.indices_nonzero(mismatch).to_pylist()[:20]
        for i in idx:
            row: dict[str, Any] = {"row_index": i, "left_fault": left_mask[i].as_py(), "right_fault": right_mask[i].as_py()}
            for col in ("timestamp", "equipment_id", "site_id"):
                if col in table.column_names:
                    row[col] = table.column(col)[i].as_py()
            mismatches_preview.append(row)

    return {
        "ok": True,
        "left_backend": left_backend,
        "right_backend": right_backend,
        "left_true_count": left_result.true_count,
        "right_true_count": right_result.true_count,
        "matching_rows": matching,
        "mismatching_rows": mismatch_count,
        "mismatches_preview": mismatches_preview,
        "row_count": table.num_rows,
        "data_source": origin,
    }


def detect_backend_from_payload(payload: dict[str, Any]) -> str:
    return detect_rule_backend(str(payload.get("code") or ""), payload)
