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
from .timeseries_api import plot_column_name
from .ttl_service import TtlService

_CACHE: dict[str, Any] = {"generated_at": 0.0, "next_refresh_at": 0.0, "payload": {}}

ZONE_BRICK_MARKERS = ("zone_air_temperature", "zone temperature")
FAN_BRICK_MARKERS = ("supply_fan", "fan_speed", "fan_command", "fan_status", "fan_start")
DEFAULT_INTERVAL_S = 3600


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


def _zone_points_for_equipment(
    model: dict[str, Any],
    site_id: str,
    equipment_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    eq_index = _equipment_index(model, site_id)
    rows: list[dict[str, Any]] = []
    for pt in model.get("points") or []:
        if not isinstance(pt, dict) or str(pt.get("site_id") or "") not in {"", site_id}:
            continue
        if not _is_zone_point(pt):
            continue
        eid = str(pt.get("equipment_id") or "").strip()
        if equipment_ids is not None and eid not in equipment_ids:
            continue
        col = plot_column_name(pt)
        if not col:
            continue
        eq = eq_index.get(eid) or {}
        rows.append(
            {
                "point_id": str(pt.get("id") or ""),
                "equipment_id": eid,
                "equipment_name": str(eq.get("name") or eid),
                "column": col,
                "label": str(pt.get("name") or pt.get("description") or col),
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


def discover_topology(model: dict[str, Any], site_id: str) -> dict[str, Any]:
    """Resolve zone sensors and optional AHU→zone groupings from BRICK JSON + feeds."""
    eq_index = _equipment_index(model, site_id)
    all_zones = _zone_points_for_equipment(model, site_id, None)
    feeds = _feeds_map(model, site_id)
    ahu_systems: list[dict[str, Any]] = []
    assigned_zone_cols: set[str] = set()

    for ahu_id, eq in eq_index.items():
        if not _is_ahu(eq):
            continue
        child_ids = set(feeds.get(ahu_id) or [])
        vav_ids = {cid for cid in child_ids if cid in eq_index and _is_vav(eq_index[cid])}
        zone_scope = vav_ids or child_ids or {ahu_id}
        zones = _zone_points_for_equipment(model, site_id, zone_scope)
        if not zones:
            zones = _zone_points_for_equipment(model, site_id, {ahu_id})
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
    zones_out: list[dict[str, Any]] = []
    for zp in topology.get("zone_points") or []:
        col = zp["column"]
        if col not in zone_df.columns:
            continue
        s = _column_series(zone_df, col)
        day = s[occupied].dropna()
        night = s[~occupied].dropna()
        zones_out.append(
            {
                **zp,
                "day_avg_f": round(float(day.mean()), 2) if not day.empty else None,
                "night_avg_f": round(float(night.mean()), 2) if not night.empty else None,
                "samples": int(s.notna().sum()),
            }
        )

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

    worst_zones = _worst_zones(zones_out, systems_out, struggling)
    sentence = _summary_sentence(zones_out, systems_out, struggling, topology.get("mode"))
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
        "dataframe_rows": len(zone_df),
        "dataframe_preview": preview.to_dict(orient="records"),
        "summary_sentence": sentence,
    }


def _worst_zones(
    zones_out: list[dict[str, Any]],
    systems_out: list[dict[str, Any]],
    struggling: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Rank zones for operator/LLM focus (slow recovery, large day/night spread)."""
    recovery_by_col: dict[str, float] = {}
    for sys in systems_out:
        for z in sys.get("zones") or []:
            col = z.get("column")
            rec = z.get("recovery_f_per_min")
            if col and rec is not None:
                recovery_by_col[col] = float(rec)
    scored: list[tuple[float, dict[str, Any]]] = []
    for z in zones_out:
        col = z.get("column")
        score = 0.0
        day = z.get("day_avg_f")
        night = z.get("night_avg_f")
        if day is not None and night is not None:
            score += abs(float(day) - float(night))
        rec = recovery_by_col.get(col or "")
        if rec is not None and rec < 0.03:
            score += 5.0
        for s in struggling:
            if s.get("column") == col:
                score += 10.0
        if score > 0:
            scored.append((score, {**z, "recovery_f_per_min": rec}))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in scored[:8]]


def _summary_sentence(
    zones: list[dict[str, Any]],
    systems: list[dict[str, Any]],
    struggling: list[dict[str, Any]],
    mode: str | None,
) -> str:
    if not zones:
        return "No BRICK zone temperature sensors in the model."
    with_day = [z for z in zones if z.get("day_avg_f") is not None]
    with_night = [z for z in zones if z.get("night_avg_f") is not None]
    parts: list[str] = []
    if with_night:
        night_avg = sum(z["night_avg_f"] for z in with_night) / len(with_night)
        parts.append(f"overnight zone temps average {night_avg:.1f}°F")
    if with_day:
        day_avg = sum(z["day_avg_f"] for z in with_day) / len(with_day)
        parts.append(f"occupied daytime average {day_avg:.1f}°F across {len(with_day)} sensor(s)")
    if systems and any(s.get("median_recovery_f_per_min") is not None for s in systems):
        medians = [s["median_recovery_f_per_min"] for s in systems if s.get("median_recovery_f_per_min") is not None]
        parts.append(f"typical warm-up rate ~{sum(medians)/len(medians):.2f}°F/min after fan start")
    if struggling:
        labels = ", ".join(s["label"] for s in struggling[:3])
        extra = f" (+{len(struggling)-3} more)" if len(struggling) > 3 else ""
        parts.append(f"slow zones under {struggling[0].get('ahu_name')}: {labels}{extra}")
    elif mode == "sensors_only":
        parts.append("no AHU/feeds grouping — site-wide sensor average only")
    if not parts:
        return f"{len(zones)} zone temperature sensor(s) mapped; insufficient trend samples for day/night split."
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
    topology = discover_topology(model, sid)
    df, origin = load_frame_for_run(sid)
    df = trim_frame_to_lookback(df)

    site_tz = _site_timezone(model, sid)
    metrics = compute_zone_metrics(df, topology, model, sid, site_tz=site_tz)
    from .device_poll_health import get_device_poll_snapshot
    from .zone_energy_research import build_zone_energy_research

    device_snapshot = get_device_poll_snapshot(site_id=sid, force=force)
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
                "day_avg_f": z.get("day_avg_f"),
                "night_avg_f": z.get("night_avg_f"),
                "recovery_f_per_min": z.get("recovery_f_per_min"),
            }
            for z in (snapshot.get("worst_zones") or [])[:6]
            if isinstance(z, dict)
        ],
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
        if len(text) <= max_bytes:
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
