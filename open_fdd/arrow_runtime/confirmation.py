"""Fault confirmation — consecutive rows and elapsed-time filters on raw masks."""

from __future__ import annotations

# Engine identifier surfaced in smoke reports and execution evidence.
CONFIRMATION_ENGINE = "python_loop_over_arrow_mask"

import datetime as _dt
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc

from .arrays import as_array


def confirmation_window_configured(
    min_true_rows: int | None = None,
    min_elapsed_minutes: float | None = None,
) -> bool:
    """True when confirm_fault_mask would apply a window (not pass-through)."""
    rows_needed = int(min_true_rows) if min_true_rows is not None and int(min_true_rows) > 1 else None
    elapsed_needed = (
        float(min_elapsed_minutes) if min_elapsed_minutes is not None and float(min_elapsed_minutes) > 0 else None
    )
    return rows_needed is not None or elapsed_needed is not None


def _parse_timestamp(value: Any) -> _dt.datetime | None:
    if value is None:
        return None
    if isinstance(value, _dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=_dt.timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = _dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=_dt.timezone.utc)


def _confirm_elapsed_minutes(
    raw: pa.ChunkedArray,
    timestamps: pa.Array | pa.ChunkedArray,
    *,
    min_minutes: float,
) -> pa.ChunkedArray:
    """True only after raw fault has been continuously true for ``min_minutes``."""
    n = len(raw)
    raw_list = as_array(raw).to_pylist()
    ts_list = as_array(timestamps).to_pylist()
    out: list[bool] = []
    streak_start: _dt.datetime | None = None
    min_seconds = float(min_minutes) * 60.0
    for i in range(n):
        is_true = raw_list[i] is True
        if not is_true:
            streak_start = None
            out.append(False)
            continue
        ts = _parse_timestamp(ts_list[i])
        if ts is None:
            streak_start = None
            out.append(False)
            continue
        if streak_start is None:
            streak_start = ts
        elapsed = (ts - streak_start).total_seconds()
        out.append(elapsed >= min_seconds)
    return pa.array(out, type=pa.bool_())


def _confirm_min_true_rows(raw: pa.ChunkedArray, min_rows: int) -> pa.ChunkedArray:
    """True only after ``min_rows`` consecutive raw-true samples (inclusive at streak end)."""
    if min_rows <= 1:
        return as_array(raw).cast(pa.bool_())
    raw_list = as_array(raw).to_pylist()
    out: list[bool] = []
    streak = 0
    for value in raw_list:
        if value is True:
            streak += 1
        else:
            streak = 0
        out.append(streak >= min_rows)
    return pa.array(out, type=pa.bool_())


def confirm_fault_mask(
    mask: pa.Array | pa.ChunkedArray,
    table: pa.Table | None = None,
    *,
    min_true_rows: int | None = None,
    min_elapsed_minutes: float | None = None,
    timestamp_column: str = "timestamp",
    poll_interval_s: float | None = None,
) -> tuple[pa.ChunkedArray, dict[str, Any]]:
    """Apply consecutive-row and/or elapsed-time confirmation to a raw fault mask."""
    meta: dict[str, Any] = {}
    raw = as_array(mask).cast(pa.bool_())
    confirmed = raw

    rows_needed = int(min_true_rows) if min_true_rows is not None and int(min_true_rows) > 1 else None
    elapsed_needed = (
        float(min_elapsed_minutes) if min_elapsed_minutes is not None and float(min_elapsed_minutes) > 0 else None
    )
    if rows_needed is None and elapsed_needed is None:
        return confirmed, meta

    if rows_needed is not None:
        confirmed = _confirm_min_true_rows(raw, rows_needed)
        meta["min_true_rows"] = rows_needed

    if elapsed_needed is not None:
        if table is not None and timestamp_column in table.column_names:
            elapsed_mask = _confirm_elapsed_minutes(
                raw,
                table.column(timestamp_column),
                min_minutes=elapsed_needed,
            )
            confirmed = pc.and_(confirmed, elapsed_mask)
            meta["min_elapsed_minutes"] = elapsed_needed
        elif poll_interval_s and float(poll_interval_s) > 0:
            fallback_rows = max(1, int(round(elapsed_needed * 60.0 / float(poll_interval_s))))
            confirmed = _confirm_min_true_rows(raw, fallback_rows)
            meta["min_elapsed_minutes"] = elapsed_needed
            meta["warning"] = (
                f"no {timestamp_column}; used poll_interval_s={poll_interval_s} "
                f"→ min_true_rows≈{fallback_rows}"
            )
        else:
            meta["warning"] = (
                f"min_elapsed_minutes={elapsed_needed} ignored — "
                f"need {timestamp_column} column or poll_interval_s in config"
            )

    return confirmed, meta


def confirm_consecutive_true(mask: pa.Array | pa.ChunkedArray, min_true_rows: int) -> pa.ChunkedArray:
    """Cookbook helper — alias for consecutive-row confirmation."""
    confirmed, _meta = confirm_fault_mask(mask, min_true_rows=min_true_rows)
    return confirmed


def apply_fault_confirmation_from_cfg(
    mask: pa.Array | pa.ChunkedArray,
    table: pa.Table | None,
    cfg: dict[str, Any] | None,
) -> tuple[pa.ChunkedArray, list[str]]:
    """Read confirmation settings from rule config and apply to a raw fault mask."""
    cfg = dict(cfg or {})
    min_rows = cfg.get("min_true_rows")
    min_elapsed = cfg.get("min_elapsed_minutes")
    if min_rows is None and min_elapsed is None:
        return as_array(mask), []
    poll = cfg.get("poll_interval_s") or cfg.get("median_poll_interval_s")
    poll_f = float(poll) if poll is not None else None
    confirmed, meta = confirm_fault_mask(
        mask,
        table,
        min_true_rows=int(min_rows) if min_rows is not None else None,
        min_elapsed_minutes=float(min_elapsed) if min_elapsed is not None else None,
        timestamp_column=str(cfg.get("timestamp_column") or "timestamp"),
        poll_interval_s=poll_f,
    )
    warnings = [str(meta["warning"])] if meta.get("warning") else []
    return confirmed, warnings
