"""Arrow vs DataFusion SQL parity helpers for paired FDD smoke."""

from __future__ import annotations

from typing import Any

import pyarrow as pa
import pyarrow.compute as pc

from open_fdd.arrow_runtime.events import count_mask_values


def mask_value_counts(mask: pa.Array | pa.ChunkedArray) -> dict[str, int]:
    counts = count_mask_values(mask)
    return {
        "true_count": int(counts.get("true_count") or 0),
        "false_count": int(counts.get("false_count") or 0),
        "null_count": int(counts.get("null_count") or 0),
        "row_count": int(counts.get("row_count") or 0),
    }


def masks_equal(
    left: pa.Array | pa.ChunkedArray,
    right: pa.Array | pa.ChunkedArray,
    *,
    float_tol: float = 1e-9,
) -> bool:
    if len(left) != len(right):
        return False
    if pa.types.is_floating(left.type) or pa.types.is_floating(right.type):
        l = pc.cast(left, pa.float64())
        r = pc.cast(right, pa.float64())
        both_null = pc.and_(pc.is_null(l), pc.is_null(r))
        close = pc.less_equal(pc.abs(pc.subtract(l, r)), pa.scalar(float_tol))
        return bool(pc.all(pc.or_(both_null, close)).as_py())
    return bool(pc.all(pc.equal(left, right)).as_py())


def compare_fault_masks(
    arrow_mask: pa.Array | pa.ChunkedArray,
    sql_mask: pa.Array | pa.ChunkedArray,
    *,
    table: pa.Table | None = None,
    key_columns: tuple[str, ...] = ("timestamp", "equipment"),
) -> dict[str, Any]:
    """Compare boolean fault masks row-level and by aggregate counts."""
    issues: list[str] = []
    arrow_counts = mask_value_counts(arrow_mask)
    sql_counts = mask_value_counts(sql_mask)
    for key in ("true_count", "false_count", "null_count", "row_count"):
        if arrow_counts[key] != sql_counts[key]:
            issues.append(f"count mismatch {key}: arrow={arrow_counts[key]} sql={sql_counts[key]}")

    row_match = masks_equal(arrow_mask, sql_mask)
    if not row_match:
        issues.append("fault mask rows differ")
        if table is not None and all(c in table.column_names for c in key_columns):
            diff_idx = [
                i
                for i in range(len(arrow_mask))
                if not masks_equal(arrow_mask.slice(i, 1), sql_mask.slice(i, 1))
            ][:5]
            samples = []
            for i in diff_idx:
                row = {c: table.column(c)[i].as_py() for c in key_columns}
                row["arrow"] = arrow_mask[i].as_py()
                row["sql"] = sql_mask[i].as_py()
                samples.append(row)
            if samples:
                issues.append(f"sample mismatches: {samples}")

    return {
        "pass": not issues,
        "issues": issues,
        "arrow": arrow_counts,
        "sql": sql_counts,
        "row_match": row_match,
    }


def compare_batch_runs(arrow_run: dict[str, Any], sql_run: dict[str, Any]) -> list[str]:
    """Compare paired batch API run dicts when analytics fields are present."""
    issues: list[str] = []
    if int(arrow_run.get("flagged") or 0) != int(sql_run.get("flagged") or 0):
        issues.append(
            f"flagged mismatch arrow={arrow_run.get('flagged')} sql={sql_run.get('flagged')}"
        )
    if int(arrow_run.get("rows") or 0) != int(sql_run.get("rows") or 0):
        issues.append(f"rows mismatch arrow={arrow_run.get('rows')} sql={sql_run.get('rows')}")
    for field in ("true_count", "false_count", "null_count"):
        av = arrow_run.get(field)
        sv = sql_run.get(field)
        if av is not None and sv is not None and int(av) != int(sv):
            issues.append(f"{field} mismatch arrow={av} sql={sv}")
    a_an = arrow_run.get("analytics") if isinstance(arrow_run.get("analytics"), dict) else {}
    s_an = sql_run.get("analytics") if isinstance(sql_run.get("analytics"), dict) else {}
    for field in ("fault_samples", "total_samples", "estimated_fault_duration_sec"):
        av = a_an.get(field)
        sv = s_an.get(field)
        if av is not None and sv is not None and av != sv:
            issues.append(f"analytics.{field} mismatch arrow={av} sql={sv}")
    if arrow_run.get("error") or sql_run.get("error"):
        if arrow_run.get("error") != sql_run.get("error"):
            issues.append("backend error mismatch")
    return issues
