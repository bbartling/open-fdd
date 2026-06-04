"""Convert historian samples or pandas columns into cookbook ``evaluate()`` rows."""

from __future__ import annotations

from typing import Any

import pandas as pd

from open_fdd.playground.cookbook import (
    DEFAULT_ROLLING_AVG_MINUTES,
    attach_rolling_avg,
    normalize_rolling_avg_minutes,
)


def timestamp_to_ts_ms(raw: Any) -> int | None:
    if raw is None:
        return None
    try:
        ts = pd.to_datetime(raw, utc=True, errors="coerce")
        if pd.isna(ts):
            return None
        return int(ts.value // 1_000_000)
    except (TypeError, ValueError):
        return None


def readings_to_evaluate_rows(readings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """DynamoDB/MQTT samples → rows (parity with AWS ``fdd_lambda`` ``series_readings_to_rows``)."""
    rows: list[dict[str, Any]] = []
    for i, r in enumerate(readings):
        ts_iso = r.get("ts") or r.get("ts_iso") or ""
        if "degF" in r:
            deg_f = float(r["degF"])
        else:
            deg_f = float(r.get("value", 0))
        rows.append(
            {
                "row": i,
                "ts_ms": int(r["ts_ms"]),
                "ts": str(ts_iso).replace("T", " ")[:19],
                "degF": deg_f,
                "degC": float(r.get("degC", (deg_f - 32) * 5 / 9)),
                "temp": deg_f,
                "value": r.get("value", deg_f),
                "unit": r.get("unit", ""),
                "series_id": r.get("series_id"),
                "source": r.get("source"),
                "value_kind": "temp",
            }
        )
    if rows:
        attach_rolling_avg(rows)
    return rows


def dataframe_to_evaluate_rows(
    df: pd.DataFrame,
    value_column: str,
    *,
    timestamp_column: str = "timestamp",
    value_kind: str = "temp",
    rolling_avg_minutes: int | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Feather/BACnet pandas frame → cookbook rows for one bound column."""
    if df.empty or value_column not in df.columns:
        return []
    work = df.tail(limit) if limit and len(df) > limit else df
    rolling_min = normalize_rolling_avg_minutes(
        rolling_avg_minutes if rolling_avg_minutes is not None else DEFAULT_ROLLING_AVG_MINUTES
    )
    rows: list[dict[str, Any]] = []
    for _, series_row in work.iterrows():
        item = series_row.to_dict()
        ts_ms = timestamp_to_ts_ms(item.get(timestamp_column) or item.get("ts"))
        if ts_ms is None:
            continue
        raw_val = item.get(value_column)
        if raw_val is None or (isinstance(raw_val, float) and pd.isna(raw_val)):
            val = None
        else:
            try:
                val = float(raw_val)
            except (TypeError, ValueError):
                val = None
        ts_raw = item.get(timestamp_column) or item.get("ts") or ""
        row = {
            "row": len(rows),
            "ts_ms": ts_ms,
            "ts": str(ts_raw).replace("T", " ")[:19],
            "temp": val,
            "degF": val,
            "value_kind": value_kind,
            "value_column": value_column,
        }
        if value_kind == "rh":
            row["rh"] = val
        rows.append(row)
    attach_rolling_avg(rows, minutes=rolling_min)
    return rows
