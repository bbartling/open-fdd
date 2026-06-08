"""BACnet poll throughput — expected vs observed samples per minute."""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from .bacnet_driver_store import driver_tree
from .commission_client import commission_poll_status
from .paths import bacnet_poll_csv, data_dir

DEFAULT_WINDOW_MIN = 60
MIN_WINDOW_MIN = 5
MAX_WINDOW_MIN = 180


def _window_minutes(raw: int | None) -> int:
    if raw is None:
        return DEFAULT_WINDOW_MIN
    return max(MIN_WINDOW_MIN, min(int(raw), MAX_WINDOW_MIN))


def _poll_csv_samples_in_window(*, window_min: int) -> dict[str, Any]:
    path = bacnet_poll_csv()
    if not path.is_file() or path.stat().st_size == 0:
        return {
            "csv_present": False,
            "rows_in_window": 0,
            "unique_points_in_window": 0,
            "observed_samples_per_min": 0.0,
            "window_minutes": window_min,
        }
    try:
        df = pd.read_csv(path, usecols=["timestamp_utc", "point_id"], low_memory=False)
    except (ValueError, pd.errors.EmptyDataError, OSError):
        return {
            "csv_present": True,
            "rows_in_window": 0,
            "unique_points_in_window": 0,
            "observed_samples_per_min": 0.0,
            "window_minutes": window_min,
            "parse_error": True,
        }
    if df.empty or "timestamp_utc" not in df.columns:
        return {
            "csv_present": True,
            "rows_in_window": 0,
            "unique_points_in_window": 0,
            "observed_samples_per_min": 0.0,
            "window_minutes": window_min,
        }
    ts = pd.to_datetime(df["timestamp_utc"], utc=True, errors="coerce")
    cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(minutes=window_min)
    mask = ts >= cutoff
    window_df = df.loc[mask]
    rows = int(len(window_df))
    unique_pts = int(window_df["point_id"].nunique()) if "point_id" in window_df.columns else 0
    rate = round(rows / max(window_min, 1), 2)
    return {
        "csv_present": True,
        "rows_in_window": rows,
        "unique_points_in_window": unique_pts,
        "observed_samples_per_min": rate,
        "window_minutes": window_min,
        "csv_mtime_age_s": round(time.time() - path.stat().st_mtime, 1),
    }


def _ingest_lag_s() -> float | None:
    path = data_dir() / "bacnet_ingest_state.json"
    if not path.is_file():
        return None
    try:
        import json

        raw = json.loads(path.read_text(encoding="utf-8"))
        at = str(raw.get("last_ingest_at") or raw.get("last_timestamp_utc") or "").strip()
        if not at:
            return None
        ts = datetime.fromisoformat(at.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - ts).total_seconds())
    except (OSError, ValueError, TypeError):
        return None


def _enabled_points_from_tree() -> list[dict[str, Any]]:
    tree = driver_tree()
    points: list[dict[str, Any]] = []
    for dev in tree.get("devices") or []:
        if not isinstance(dev, dict):
            continue
        for pt in dev.get("points") or []:
            if not isinstance(pt, dict) or not pt.get("enabled"):
                continue
            try:
                interval = int(pt.get("poll_interval_s") or 60)
            except (TypeError, ValueError):
                interval = 60
            points.append(
                {
                    "point_id": str(pt.get("point_id") or ""),
                    "poll_interval_s": max(60, interval),
                    "device_instance": str(dev.get("device_instance") or ""),
                }
            )
    return points


def compute_poll_throughput(*, window_minutes: int | None = None) -> dict[str, Any]:
    """Summarize BACnet poll duty vs observed CSV ingest rate.

    Note: the commission poll loop sleeps ``min(poll_interval_s)`` and RPM-polls
    **all** enabled points each cycle. Per-point intervals are configuration labels
    until per-point scheduling lands; ``cycle_model`` documents that behavior.
    """
    window_min = _window_minutes(window_minutes)
    enabled = _enabled_points_from_tree()
    enabled_n = len(enabled)

    by_interval: dict[int, int] = {}
    configured_duty_per_min = 0.0
    for pt in enabled:
        iv = int(pt["poll_interval_s"])
        by_interval[iv] = by_interval.get(iv, 0) + 1
        configured_duty_per_min += 60.0 / iv

    cycle_interval_s = 60.0
    if by_interval:
        cycle_interval_s = float(min(by_interval.keys()))
    cycles_per_min = 60.0 / max(cycle_interval_s, 15.0)
    expected_all_polled_per_min = round(enabled_n * cycles_per_min, 2)

    code, poll_payload = commission_poll_status()
    live: dict[str, Any] = {}
    if code == 200 and isinstance(poll_payload, dict):
        live = {
            "enabled_points": int(poll_payload.get("enabled_points") or enabled_n),
            "last_cycle_samples": int(poll_payload.get("samples") or 0),
            "last_poll_at": str(poll_payload.get("at") or ""),
            "last_poll_error": str(poll_payload.get("error") or "").strip(),
            "commission_interval_s": float(poll_payload.get("interval_s") or cycle_interval_s),
        }

    observed = _poll_csv_samples_in_window(window_min=window_min)
    ingest_lag = _ingest_lag_s()

    expected = expected_all_polled_per_min
    observed_rate = float(observed.get("observed_samples_per_min") or 0.0)
    keepup_ratio = round(observed_rate / expected, 3) if expected > 0 else None

    status = "unknown"
    if enabled_n == 0:
        status = "idle"
    elif live.get("last_poll_error"):
        status = "error"
    elif keepup_ratio is not None:
        if keepup_ratio >= 0.85:
            status = "healthy"
        elif keepup_ratio >= 0.5:
            status = "degraded"
        else:
            status = "lagging"
    elif observed_rate > 0:
        status = "warming"

    notes = [
        "Poll loop RPMs all enabled points each cycle; sleep uses minimum configured interval.",
        "configured_duty_per_min sums 60/interval per point (ideal per-point scheduling).",
        "expected_all_polled_per_min matches current driver: enabled_points × cycles_per_min.",
    ]

    return {
        "ok": True,
        "status": status,
        "window_minutes": window_min,
        "enabled_points": enabled_n,
        "cycle_interval_s": cycle_interval_s,
        "cycles_per_min": round(cycles_per_min, 3),
        "configured_duty_per_min": round(configured_duty_per_min, 2),
        "expected_all_polled_per_min": expected_all_polled_per_min,
        "observed_samples_per_min": observed_rate,
        "keepup_ratio": keepup_ratio,
        "interval_buckets": [
            {"poll_interval_s": iv, "points": n, "duty_per_min": round(n * 60.0 / iv, 2)}
            for iv, n in sorted(by_interval.items())
        ],
        "live_poll": live,
        "observed": observed,
        "ingest_lag_s": round(ingest_lag, 1) if ingest_lag is not None else None,
        "cycle_model": "all_enabled_each_cycle",
        "notes": notes,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
