"""Arrow-native run summaries — JSON-safe dicts for API/UI."""

from __future__ import annotations

from typing import Any

import pyarrow as pa

from .events import count_mask_values, detect_fault_episodes


def summarize_arrow_run(
    table: pa.Table,
    mask: pa.Array | pa.ChunkedArray,
    *,
    rule_id: str = "",
    site_id: str = "",
    equipment_id: str = "",
    duration_ms: float = 0.0,
    backend: str = "arrow",
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    counts = count_mask_values(mask)
    row_count = counts["row_count"]
    true_count = counts["true_count"]
    pct = (100.0 * true_count / row_count) if row_count else 0.0
    episodes = detect_fault_episodes(table, mask, rule_id=rule_id)
    first_ts = episodes[0].get("first_ts") if episodes else None
    last_ts = episodes[-1].get("last_ts") if episodes else None
    if not first_ts and "timestamp" in table.column_names and true_count:
        ts_col = table["timestamp"].combine_chunks().to_pylist()
        from .arrays import as_array

        for i, hit in enumerate(as_array(mask).to_pylist()):
            if hit:
                first_ts = str(ts_col[i])
                break
        for i in range(len(ts_col) - 1, -1, -1):
            if as_array(mask)[i].as_py():
                last_ts = str(ts_col[i])
                break
    return {
        "rule_id": rule_id,
        "backend": backend,
        "site_id": site_id,
        "equipment_id": equipment_id,
        "row_count": row_count,
        "fault_rows": true_count,
        "fault_percentage": round(pct, 4),
        "first_fault_ts": first_ts,
        "last_fault_ts": last_ts,
        "episode_count": len(episodes),
        "episodes": episodes[:50],
        "duration_ms": round(duration_ms, 2),
        "batch_count": table.num_rows and max(1, (row_count + 49_999) // 50_000) or 0,
        "warnings": warnings or [],
        **counts,
    }


def preview_fault_rows(
    table: pa.Table,
    mask: pa.Array | pa.ChunkedArray,
    *,
    columns: list[str] | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    from .arrays import as_array

    m = as_array(mask)
    sel = table
    if columns:
        keep = [c for c in columns if c in table.column_names]
        if keep:
            sel = table.select(keep)
    rows: list[dict[str, Any]] = []
    for i in range(min(len(m), sel.num_rows)):
        if m[i].as_py():
            row = {name: sel[name][i].as_py() for name in sel.column_names}
            rows.append(row)
            if len(rows) >= limit:
                break
    return rows
