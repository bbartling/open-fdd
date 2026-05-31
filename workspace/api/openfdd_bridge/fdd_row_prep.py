"""Prepare feather/joined-frame rows for cookbook-style evaluate() rules."""

from __future__ import annotations

import statistics
from typing import Any

import pandas as pd

from .data_loader import column_map_for_rule, enrich_rows_with_column_map

DEFAULT_THRESHOLDS_F: dict[str, float] = {
    "flatline_tolerance": 0.10,
    "max_temp_per_hour": 5.0,
    "max_temp_per_15min": 2.0,
    "max_spread": 4.0,
    "max_spread_15min": 2.5,
    "max_spread_24h": 12.0,
    "bounds_low": 65.0,
    "bounds_high": 80.0,
    "flatline_window": 18.0,
    "rolling_window": 6.0,
    "flatline_tolerance_rh": 1.0,
    "bounds_low_rh": 20.0,
    "bounds_high_rh": 70.0,
}


def temp_unit_symbol(cfg: dict[str, Any] | None) -> str:
    unit = str((cfg or {}).get("temp_unit") or "imperial").lower()
    return "°C" if unit in {"metric", "c", "celsius"} else "°F"


def cfg_threshold(cfg: dict[str, Any] | None, key: str) -> float:
    cfg = cfg or {}
    if key in cfg and cfg[key] is not None and str(cfg[key]).strip() != "":
        return float(cfg[key])
    return float(DEFAULT_THRESHOLDS_F.get(key, 0.0))


def _ts_ms_from_value(raw: Any) -> int | None:
    if raw is None:
        return None
    try:
        ts = pd.to_datetime(raw, utc=True, errors="coerce")
        if pd.isna(ts):
            return None
        return int(ts.value // 1_000_000)
    except (TypeError, ValueError):
        return None


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
    for pt in model.get("points") or []:
        if not isinstance(pt, dict):
            continue
        if str(pt.get("site_id") or "") != str(site_id):
            continue
        if point_ids and str(pt.get("id") or "") not in point_ids:
            continue
        if not point_ids:
            brick_types = {str(x) for x in bindings.get("brick_types") or [] if str(x).strip()}
            if brick_types and str(pt.get("brick_type") or "") not in brick_types:
                continue
        col = str(pt.get("external_id") or "").strip()
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


def _median_sample_ms(rows: list[dict[str, Any]]) -> int:
    if len(rows) < 2:
        return 60_000
    dts = [
        int(rows[i]["ts_ms"]) - int(rows[i - 1]["ts_ms"])
        for i in range(1, len(rows))
        if int(rows[i]["ts_ms"]) > int(rows[i - 1]["ts_ms"])
    ]
    return int(statistics.median(dts)) if dts else 60_000


def attach_rolling_avg(rows: list[dict[str, Any]], *, minutes: int = 1) -> None:
    if not rows:
        return
    window_ms = max(1, int(minutes)) * 60_000
    period_ms = _median_sample_ms(rows)
    j_start = 0
    for i, row in enumerate(rows):
        ts = int(row["ts_ms"])
        cutoff = ts - window_ms
        while j_start < i and int(rows[j_start]["ts_ms"]) < cutoff:
            j_start += 1
        window = rows[j_start : i + 1]
        vals = [float(r["temp"]) for r in window if r.get("temp") is not None]
        avg = sum(vals) / len(vals) if vals else row.get("temp")
        row["temp_rolling_avg"] = avg
        row["degF_rolling_avg"] = avg
        row["temp_raw"] = row.get("temp")
        row["sample_period_ms"] = period_ms
        row["rolling_avg_minutes"] = minutes
        row["samples_in_avg"] = len(window)


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
    rolling_min = int(cfg.get("rolling_avg_minutes") or 1)

    rows: list[dict[str, Any]] = []
    for _, series_row in work.iterrows():
        item = series_row.to_dict()
        if "timestamp" in item and hasattr(item["timestamp"], "isoformat"):
            item["timestamp"] = item["timestamp"].isoformat()
        ts_ms = _ts_ms_from_value(item.get("timestamp") or item.get("ts"))
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
    globals_dict["temp_unit_symbol"] = temp_unit_symbol
    globals_dict["cfg_threshold"] = cfg_threshold
