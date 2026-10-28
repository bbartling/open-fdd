"""Timescale sample reads for IP baseline capture (window-complete, paged)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

# Page size matches product ``point_resolve`` max (``clamp_max_points`` → 5000).
PAGE_SIZE = 5000


def count_samples_in_window(
    conn,
    *,
    site_id: str,
    openfdd_key: str,
    window_start: str,
    window_end: str,
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*)::bigint
            FROM sample
            WHERE site_id = %s
              AND openfdd_key = %s
              AND ts >= %s::timestamptz
              AND ts < %s::timestamptz
            """,
            (site_id, openfdd_key, window_start, window_end),
        )
        return int(cur.fetchone()[0])


def load_samples_in_window(
    conn,
    *,
    site_id: str,
    openfdd_key: str,
    window_start: str,
    window_end: str,
    page_size: int = PAGE_SIZE,
) -> list[tuple[datetime, Any]]:
    """Load every sample in ``[window_start, window_end)``, paging by timestamp."""
    expected = count_samples_in_window(
        conn,
        site_id=site_id,
        openfdd_key=openfdd_key,
        window_start=window_start,
        window_end=window_end,
    )
    rows: list[tuple[datetime, Any]] = []
    cursor_after: str | None = None
    while True:
        with conn.cursor() as cur:
            if cursor_after is None:
                cur.execute(
                    """
                    SELECT ts, val
                    FROM sample
                    WHERE site_id = %s
                      AND openfdd_key = %s
                      AND ts >= %s::timestamptz
                      AND ts < %s::timestamptz
                    ORDER BY ts ASC
                    LIMIT %s
                    """,
                    (site_id, openfdd_key, window_start, window_end, page_size),
                )
            else:
                cur.execute(
                    """
                    SELECT ts, val
                    FROM sample
                    WHERE site_id = %s
                      AND openfdd_key = %s
                      AND ts > %s::timestamptz
                      AND ts < %s::timestamptz
                    ORDER BY ts ASC
                    LIMIT %s
                    """,
                    (site_id, openfdd_key, cursor_after, window_end, page_size),
                )
            batch = cur.fetchall()
        if not batch:
            break
        for ts, val in batch:
            rows.append((ts, val))
        if len(batch) < page_size:
            break
        cursor_after = batch[-1][0].isoformat().replace("+00:00", "Z")
    if len(rows) != expected:
        raise RuntimeError(
            f"sample window incomplete for {openfdd_key}: pulled {len(rows)}, "
            f"sample table count {expected} "
            f"(window {window_start} .. {window_end})"
        )
    return rows
