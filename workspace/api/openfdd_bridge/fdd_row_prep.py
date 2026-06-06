"""Prepare feather/joined-frame rows for cookbook-style evaluate() rules."""

from __future__ import annotations

from typing import Any

import pandas as pd

from open_fdd.playground.cookbook import (
    DEFAULT_ROLLING_AVG_MINUTES,
    DEFAULT_THRESHOLDS_F,
    ROLLING_AVG_MINUTES_ALLOWED,
    attach_rolling_avg,
    cfg_threshold,
    inject_cookbook_helpers,
    normalize_rolling_avg_minutes,
    temp_unit_symbol,
)
from open_fdd.playground.rows import timestamp_to_ts_ms

from .data_loader import column_map_for_rule, enrich_rows_with_column_map
from .model_point_utils import point_site_id
from .timeseries_api import plot_column_name


def resolve_value_column(rule: dict[str, Any], model: dict[str, Any], site_id: str) -> tuple[str, str]:
    """Return (external_id column name, value kind: temp | rh)."""
    cfg = rule.get("config") if isinstance(rule.get("config"), dict) else {}
    forced = str(cfg.get("value_kind") or "").strip().lower()
    if forced in {"temp", "rh"}:
        kind = forced
    else:
        kind = "temp"

    bindings = rule.get("bindings") if isinstance(rule.get("bindings"), dict) else {}
    point_ids = [str(x) for x in bindings.get("point_ids") or [] if str(x).strip()]
    equipment_ids = {str(x) for x in bindings.get("equipment_ids") or [] if str(x).strip()}
    brick_types = {str(x) for x in bindings.get("brick_types") or [] if str(x).strip()}

    def _matches(pt: dict[str, Any]) -> bool:
        if point_site_id(pt, model) != str(site_id):
            return False
        eid = str(pt.get("equipment_id") or "").strip()
        if equipment_ids and eid not in equipment_ids:
            return False
        if point_ids and str(pt.get("id") or "") not in point_ids:
            return False
        if not point_ids and brick_types and str(pt.get("brick_type") or "") not in brick_types:
            return False
        return True

    for pt in model.get("points") or []:
        if not isinstance(pt, dict) or not _matches(pt):
            continue
        col = plot_column_name(pt)
        if not col:
            continue
        brick = str(pt.get("brick_type") or "")
        if not forced:
            kind = "rh" if "Humidity" in brick else "temp"
        return col, kind

    for key in ("oa-t", "duct-t", "stat_zn-t", "SAT", "temp"):
        if key:
            return key, kind
    return "temp", kind


def rolling_avg_values_for_column(
    df: pd.DataFrame,
    column: str,
    *,
    minutes: int = DEFAULT_ROLLING_AVG_MINUTES,
) -> list[float | None]:
    """Trailing mean aligned 1:1 with dataframe rows (for plot overlays)."""
    if df.empty or column not in df.columns:
        return []
    minutes = normalize_rolling_avg_minutes(minutes)
    out: list[float | None] = [None] * len(df)
    prep_rows: list[dict[str, Any]] = []
    index_map: list[int] = []
    for idx, (_, series_row) in enumerate(df.iterrows()):
        ts_ms = timestamp_to_ts_ms(series_row.get("timestamp") or series_row.get("ts"))
        if ts_ms is None:
            continue
        raw_val = series_row.get(column)
        if raw_val is None or (isinstance(raw_val, float) and pd.isna(raw_val)):
            val = None
        else:
            try:
                val = float(raw_val)
            except (TypeError, ValueError):
                val = None
        prep_rows.append({"ts_ms": ts_ms, "temp": val, "degF": val})
        index_map.append(idx)
    if not prep_rows:
        return out
    attach_rolling_avg(prep_rows, minutes=minutes)
    for prep_i, df_i in enumerate(index_map):
        avg = prep_rows[prep_i].get("temp_rolling_avg")
        if avg is None or (isinstance(avg, float) and pd.isna(avg)):
            out[df_i] = None
        else:
            out[df_i] = float(avg)
    return out


def aux_series_key(column: str, minutes: int) -> str:
    return f"{column}__rolling_{normalize_rolling_avg_minutes(minutes)}m"


def build_rolling_aux_series(
    df: pd.DataFrame,
    columns: list[str],
    kinds: dict[str, str],
    *,
    minutes: int = DEFAULT_ROLLING_AVG_MINUTES,
) -> dict[str, list[float | None]]:
    """Per-column trailing means for temperature series (humidity skipped)."""
    minutes = normalize_rolling_avg_minutes(minutes)
    aux: dict[str, list[float | None]] = {}
    for col in columns:
        if col not in df.columns:
            continue
        if kinds.get(col) == "humidity":
            continue
        vals = rolling_avg_values_for_column(df, col, minutes=minutes)
        if vals:
            aux[aux_series_key(col, minutes)] = vals
    return aux


def prepare_fdd_rows(
    df: pd.DataFrame,
    rule: dict[str, Any],
    model: dict[str, Any],
    site_id: str,
    *,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Build cookbook rows: ts_ms, ts, row, temp/rh from bound BACnet column."""
    if df.empty:
        return []
    work = df.tail(limit) if limit and len(df) > limit else df
    value_col, kind = resolve_value_column(rule, model, site_id)
    cfg = rule.get("config") if isinstance(rule.get("config"), dict) else {}
    rolling_min = normalize_rolling_avg_minutes(cfg.get("rolling_avg_minutes"))

    rows: list[dict[str, Any]] = []
    for _, series_row in work.iterrows():
        item = series_row.to_dict()
        if "timestamp" in item and hasattr(item["timestamp"], "isoformat"):
            item["timestamp"] = item["timestamp"].isoformat()
        ts_ms = timestamp_to_ts_ms(item.get("timestamp") or item.get("ts"))
        if ts_ms is None:
            continue
        raw_val = item.get(value_col)
        if raw_val is None or (isinstance(raw_val, float) and pd.isna(raw_val)):
            val = None
        else:
            try:
                val = float(raw_val)
            except (TypeError, ValueError):
                val = None
        item["row"] = len(rows)
        item["ts_ms"] = ts_ms
        ts_raw = item.get("timestamp") or item.get("ts") or ""
        item["ts"] = str(ts_raw).replace("T", " ")[:19]
        if kind == "rh":
            item["rh"] = val
            item["temp"] = val
        else:
            item["temp"] = val
            item["degF"] = val
        item["value_kind"] = kind
        item["value_column"] = value_col
        rows.append(item)

    attach_rolling_avg(rows, minutes=rolling_min)
    column_map = column_map_for_rule(model, site_id, rule)
    return enrich_rows_with_column_map(rows, column_map)


def inject_rule_helpers(globals_dict: dict[str, Any]) -> None:
    inject_cookbook_helpers(globals_dict)
