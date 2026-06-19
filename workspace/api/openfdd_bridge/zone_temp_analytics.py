"""Prebuilt zone temperature levers from BRICK model + feather store (pandas).

Uses SPARQL/model ``brick:feeds`` when present (AHU → VAV zone sensors). Without
AHU/fan relationships, averages all ``Zone_Air_Temperature*`` sensors site-wide.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

import pandas as pd

from .data_loader import load_frame_for_run
from .model_feeds import _is_ahu, _is_vav
from .model_service import ModelService
from .operational_analytics import (
    analytics_lookback_days,
    analytics_methodology,
    trim_frame_to_lookback,
)
from .site_defaults import ensure_default_site
from .timeseries_api import historian_column_candidates, plot_column_name, resolve_historian_column
from .ttl_service import TtlService

_CACHE: dict[str, Any] = {"generated_at": 0.0, "next_refresh_at": 0.0, "payload": {}}

ZONE_BRICK_MARKERS = ("zone_air_temperature", "zone temperature")
FAN_BRICK_MARKERS = ("supply_fan", "fan_speed", "fan_command", "fan_status", "fan_start")
DEFAULT_INTERVAL_S = 3600
_GENERIC_ZONE_POINT_NAMES = frozenset(
    {
        "space temperature local",
        "zone temperature",
        "zone air temperature",
        "space temperature",
        "zone temp",
    }
)


def refresh_interval_s() -> int:
    try:
        return max(300, int(os.environ.get("OFDD_ZONE_TEMP_INTERVAL_S", str(DEFAULT_INTERVAL_S))))
    except ValueError:
        return DEFAULT_INTERVAL_S


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _site_timezone(model: dict[str, Any], site_id: str) -> str:
    env_tz = os.environ.get("OFDD_SITE_TIMEZONE", "").strip()
    if env_tz:
        return env_tz
    for site in model.get("sites") or []:
        if not isinstance(site, dict):
            continue
        if str(site.get("id") or "") != site_id:
            continue
        tz = site.get("timezone") or site.get("time_zone")
        if tz:
            return str(tz).strip()
    return "America/Chicago"


def _occupied_mask(ts: pd.Series, tz_name: str) -> pd.Series:
    start = _env_int("OFDD_OCCUPIED_START_HOUR", 8)
    end = _env_int("OFDD_OCCUPIED_END_HOUR", 17)
    local = pd.to_datetime(ts, utc=True, errors="coerce").dt.tz_convert(tz_name)
    return (local.dt.weekday < 5) & (local.dt.hour >= start) & (local.dt.hour < end)


def _is_zone_point(pt: dict[str, Any]) -> bool:
    bt = str(pt.get("brick_type") or "").lower()
    if "zone_air_temperature" in bt:
        return True
    name = str(pt.get("name") or pt.get("description") or "").lower()
    return "zone" in name and "temp" in name


def _is_fan_point(pt: dict[str, Any]) -> bool:
    bt = str(pt.get("brick_type") or "").lower()
    if any(m in bt for m in FAN_BRICK_MARKERS):
        return True
    ext = str(pt.get("external_id") or "").lower()
    return "fan" in ext and ("speed" in ext or "cmd" in ext or "command" in ext or "start" in ext)


def _equipment_index(model: dict[str, Any], site_id: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for eq in model.get("equipment") or []:
        if not isinstance(eq, dict):
            continue
        if str(eq.get("site_id") or "") != site_id:
            continue
        eid = str(eq.get("id") or "").strip()
        if eid:
            out[eid] = eq
    return out


def _feeds_map(model: dict[str, Any], site_id: str) -> dict[str, list[str]]:
    """AHU/plant equipment_id -> list of fed child equipment_ids (usually VAVs)."""
    children: dict[str, list[str]] = {}
    for eq in model.get("equipment") or []:
        if not isinstance(eq, dict) or str(eq.get("site_id") or "") != site_id:
            continue
        parent_id = str(eq.get("id") or "").strip()
        feeds = eq.get("feeds")
        if not parent_id or not isinstance(feeds, list):
            continue
        kids = [str(x).strip() for x in feeds if str(x).strip()]
        if kids:
            children[parent_id] = kids
    try:
        from .model_sparql import query_feeds

        for edge in query_feeds(site_id, model=model, ensure=False):
            src = edge.get("from_equipment_id")
            dst = edge.get("to_equipment_id")
            if src and dst:
                children.setdefault(src, [])
                if dst not in children[src]:
                    children[src].append(dst)
    except Exception:
        pass
    return children


def zone_display_label(pt: dict[str, Any], eq: dict[str, Any]) -> str:
    """Operator-facing label — prefer VAV/equipment name over generic BACnet object text."""
    eq_name = str(eq.get("name") or pt.get("equipment_id") or "Zone").strip()
    pt_name = str(pt.get("name") or pt.get("description") or "").strip()
    tag = str(pt.get("brick_tag") or "").strip()
    if not pt_name or pt_name.lower() in _GENERIC_ZONE_POINT_NAMES:
        return f"{eq_name} ({tag})" if tag else eq_name
    return f"{eq_name} — {pt_name}"


def _zone_points_for_equipment(
    model: dict[str, Any],
    site_id: str,
    equipment_ids: set[str] | None = None,
    *,
    available_columns: set[str] | None = None,
) -> list[dict[str, Any]]:
    eq_index = _equipment_index(model, site_id)
    avail = available_columns or set()
    rows: list[dict[str, Any]] = []
    for pt in model.get("points") or []:
        if not isinstance(pt, dict) or str(pt.get("site_id") or "") not in {"", site_id}:
            continue
        if not _is_zone_point(pt):
            continue
        eid = str(pt.get("equipment_id") or "").strip()
        if equipment_ids is not None and eid not in equipment_ids:
            continue
        col = resolve_historian_column(pt, avail) if avail else plot_column_name(pt)
        if not col:
            continue
        eq = eq_index.get(eid) or {}
        rows.append(
            {
                "point_id": str(pt.get("id") or ""),
                "equipment_id": eid,
                "equipment_name": str(eq.get("name") or eid),
                "column": col,
                "label": zone_display_label(pt, eq),
            }
        )
    return rows


def _fan_column_on_equipment(
    model: dict[str, Any],
    site_id: str,
    equipment_id: str,
    available_columns: set[str],
) -> str | None:
    for pt in model.get("points") or []:
        if not isinstance(pt, dict):
            continue
        if str(pt.get("site_id") or "") not in {"", site_id}:
            continue
        if str(pt.get("equipment_id") or "").strip() != equipment_id:
            continue
        if not _is_fan_point(pt):
            continue
        col = plot_column_name(pt)
        if col and col in available_columns:
            return col
    for pt in model.get("points") or []:
        if not isinstance(pt, dict):
            continue
        if str(pt.get("site_id") or "") not in {"", site_id}:
            continue
        if not _is_fan_point(pt):
            continue
        col = plot_column_name(pt)
        if col and col in available_columns:
            return col
    return None


def discover_topology(
    model: dict[str, Any],
    site_id: str,
    *,
    available_columns: set[str] | None = None,
) -> dict[str, Any]:
    """Resolve zone sensors and optional AHU→zone groupings from BRICK JSON + feeds."""
    eq_index = _equipment_index(model, site_id)
    all_zones = _zone_points_for_equipment(model, site_id, None, available_columns=available_columns)
    feeds = _feeds_map(model, site_id)
    ahu_systems: list[dict[str, Any]] = []
    assigned_zone_cols: set[str] = set()

    for ahu_id, eq in eq_index.items():
        if not _is_ahu(eq):
            continue
        child_ids = set(feeds.get(ahu_id) or [])
        vav_ids = {cid for cid in child_ids if cid in eq_index and _is_vav(eq_index[cid])}
        zone_scope = vav_ids or child_ids or {ahu_id}
        zones = _zone_points_for_equipment(model, site_id, zone_scope, available_columns=available_columns)
        if not zones:
            zones = _zone_points_for_equipment(model, site_id, {ahu_id}, available_columns=available_columns)
        if not zones:
            continue
        for z in zones:
            assigned_zone_cols.add(z["column"])
        ahu_systems.append(
            {
                "ahu_id": ahu_id,
                "ahu_name": str(eq.get("name") or ahu_id),
                "zones": zones,
            }
        )

    orphan_zones = [z for z in all_zones if z["column"] not in assigned_zone_cols]
    mode = "ahu_systems" if ahu_systems else "sensors_only"
    if ahu_systems and orphan_zones:
        mode = "mixed"
    return {
        "mode": mode,
        "site_id": site_id,
        "zone_points": all_zones,
        "ahu_systems": ahu_systems,
        "orphan_zones": orphan_zones,
    }


def _column_series(frame: pd.DataFrame, col: str) -> pd.Series:
    """One numeric series for ``col`` even when the frame has duplicate column labels."""
    if col not in frame.columns:
        return pd.Series(dtype=float)
    data = frame[col]
    if isinstance(data, pd.DataFrame):
        data = data.iloc[:, 0]
    return pd.to_numeric(data, errors="coerce")


def _column_health_map(device_snapshot: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if not isinstance(device_snapshot, dict):
        return out
    for eq in device_snapshot.get("equipment") or []:
        if not isinstance(eq, dict):
            continue
        eq_status = str(eq.get("status") or "")
        for pt in eq.get("points") or []:
            if not isinstance(pt, dict):
                continue
            col = str(pt.get("column") or "").strip()
            if not col:
                continue
            out[col] = {**pt, "equipment_status": eq_status}
    return out


def _zone_temp_plausible(s: pd.Series, *, min_f: float = 50.0, max_f: float = 105.0) -> pd.Series:
    numeric = pd.to_numeric(s, errors="coerce")
    return numeric.notna() & (numeric != 0) & (numeric >= min_f) & (numeric <= max_f)


def _zone_samples_for_averages(
    s: pd.Series,
    occupied: pd.Series,
    *,
    column_health: dict[str, Any] | None,
) -> tuple[pd.Series, pd.Series]:
    """Return day/night sample series with offline and implausible values excluded."""
    if column_health:
        eq_status = str(column_health.get("equipment_status") or "")
        valid_ratio = float(column_health.get("valid_ratio") or 1.0)
        if eq_status == "offline" or (column_health.get("stale") and valid_ratio < 0.2):
            empty = pd.Series(dtype=float)
            return empty, empty
    plausible = _zone_temp_plausible(s)
    masked = s.where(plausible)
    day = masked[occupied].dropna()
    night = masked[~occupied].dropna()
    return day, night


def _fan_on_series(series: pd.Series, *, threshold: float = 5.0) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce")
    if s.dropna().empty:
        return pd.Series(False, index=series.index)
    uniq = set(s.dropna().unique())
    if uniq <= {0.0, 1.0} or uniq <= {0, 1}:
        return (s.fillna(0) > 0.5).astype(bool)
    return (s.fillna(0) > threshold).astype(bool)


def _recovery_rates(
    df: pd.DataFrame,
    zone_columns: list[str],
    fan_col: str,
    *,
    window_minutes: int = 30,
    min_gap_hours: float = 2.0,
) -> dict[str, float]:
    if fan_col not in df.columns or "timestamp" not in df.columns:
        return {}
    pick = list(dict.fromkeys(["timestamp", fan_col, *[c for c in zone_columns if c in df.columns]]))
    work = df.loc[:, pick].copy()
    work["timestamp"] = pd.to_datetime(work["timestamp"], utc=True, errors="coerce")
    work = work.dropna(subset=["timestamp"]).sort_values("timestamp")
    if len(work) < 10:
        return {}
    fan_on = _fan_on_series(_column_series(work, fan_col))
    prev = fan_on.shift(1, fill_value=False)
    starts = work.index[fan_on & ~prev]
    if starts.empty:
        return {}
    rates: dict[str, list[float]] = {c: [] for c in zone_columns}
    gap = pd.Timedelta(hours=min_gap_hours)
    last_start: pd.Timestamp | None = None
    for idx in starts:
        t0 = work.loc[idx, "timestamp"]
        if last_start is not None and (t0 - last_start) < gap:
            continue
        last_start = t0
        t1 = t0 + pd.Timedelta(minutes=window_minutes)
        seg = work[(work["timestamp"] >= t0) & (work["timestamp"] <= t1)]
        if len(seg) < 3:
            continue
        minutes = (seg["timestamp"].iloc[-1] - seg["timestamp"].iloc[0]).total_seconds() / 60.0
        if minutes < 5:
            continue
        for col in zone_columns:
            if col not in seg.columns:
                continue
            vals = _column_series(seg, col).dropna()
            if len(vals) < 2:
                continue
            delta = float(vals.iloc[-1] - vals.iloc[0])
            rates[col].append(delta / minutes)
    return {c: sum(v) / len(v) for c, v in rates.items() if v}


def _fan_on_minutes_by_period(
    df: pd.DataFrame,
    fan_col: str,
    *,
    site_tz: str,
) -> dict[str, Any]:
    """Typical HVAC on/off pattern: weekday vs weekend and overnight cycling minutes."""
    if fan_col not in df.columns or "timestamp" not in df.columns:
        return {}
    work = df.loc[:, ["timestamp", fan_col]].copy()
    work["timestamp"] = pd.to_datetime(work["timestamp"], utc=True, errors="coerce")
    work = work.dropna(subset=["timestamp"]).sort_values("timestamp")
    if len(work) < 12:
        return {}
    fan_on = _fan_on_series(_column_series(work, fan_col))
    work["fan_on"] = fan_on
    local = work["timestamp"].dt.tz_convert(site_tz)
    work["weekday"] = local.dt.weekday
    work["hour"] = local.dt.hour
    work["date"] = local.dt.date
    if len(work) < 2:
        return {}
    deltas = work["timestamp"].diff().dt.total_seconds().fillna(0) / 60.0
    work["minutes"] = deltas.clip(lower=0)

    occ_start = _env_int("OFDD_OCCUPIED_START_HOUR", 8)
    occ_end = _env_int("OFDD_OCCUPIED_END_HOUR", 17)
    overnight = (work["hour"] < occ_start) | (work["hour"] >= occ_end)

    def _summarize(mask: pd.Series) -> dict[str, Any]:
        seg = work.loc[mask]
        if seg.empty:
            return {}
        on_min = float(seg.loc[seg["fan_on"], "minutes"].sum())
        total_min = float(seg["minutes"].sum()) or 1.0
        starts = int((seg["fan_on"] & ~seg["fan_on"].shift(1, fill_value=False)).sum())
        first_on = seg.loc[seg["fan_on"], "hour"]
        last_on = seg.loc[seg["fan_on"], "hour"]
        return {
            "fan_on_minutes": round(on_min, 1),
            "fan_on_pct": round(100.0 * on_min / total_min, 1),
            "fan_start_events": starts,
            "typical_first_fan_on_hour": int(first_on.median()) if not first_on.empty else None,
            "typical_last_fan_on_hour": int(last_on.median()) if not last_on.empty else None,
        }

    weekday = work["weekday"] < 5
    weekend = ~weekday
    overnight_cycling: list[dict[str, Any]] = []
    for date_val, day_df in work.groupby("date"):
        wd = int(day_df["weekday"].iloc[0])
        night = day_df.loc[overnight.reindex(day_df.index, fill_value=False)]
        if night.empty:
            continue
        on_min = float(night.loc[night["fan_on"], "minutes"].sum())
        if on_min < 1.0:
            continue
        starts = int((night["fan_on"] & ~night["fan_on"].shift(1, fill_value=False)).sum())
        overnight_cycling.append(
            {
                "date": str(date_val),
                "weekday": wd,
                "overnight_fan_on_minutes": round(on_min, 1),
                "overnight_fan_cycles": starts,
            }
        )
    overnight_cycling.sort(key=lambda x: x["overnight_fan_on_minutes"], reverse=True)
    weekday_nights = [x for x in overnight_cycling if x["weekday"] < 5]
    weekend_nights = [x for x in overnight_cycling if x["weekday"] >= 5]
    avg_weeknight = (
        sum(x["overnight_fan_on_minutes"] for x in weekday_nights) / len(weekday_nights)
        if weekday_nights
        else None
    )
    avg_weekend_night = (
        sum(x["overnight_fan_on_minutes"] for x in weekend_nights) / len(weekend_nights)
        if weekend_nights
        else None
    )
    return {
        "fan_column": fan_col,
        "occupied_hours_local": f"weekdays {occ_start:02d}:00–{occ_end:02d}:00",
        "weekday": _summarize(weekday),
        "weekend": _summarize(weekend),
        "overnight_avg_fan_on_minutes_weeknight": round(avg_weeknight, 1) if avg_weeknight is not None else None,
        "overnight_avg_fan_on_minutes_weekend": round(avg_weekend_night, 1) if avg_weekend_night is not None else None,
        "worst_overnight_cycling_nights": overnight_cycling[:5],
    }


def _collapse_zones_by_column(zones: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One metrics row per historian column; preserve equipment names for operator labels."""
    by_col: dict[str, dict[str, Any]] = {}
    for z in zones:
        col = str(z.get("column") or "")
        if not col:
            continue
        name = str(z.get("equipment_name") or z.get("label") or "").strip()
        if col not in by_col:
            by_col[col] = {**z, "_equipment_names": [name] if name else []}
            continue
        entry = by_col[col]
        if name and name not in entry["_equipment_names"]:
            entry["_equipment_names"].append(name)
    out: list[dict[str, Any]] = []
    for col, z in by_col.items():
        names: list[str] = z.pop("_equipment_names", [])
        shared = len(names)
        label = str(z.get("label") or col)
        if shared > 1:
            examples = ", ".join(names[:3])
            extra = f" (+{shared - 3} more)" if shared > 3 else ""
            z["label"] = f"{examples}{extra} — shared column {col}"
            z["shared_column_zone_count"] = shared
            z["example_equipment"] = names[:6]
        elif names:
            z["label"] = names[0]
            z["equipment_name"] = names[0]
        out.append(z)
    return out


def build_zone_dataframe(
    df: pd.DataFrame,
    topology: dict[str, Any],
) -> pd.DataFrame:
    """Narrow pandas frame: timestamp, optional fan columns, zone temp columns."""
    cols = ["timestamp"]
    if "timestamp" not in df.columns:
        return pd.DataFrame()
    available = set(df.columns)
    fan_cols: list[str] = []
    zone_cols = sorted({z["column"] for z in topology.get("zone_points") or [] if z["column"] in available})
    for sys in topology.get("ahu_systems") or []:
        ahu_id = sys.get("ahu_id")
        if ahu_id:
            pass  # fan resolved during metrics
    for c in zone_cols:
        if c not in cols:
            cols.append(c)
    out = df[cols].copy()
    out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True, errors="coerce")
    return out.dropna(subset=["timestamp"])


def compute_zone_metrics(
    df: pd.DataFrame,
    topology: dict[str, Any],
    model: dict[str, Any],
    site_id: str,
    *,
    site_tz: str | None = None,
    device_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute day/night averages and optional recovery rates per zone / AHU."""
    zone_df = build_zone_dataframe(df, topology)
    available = set(df.columns)
    if zone_df.empty or not topology.get("zone_points"):
        return {
            "mode": topology.get("mode"),
            "site_id": site_id,
            "zones": [],
            "systems": [],
            "dataframe_rows": 0,
            "summary_sentence": "No zone temperature columns in the timeseries store yet.",
        }

    tz_name = site_tz or _site_timezone(model, site_id)
    ts = zone_df["timestamp"]
    occupied = _occupied_mask(ts, tz_name)
    col_health = _column_health_map(device_snapshot)
    zones_out: list[dict[str, Any]] = []
    for zp in topology.get("zone_points") or []:
        col = zp["column"]
        if col not in zone_df.columns:
            continue
        s = _column_series(zone_df, col)
        day, night = _zone_samples_for_averages(s, occupied, column_health=col_health.get(col))
        excluded = bool(col_health.get(col, {}).get("stale")) or str(
            col_health.get(col, {}).get("equipment_status") or ""
        ) == "offline"
        zones_out.append(
            {
                **zp,
                "day_avg_f": round(float(day.mean()), 2) if not day.empty else None,
                "night_avg_f": round(float(night.mean()), 2) if not night.empty else None,
                "setback_delta_f": round(float(day.mean() - night.mean()), 2)
                if not day.empty and not night.empty
                else None,
                "samples": int(s.notna().sum()),
                "samples_used": int(day.notna().sum() + night.notna().sum()),
                "excluded_offline": excluded,
            }
        )

    zones_out = _collapse_zones_by_column(zones_out)
    unique_columns = {z.get("column") for z in zones_out if z.get("column")}
    mapped_sensors = len(topology.get("zone_points") or [])
    column_collision = mapped_sensors > len(unique_columns)

    systems_out: list[dict[str, Any]] = []
    struggling: list[dict[str, Any]] = []
    for sys in topology.get("ahu_systems") or []:
        zone_cols = [z["column"] for z in sys.get("zones") or [] if z["column"] in available]
        if not zone_cols:
            continue
        fan_col = _fan_column_on_equipment(model, site_id, str(sys.get("ahu_id") or ""), available)
        recoveries = {}
        if fan_col and fan_col in available:
            rate_cols = list(dict.fromkeys(["timestamp", fan_col, *zone_cols]))
            rate_df = df.loc[:, [c for c in rate_cols if c in df.columns]].copy()
            recoveries = _recovery_rates(rate_df, zone_cols, fan_col)
        sys_zones = []
        rates = [r for r in recoveries.values() if r is not None]
        median_rate = sorted(rates)[len(rates) // 2] if rates else None
        for z in sys.get("zones") or []:
            col = z["column"]
            zrow = next((x for x in zones_out if x["column"] == col), None)
            rec = recoveries.get(col)
            entry = {
                "column": col,
                "label": z.get("label") or col,
                "equipment_id": z.get("equipment_id"),
                "equipment_name": z.get("equipment_name"),
                "day_avg_f": zrow.get("day_avg_f") if zrow else None,
                "night_avg_f": zrow.get("night_avg_f") if zrow else None,
                "recovery_f_per_min": round(rec, 4) if rec is not None else None,
            }
            sys_zones.append(entry)
            if zrow is not None and rec is not None:
                zrow["recovery_f_per_min"] = round(rec, 4)
            if rec is not None and median_rate is not None and median_rate > 0.02:
                if rec < 0.5 * median_rate:
                    struggling.append(
                        {
                            "ahu_id": sys.get("ahu_id"),
                            "ahu_name": sys.get("ahu_name"),
                            "column": col,
                            "label": entry["label"],
                            "recovery_f_per_min": entry["recovery_f_per_min"],
                            "median_recovery_f_per_min": round(median_rate, 4),
                            "reason": "slow_recovery_after_fan_start",
                        }
                    )
        systems_out.append(
            {
                "ahu_id": sys.get("ahu_id"),
                "ahu_name": sys.get("ahu_name"),
                "fan_column": fan_col,
                "zones": sys_zones,
                "median_recovery_f_per_min": round(median_rate, 4) if median_rate is not None else None,
            }
        )

    fan_schedule: dict[str, Any] = {}
    for sys in systems_out:
        fan_col = sys.get("fan_column")
        if fan_col and fan_col in available:
            fan_schedule = _fan_on_minutes_by_period(df, str(fan_col), site_tz=tz_name)
            if fan_schedule:
                break

    worst_zones = _worst_zones(zones_out, systems_out, struggling, column_collision=column_collision)
    sentence = _summary_sentence(
        zones_out,
        systems_out,
        struggling,
        topology.get("mode"),
        mapped_sensors=mapped_sensors,
        column_collision=column_collision,
    )
    preview = zone_df.tail(120).copy()
    for c in preview.columns:
        if c != "timestamp":
            preview[c] = pd.to_numeric(preview[c], errors="coerce").round(2)
    return {
        "mode": topology.get("mode"),
        "site_id": site_id,
        "lookback_days": analytics_lookback_days(),
        "methodology": analytics_methodology(),
        "zones": zones_out,
        "systems": systems_out,
        "struggling_zones": struggling,
        "worst_zones": worst_zones,
        "site_aggregates": _site_aggregates(zones_out, mapped_sensors, len(unique_columns)),
        "column_collision": column_collision,
        "fan_schedule": fan_schedule,
        "dataframe_rows": len(zone_df),
        "dataframe_preview": preview.to_dict(orient="records"),
        "summary_sentence": sentence,
    }


def _site_aggregates(
    zones_out: list[dict[str, Any]],
    mapped_sensors: int,
    unique_columns: int,
) -> dict[str, Any]:
    with_day = [z for z in zones_out if z.get("day_avg_f") is not None]
    with_night = [z for z in zones_out if z.get("night_avg_f") is not None]
    return {
        "mapped_zone_sensors": mapped_sensors,
        "unique_historian_columns": unique_columns,
        "day_avg_f": round(sum(z["day_avg_f"] for z in with_day) / len(with_day), 2) if with_day else None,
        "night_avg_f": round(sum(z["night_avg_f"] for z in with_night) / len(with_night), 2) if with_night else None,
    }


def _worst_zones(
    zones_out: list[dict[str, Any]],
    systems_out: list[dict[str, Any]],
    struggling: list[dict[str, Any]],
    *,
    column_collision: bool = False,
) -> list[dict[str, Any]]:
    """Rank distinct historian columns for operator focus (slow recovery, weak setback)."""
    recovery_by_col: dict[str, float] = {}
    for sys in systems_out:
        for z in sys.get("zones") or []:
            col = z.get("column")
            rec = z.get("recovery_f_per_min")
            if col and rec is not None:
                recovery_by_col[col] = float(rec)
    scored: list[tuple[float, dict[str, Any]]] = []
    seen_cols: set[str] = set()
    seen_names: set[str] = set()
    for z in zones_out:
        col = str(z.get("column") or "")
        if not col or col in seen_cols:
            continue
        eq_name = str(z.get("equipment_name") or z.get("label") or "").strip()
        if eq_name and eq_name in seen_names and not z.get("shared_column_zone_count"):
            continue
        seen_cols.add(col)
        if eq_name:
            seen_names.add(eq_name)
        score = 0.0
        day = z.get("day_avg_f")
        night = z.get("night_avg_f")
        setback = z.get("setback_delta_f")
        if setback is not None:
            score += max(0.0, 1.5 - abs(float(setback)))
        if day is not None and night is not None:
            score += abs(float(day) - float(night)) * 0.5
        rec = z.get("recovery_f_per_min")
        if rec is None:
            rec = recovery_by_col.get(col)
        if rec is not None and rec < 0.03:
            score += 5.0
        for s in struggling:
            if s.get("column") == col:
                score += 10.0
        if score <= 0 and not column_collision:
            continue
        row = {**z, "recovery_f_per_min": rec, "worst_reason": _worst_reason(z, rec, setback)}
        scored.append((score, row))
    scored.sort(key=lambda x: x[0], reverse=True)
    out = [item for _, item in scored[:6]]
    if column_collision and len(out) <= 1 and zones_out:
        z0 = zones_out[0]
        shared = int(z0.get("shared_column_zone_count") or 0)
        if shared > 1:
            out = [
                {
                    **z0,
                    "label": (
                        f"{shared} zone sensors share historian column {z0.get('column')} "
                        f"(site avg night {z0.get('night_avg_f')}°F / day {z0.get('day_avg_f')}°F)"
                    ),
                    "worst_reason": "shared_historian_column",
                }
            ]
    return out


def _worst_reason(z: dict[str, Any], rec: float | None, setback: float | None) -> str:
    reasons: list[str] = []
    if setback is not None and abs(float(setback)) < 1.5:
        reasons.append("minimal_setback")
    if rec is not None and float(rec) < 0.03:
        reasons.append("slow_recovery")
    if z.get("shared_column_zone_count"):
        reasons.append("shared_column")
    return ",".join(reasons) or "focus_zone"


def _summary_sentence(
    zones: list[dict[str, Any]],
    systems: list[dict[str, Any]],
    struggling: list[dict[str, Any]],
    mode: str | None,
    *,
    mapped_sensors: int = 0,
    column_collision: bool = False,
) -> str:
    if not zones:
        return "No BRICK zone temperature sensors in the model."
    with_day = [z for z in zones if z.get("day_avg_f") is not None]
    with_night = [z for z in zones if z.get("night_avg_f") is not None]
    parts: list[str] = []
    sensor_n = mapped_sensors or len(zones)
    if with_night:
        night_avg = sum(z["night_avg_f"] for z in with_night) / len(with_night)
        parts.append(f"overnight zone temps average {night_avg:.1f}°F")
    if with_day:
        day_avg = sum(z["day_avg_f"] for z in with_day) / len(with_day)
        parts.append(f"occupied daytime average {day_avg:.1f}°F across {sensor_n} sensor(s)")
    if column_collision:
        parts.append(
            f"historian uses {len(zones)} unique column(s) for {sensor_n} sensors — "
            "per-VAV detail needs unique point columns (re-ingest after model column fix)"
        )
    if systems and any(s.get("median_recovery_f_per_min") is not None for s in systems):
        medians = [s["median_recovery_f_per_min"] for s in systems if s.get("median_recovery_f_per_min") is not None]
        parts.append(f"typical warm-up rate ~{sum(medians)/len(medians):.2f}°F/min after fan start")
    if struggling:
        labels = ", ".join(str(s.get("label") or s.get("equipment_name") or "zone") for s in struggling[:3])
        extra = f" (+{len(struggling)-3} more)" if len(struggling) > 3 else ""
        parts.append(f"slow recovery vs {struggling[0].get('ahu_name')}: {labels}{extra}")
    elif mode == "sensors_only":
        parts.append("no AHU/feeds grouping — site-wide sensor average only")
    if not parts:
        return f"{sensor_n} zone temperature sensor(s) mapped; insufficient trend samples for day/night split."
    return "Zone temps: " + "; ".join(parts) + "."


def get_zone_temp_snapshot(*, site_id: str | None = None, force: bool = False) -> dict[str, Any]:
    now = time.time()
    interval = refresh_interval_s()
    cache_key = site_id or "__default__"
    cached = _CACHE.get("payload") or {}
    cached_entry = cached.get(cache_key) if isinstance(cached, dict) else None
    if (
        not force
        and isinstance(cached_entry, dict)
        and now < float(cached_entry.get("next_refresh_at") or 0)
    ):
        return {**cached_entry, "ok": True, "cached": True, "refresh_interval_s": interval}

    model_svc = ModelService()
    sid = (site_id or "").strip() or ensure_default_site(model_svc, TtlService())
    model = model_svc.load()
    df, origin = load_frame_for_run(sid)
    df = trim_frame_to_lookback(df)
    available = set(df.columns) if not df.empty else set()
    topology = discover_topology(model, sid, available_columns=available)

    site_tz = _site_timezone(model, sid)
    from .device_poll_health import get_device_poll_snapshot
    from .zone_energy_research import build_zone_energy_research

    device_snapshot = get_device_poll_snapshot(site_id=sid, force=force)
    metrics = compute_zone_metrics(df, topology, model, sid, site_tz=site_tz, device_snapshot=device_snapshot)
    zone_df = build_zone_dataframe(df, topology)
    occupied_mask = None
    if not zone_df.empty and "timestamp" in zone_df.columns:
        occupied_mask = _occupied_mask(zone_df["timestamp"], site_tz)
    research = build_zone_energy_research(
        metrics,
        device_snapshot,
        zone_df=zone_df if not zone_df.empty else None,
        occupied_mask=occupied_mask,
    )
    payload = {
        "ok": True,
        "cached": False,
        "generated_at": now,
        "next_refresh_at": now + interval,
        "refresh_interval_s": interval,
        "data_source": origin,
        "site_timezone": site_tz,
        "topology_mode": metrics.get("mode"),
        "zone_sensor_count": len(topology.get("zone_points") or []),
        "research": research,
        **metrics,
    }
    stored = dict(cached) if isinstance(cached, dict) else {}
    stored[cache_key] = payload
    _CACHE["payload"] = stored
    _CACHE["generated_at"] = now
    return payload


def slim_zone_for_llm(
    snapshot: dict[str, Any],
    *,
    max_zones: int = 16,
    max_systems: int = 6,
    max_zones_per_system: int = 12,
    max_struggling: int = 8,
) -> dict[str, Any]:
    """Compact zone snapshot for LLM context (dict — never slice JSON mid-string)."""
    summary = str(snapshot.get("summary_sentence") or "")[:400]
    return {
        "topology_mode": snapshot.get("topology_mode") or snapshot.get("mode"),
        "zone_sensor_count": snapshot.get("zone_sensor_count"),
        "summary_sentence": summary,
        "zones": [
            {
                "label": z.get("label"),
                "day_avg_f": z.get("day_avg_f"),
                "night_avg_f": z.get("night_avg_f"),
            }
            for z in (snapshot.get("zones") or [])[:max_zones]
            if isinstance(z, dict)
        ],
        "systems": [
            {
                "ahu_name": s.get("ahu_name"),
                "fan_column": s.get("fan_column"),
                "median_recovery_f_per_min": s.get("median_recovery_f_per_min"),
                "zones": [
                    {
                        "label": z.get("label"),
                        "recovery_f_per_min": z.get("recovery_f_per_min"),
                        "day_avg_f": z.get("day_avg_f"),
                        "night_avg_f": z.get("night_avg_f"),
                    }
                    for z in (s.get("zones") or [])[:max_zones_per_system]
                    if isinstance(z, dict)
                ],
            }
            for s in (snapshot.get("systems") or [])[:max_systems]
            if isinstance(s, dict)
        ],
        "struggling_zones": [
            z
            for z in (snapshot.get("struggling_zones") or [])[:max_struggling]
            if isinstance(z, dict)
        ],
        "worst_zones": [
            {
                "label": z.get("label"),
                "equipment_name": z.get("equipment_name"),
                "day_avg_f": z.get("day_avg_f"),
                "night_avg_f": z.get("night_avg_f"),
                "recovery_f_per_min": z.get("recovery_f_per_min"),
                "worst_reason": z.get("worst_reason"),
            }
            for z in (snapshot.get("worst_zones") or [])[:6]
            if isinstance(z, dict)
        ],
        "site_aggregates": snapshot.get("site_aggregates"),
        "fan_schedule": snapshot.get("fan_schedule"),
        "lookback_days": snapshot.get("lookback_days"),
        "research": _slim_research(snapshot.get("research")),
    }


def _slim_research(research: Any) -> dict[str, Any] | None:
    if not isinstance(research, dict):
        return None
    from .zone_energy_research import slim_research_for_llm

    return slim_research_for_llm(research)


def compact_for_llm(snapshot: dict[str, Any], *, max_bytes: int = 2800) -> str:
    """Small JSON blob for building-insight / agent prompts (always valid JSON)."""
    limits = [
        (16, 6, 12, 8),
        (12, 4, 8, 6),
        (8, 3, 6, 4),
        (4, 2, 4, 2),
    ]
    for max_z, max_sys, max_zps, max_str in limits:
        slim = slim_zone_for_llm(
            snapshot,
            max_zones=max_z,
            max_systems=max_sys,
            max_zones_per_system=max_zps,
            max_struggling=max_str,
        )
        text = json.dumps(slim, separators=(",", ":"))
        if len(text.encode("utf-8")) <= max_bytes:
            return text
    slim = slim_zone_for_llm(snapshot, max_zones=2, max_systems=1, max_zones_per_system=2, max_struggling=2)
    return _compact_json_under_bytes(slim, max_bytes=max_bytes, summary_cap=120)


def _compact_json_under_bytes(
    slim: dict[str, Any],
    *,
    max_bytes: int,
    summary_cap: int = 120,
) -> str:
    """Trim string fields until JSON fits max_bytes (valid JSON guaranteed)."""
    slim = dict(slim)
    slim["summary_sentence"] = str(slim.get("summary_sentence") or "")[:summary_cap]
    cap = 80
    while cap >= 8:
        text = json.dumps(slim, separators=(",", ":"))
        if len(text.encode("utf-8")) <= max_bytes:
            return text
        for key, val in list(slim.items()):
            if isinstance(val, str) and len(val) > cap:
                slim[key] = val[:cap]
            elif isinstance(val, list):
                slim[key] = [
                    {
                        k: (v[:cap] if isinstance(v, str) and len(v) > cap else v)
                        for k, v in (item.items() if isinstance(item, dict) else [])
                    }
                    if isinstance(item, dict)
                    else item
                    for item in val
                ]
        cap //= 2
    slim["summary_sentence"] = str(slim.get("summary_sentence") or "")[: min(summary_cap, 40)]
    return json.dumps(slim, separators=(",", ":"))
