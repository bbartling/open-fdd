"""Equipment online/flaky health from feather poll timestamps + FDD point bindings."""

from __future__ import annotations

import os
import time
from typing import Any

import pandas as pd

from .commission_client import commission_poll_status
from .data_loader import load_frame_for_run
from .fdd_results import fdd_issues
from .model_service import ModelService
from .paths import bacnet_poll_csv
from .operational_analytics import (
    analytics_lookback_days,
    analytics_methodology,
    trim_frame_to_lookback,
)
from .rule_store import RuleStore
from .site_defaults import ensure_default_site
from .timeseries_api import plot_column_name, resolve_historian_column
from .ttl_service import TtlService

_CACHE: dict[str, Any] = {"generated_at": 0.0, "payload": {}}

DEFAULT_INTERVAL_S = 60
STALE_MULTIPLIER = 2.5
FLAKY_FLIPS_PER_DAY = 6.0


def _poll_csv_fresh(*, max_age_s: float) -> bool:
    path = bacnet_poll_csv()
    if not path.is_file() or path.stat().st_size == 0:
        return False
    return (time.time() - path.stat().st_mtime) <= max_age_s


def _live_bacnet_poll_age_s() -> float | None:
    code, payload = commission_poll_status()
    if code != 200 or not isinstance(payload, dict):
        return None
    at_raw = str(payload.get("at") or "").strip()
    if not at_raw:
        return None
    try:
        ts = pd.Timestamp(at_raw.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        return max(0.0, (pd.Timestamp.now(tz="UTC") - ts).total_seconds())
    except (TypeError, ValueError):
        return None


def refresh_interval_s() -> int:
    raw = os.environ.get("OFDD_DEVICE_HEALTH_INTERVAL_S", "").strip()
    if not raw:
        return 3600
    try:
        return max(300, int(raw))
    except ValueError:
        return 3600


def _median_interval_sec(timestamps: pd.Series) -> float:
    ts = pd.to_datetime(timestamps, utc=True, errors="coerce").dropna().sort_values()
    if len(ts) < 3:
        return float(DEFAULT_INTERVAL_S)
    deltas = ts.diff().dt.total_seconds().dropna()
    if deltas.empty:
        return float(DEFAULT_INTERVAL_S)
    med = float(deltas.median())
    return max(30.0, min(med, 3600.0))


def _point_health(
    frame: pd.DataFrame,
    column: str,
    *,
    interval_s: float,
    lookback_days: int,
) -> dict[str, Any]:
    if column not in frame.columns or "timestamp" not in frame.columns:
        return {
            "column": column,
            "samples": 0,
            "valid_ratio": 0.0,
            "stale": True,
            "flips_per_day": 0.0,
            "last_seen_age_min": None,
        }
    work = frame.loc[:, ["timestamp", column]].copy()
    work["timestamp"] = pd.to_datetime(work["timestamp"], utc=True, errors="coerce")
    work = work.dropna(subset=["timestamp"]).sort_values("timestamp")
    has_value = work[column].notna()
    valid = work["timestamp"].notna() & has_value
    samples = int(len(work))
    valid_n = int(valid.sum())
    valid_ratio = round(valid_n / samples, 3) if samples else 0.0
    last_seen = work.loc[valid, "timestamp"].max() if valid_n else pd.NaT
    age_min = None
    stale = True
    if pd.notna(last_seen):
        age_min = round((pd.Timestamp.now(tz="UTC") - last_seen).total_seconds() / 60.0, 1)
        stale = age_min > (STALE_MULTIPLIER * interval_s / 60.0)
    stale_threshold = STALE_MULTIPLIER * interval_s
    online_flags: list[bool] = []
    last_t: pd.Timestamp | None = None
    for t, ok in zip(work["timestamp"], valid):
        if not ok:
            online_flags.append(False)
            continue
        if last_t is None:
            online_flags.append(True)
        else:
            gap = (t - last_t).total_seconds()
            online_flags.append(gap <= stale_threshold)
        last_t = t
    flips = 0
    for i in range(1, len(online_flags)):
        if online_flags[i] != online_flags[i - 1]:
            flips += 1
    flips_per_day = round(flips / max(lookback_days, 1), 2)
    return {
        "column": column,
        "samples": samples,
        "valid_ratio": valid_ratio,
        "stale": stale,
        "flips_per_day": flips_per_day,
        "last_seen_age_min": age_min,
    }


def _fdd_points_by_point_id() -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    store = RuleStore()
    for issue in fdd_issues():
        rule_id = str(issue.get("rule_id") or "").strip()
        if not rule_id:
            continue
        rule = store.get(rule_id)
        if not rule:
            continue
        for pid in rule.get("bindings", {}).get("point_ids") or []:
            key = str(pid).strip()
            if key:
                out.setdefault(key, []).append(issue)
    return out


def _equipment_for_site(model: dict[str, Any], site_id: str) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for eq in model.get("equipment") or []:
        if not isinstance(eq, dict) or str(eq.get("site_id") or "") not in {"", site_id}:
            continue
        eid = str(eq.get("id") or "").strip()
        if eid:
            index[eid] = eq
    return index


def _points_by_equipment(
    model: dict[str, Any],
    site_id: str,
    *,
    available_columns: set[str] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """One poll-health row per model point id — prefer feather column over stale fdd alias."""
    avail = set(available_columns or [])
    buckets: dict[str, dict[str, dict[str, Any]]] = {}
    for pt in model.get("points") or []:
        if not isinstance(pt, dict) or str(pt.get("site_id") or "") not in {"", site_id}:
            continue
        pid = str(pt.get("id") or "").strip()
        if avail:
            col = resolve_historian_column(pt, avail)
            if col not in avail:
                continue
        else:
            col = plot_column_name(pt)
        if not col or not pid:
            continue
        eid = str(pt.get("equipment_id") or "").strip() or "__unassigned__"
        buckets.setdefault(eid, {})[pid] = {**pt, "column": col}
    return {eid: list(pts.values()) for eid, pts in buckets.items()}


def _bacnet_device_key(eq: dict[str, Any], points: list[dict[str, Any]], eid: str) -> str:
    inst = eq.get("bacnet_device_instance")
    if inst is None:
        inst = eq.get("bacnet_device_id")
    if inst is not None and str(inst).strip():
        return f"dev:{inst}"
    for pt in points:
        dev = pt.get("bacnet_device_id")
        if dev is not None and str(dev).strip():
            return f"dev:{dev}"
    return f"eq:{eid}"


def _merge_equipment_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Merge duplicate BRICK equipment rows that share one BACnet device instance."""
    if not rows:
        return {}
    status_rank = {"offline": 0, "historian_lag": 1, "flaky": 2, "degraded": 3, "healthy": 4, "unknown": 5}
    merged = rows[0]
    for row in rows[1:]:
        merged["points_polled"] += row.get("points_polled") or 0
        merged["points_stale"] += row.get("points_stale") or 0
        merged["points_fdd"] += row.get("points_fdd") or 0
        merged["max_flips_per_day"] = max(
            float(merged.get("max_flips_per_day") or 0),
            float(row.get("max_flips_per_day") or 0),
        )
        merged["points"] = (merged.get("points") or []) + (row.get("points") or [])
        if status_rank.get(str(row.get("status")), 5) < status_rank.get(str(merged.get("status")), 5):
            merged["status"] = row["status"]
        alt_ids = merged.setdefault("_merged_equipment_ids", [merged.get("equipment_id")])
        alt = row.get("equipment_id")
        if alt and alt not in alt_ids:
            alt_ids.append(alt)
    merged["points"] = merged.get("points") or []
    merged["points"] = merged["points"][:24]
    return merged


def compute_device_poll_health(
    model: dict[str, Any],
    site_id: str,
    frame: pd.DataFrame,
    *,
    fdd_by_point: dict[str, list[dict[str, Any]]] | None = None,
    poll_csv_fresh_override: bool | None = None,
    live_poll_age_s_override: float | None = None,
) -> dict[str, Any]:
    lookback_days = analytics_lookback_days()
    fdd_by_point = fdd_by_point if fdd_by_point is not None else _fdd_points_by_point_id()
    eq_index = _equipment_for_site(model, site_id)
    avail_cols = set(frame.columns) if not frame.empty else set()
    by_eq = _points_by_equipment(model, site_id, available_columns=avail_cols)
    interval_s = _median_interval_sec(frame["timestamp"]) if not frame.empty else float(DEFAULT_INTERVAL_S)
    stale_after_s = STALE_MULTIPLIER * interval_s
    poll_csv_fresh = (
        poll_csv_fresh_override
        if poll_csv_fresh_override is not None
        else _poll_csv_fresh(max_age_s=stale_after_s)
    )
    live_poll_age_s = (
        live_poll_age_s_override
        if live_poll_age_s_override is not None
        else _live_bacnet_poll_age_s()
    )
    live_poll_fresh = live_poll_age_s is not None and live_poll_age_s <= stale_after_s
    equipment_rows: list[dict[str, Any]] = []
    by_device: dict[str, list[dict[str, Any]]] = {}

    for eid, points in sorted(by_eq.items()):
        if not points:
            continue
        eq = eq_index.get(eid) or {}
        name = str(eq.get("name") or eid)
        eq_family = str(eq.get("equipment_type") or "").split("_")[0][:8].upper() or "GENERAL"
        point_rows: list[dict[str, Any]] = []
        stale_n = 0
        fdd_n = 0
        flaky_n = 0
        for pt in points:
            col = pt["column"]
            ph = _point_health(frame, col, interval_s=interval_s, lookback_days=lookback_days)
            pid = str(pt.get("id") or "")
            has_fdd = bool(fdd_by_point.get(pid))
            ph["point_id"] = pid
            ph["has_fdd"] = has_fdd
            point_rows.append(ph)
            if ph["stale"]:
                stale_n += 1
            if has_fdd:
                fdd_n += 1
            if ph["flips_per_day"] >= FLAKY_FLIPS_PER_DAY:
                flaky_n += 1
        polled = len(point_rows)
        if polled == 0:
            status = "unknown"
        elif stale_n == polled or (fdd_n == polled and polled > 0):
            if (poll_csv_fresh or live_poll_fresh) and fdd_n < polled:
                status = "historian_lag"
            else:
                status = "offline"
        elif flaky_n > 0 or stale_n > 0 or fdd_n > 0:
            status = "degraded"
        else:
            status = "healthy"
        if flaky_n > 0 and status != "offline":
            status = "flaky"
        max_flips = max((p["flips_per_day"] for p in point_rows), default=0.0)
        row = {
            "equipment_id": eid,
            "equipment_name": name,
            "equipment_family": eq_family,
            "status": status,
            "points_polled": polled,
            "points_stale": stale_n,
            "points_fdd": fdd_n,
            "max_flips_per_day": max_flips,
            "median_poll_interval_s": round(interval_s, 1),
            "points": point_rows[:24],
            "bacnet_device_key": _bacnet_device_key(eq, points, eid),
        }
        by_device.setdefault(row["bacnet_device_key"], []).append(row)

    for group in by_device.values():
        equipment_rows.append(_merge_equipment_rows(group))

    offline = [e for e in equipment_rows if e["status"] == "offline"]
    historian_lag = [e for e in equipment_rows if e["status"] == "historian_lag"]
    flaky = [e for e in equipment_rows if e["status"] == "flaky"]
    degraded = [e for e in equipment_rows if e["status"] == "degraded"]
    healthy_n = sum(1 for e in equipment_rows if e["status"] == "healthy")
    summary = _health_summary_sentence(equipment_rows, offline, flaky, degraded, healthy_n, lookback_days)
    return {
        "site_id": site_id,
        "lookback_days": lookback_days,
        "methodology": analytics_methodology(),
        "median_poll_interval_s": round(interval_s, 1),
        "equipment": equipment_rows,
        "equipment_row_count": len(by_eq),
        "physical_device_count": len(equipment_rows),
        "offline_equipment": offline[:12],
        "historian_lag_equipment": historian_lag[:12],
        "flaky_equipment": flaky[:12],
        "degraded_equipment": degraded[:12],
        "healthy_count": healthy_n,
        "summary_sentence": summary,
    }


def _health_summary_sentence(
    all_rows: list[dict[str, Any]],
    offline: list[dict[str, Any]],
    flaky: list[dict[str, Any]],
    degraded: list[dict[str, Any]],
    healthy_n: int,
    lookback_days: int,
) -> str:
    if not all_rows:
        return "No model points mapped to feather columns for poll health."
    parts = [f"Poll health ({lookback_days}d): {healthy_n}/{len(all_rows)} device(s) fully healthy."]
    if offline:
        names = ", ".join(e["equipment_name"] for e in offline[:4])
        extra = f" (+{len(offline)-4} more)" if len(offline) > 4 else ""
        parts.append(f"Offline (all points stale or FDD): {names}{extra}.")
    if flaky:
        names = ", ".join(
            f"{e['equipment_name']} ({e['max_flips_per_day']:.0f} flips/d)"
            for e in flaky[:3]
        )
        parts.append(f"Flaky comm: {names}.")
    if degraded and not offline:
        names = ", ".join(e["equipment_name"] for e in degraded[:3])
        parts.append(f"Degraded (some sensors): {names}.")
    return " ".join(parts)


def poll_health_alerts(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Check-engine alerts for offline/flaky equipment (operator-facing device names, not fault codes)."""
    alerts: list[dict[str, Any]] = []
    for eq in snapshot.get("offline_equipment") or []:
        if not isinstance(eq, dict):
            continue
        eid = eq.get("equipment_id")
        name = str(eq.get("equipment_name") or eid or "Equipment").strip()
        alerts.append(
            {
                "id": f"poll-offline-{eid}",
                "severity": "critical",
                "title": f"{name}: no recent telemetry",
                "detail": (
                    f"All {eq.get('points_polled')} mapped point(s) are stale or FDD-flagged in the last "
                    f"{snapshot.get('lookback_days')} days. BACnet polling may be down or points are not ingesting "
                    "into the historian."
                ),
                "source": "poll_health",
                "equipment_family": "POLL",
                "equipment_id": eid,
                "equipment_name": name,
            }
        )
    for eq in snapshot.get("historian_lag_equipment") or []:
        if not isinstance(eq, dict):
            continue
        eid = eq.get("equipment_id")
        name = str(eq.get("equipment_name") or eid or "Equipment").strip()
        alerts.append(
            {
                "id": f"poll-historian-{eid}",
                "severity": "warning",
                "title": f"{name}: historian behind live poll",
                "detail": (
                    f"BACnet poll CSV is fresh but feather columns for this device are stale "
                    f"({eq.get('points_polled')} point(s)). Check bridge ingest after poll cycles."
                ),
                "source": "poll_health",
                "equipment_family": "POLL",
                "equipment_id": eid,
                "equipment_name": name,
            }
        )
    for eq in snapshot.get("flaky_equipment") or []:
        if not isinstance(eq, dict):
            continue
        eid = eq.get("equipment_id")
        name = str(eq.get("equipment_name") or eid or "Equipment").strip()
        alerts.append(
            {
                "id": f"poll-flaky-{eid}",
                "severity": "warning",
                "title": f"{name}: flaky BACnet poll",
                "detail": (
                    f"Up to {eq.get('max_flips_per_day')} online/offline transitions per day "
                    f"across points (last {snapshot.get('lookback_days')} days)."
                ),
                "source": "poll_health",
                "equipment_family": "POLL",
                "equipment_id": eid,
                "equipment_name": name,
            }
        )
    return alerts


def get_device_poll_snapshot(*, site_id: str | None = None, force: bool = False) -> dict[str, Any]:
    now = time.time()
    interval = refresh_interval_s()
    cache_key = site_id or "__default__"
    cached = _CACHE.get("payload") or {}
    entry = cached.get(cache_key) if isinstance(cached, dict) else None
    if (
        not force
        and isinstance(entry, dict)
        and now < float(entry.get("next_refresh_at") or 0)
    ):
        return {**entry, "ok": True, "cached": True, "refresh_interval_s": interval}

    model_svc = ModelService()
    sid = (site_id or "").strip() or ensure_default_site(model_svc, TtlService())
    model = model_svc.load()
    frame, origin = load_frame_for_run(sid)
    frame = trim_frame_to_lookback(frame)
    metrics = compute_device_poll_health(model, sid, frame)
    payload = {
        "ok": True,
        "cached": False,
        "generated_at": now,
        "next_refresh_at": now + interval,
        "refresh_interval_s": interval,
        "data_source": origin,
        **metrics,
    }
    stored = dict(cached) if isinstance(cached, dict) else {}
    stored[cache_key] = payload
    _CACHE["payload"] = stored
    return payload


def slim_devices_for_llm(snapshot: dict[str, Any], *, max_equipment: int = 10) -> dict[str, Any]:
    return {
        "lookback_days": snapshot.get("lookback_days"),
        "summary_sentence": str(snapshot.get("summary_sentence") or "")[:400],
        "healthy_count": snapshot.get("healthy_count"),
        "offline": [
            {"name": e.get("equipment_name"), "points_stale": e.get("points_stale"), "points_polled": e.get("points_polled")}
            for e in (snapshot.get("offline_equipment") or [])[:max_equipment]
            if isinstance(e, dict)
        ],
        "flaky": [
            {"name": e.get("equipment_name"), "max_flips_per_day": e.get("max_flips_per_day")}
            for e in (snapshot.get("flaky_equipment") or [])[:max_equipment]
            if isinstance(e, dict)
        ],
        "degraded": [
            {"name": e.get("equipment_name"), "points_fdd": e.get("points_fdd"), "points_stale": e.get("points_stale")}
            for e in (snapshot.get("degraded_equipment") or [])[:max_equipment]
            if isinstance(e, dict)
        ],
    }
