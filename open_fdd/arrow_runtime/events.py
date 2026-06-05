"""Arrow-native fault episode detection."""

from __future__ import annotations

from typing import Any

import pyarrow as pa
import pyarrow.compute as pc

from .arrays import as_array


def detect_fault_episodes(
    table: pa.Table,
    mask: pa.Array | pa.ChunkedArray,
    *,
    ts_column: str = "timestamp",
    rule_id: str = "",
) -> list[dict[str, Any]]:
    """Contiguous true runs in ``mask``; carries state across ChunkedArray chunks."""
    m = as_array(mask).cast(pa.bool_())
    n = len(m)
    if n == 0:
        return []
    ts_vals: list[Any] = []
    if ts_column in table.column_names:
        ts_vals = as_array(table[ts_column]).to_pylist()
    episodes: list[dict[str, Any]] = []
    start: int | None = None
    for i in range(n):
        hit = bool(m[i].as_py())
        if hit and start is None:
            start = i
        elif not hit and start is not None:
            episodes.append(_episode_row(start, i - 1, ts_vals, rule_id))
            start = None
    if start is not None:
        episodes.append(_episode_row(start, n - 1, ts_vals, rule_id))
    return episodes


def _episode_row(start: int, end: int, ts_vals: list[Any], rule_id: str) -> dict[str, Any]:
    row: dict[str, Any] = {
        "rule_id": rule_id,
        "start_index": start,
        "end_index": end,
        "samples": end - start + 1,
    }
    if ts_vals:
        if start < len(ts_vals):
            row["first_ts"] = str(ts_vals[start])
        if end < len(ts_vals):
            row["last_ts"] = str(ts_vals[end])
    return row


from .arrays import as_array


def count_mask_values(mask: pa.Array | pa.ChunkedArray) -> dict[str, int]:
    m = as_array(mask)
    if not pa.types.is_boolean(m.type):
        m = pc.cast(m, pa.bool_())
    n = len(m)
    true_count = int(pc.sum(pc.cast(m, pa.int64())).as_py() or 0)
    null_count = int(pc.sum(pc.is_null(m).cast(pa.int64())).as_py() or 0)
    false_count = max(0, n - true_count - null_count)
    return {
        "row_count": n,
        "true_count": true_count,
        "false_count": false_count,
        "null_count": null_count,
    }
