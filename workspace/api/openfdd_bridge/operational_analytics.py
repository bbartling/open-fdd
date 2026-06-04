"""Shared lookback window and methodology for operator analytics (zone temps, poll health)."""

from __future__ import annotations

import os
from typing import Any

import pandas as pd

DEFAULT_LOOKBACK_DAYS = 14


def analytics_lookback_days() -> int:
    raw = os.environ.get("OFDD_ANALYTICS_LOOKBACK_DAYS", "").strip()
    if not raw:
        return DEFAULT_LOOKBACK_DAYS
    try:
        return max(1, min(int(raw), 90))
    except ValueError:
        return DEFAULT_LOOKBACK_DAYS


def analytics_lookback_hours() -> float:
    return float(analytics_lookback_days()) * 24.0


def trim_frame_to_lookback(df: pd.DataFrame, *, hours: float | None = None) -> pd.DataFrame:
    """Keep rows within the analytics window (UTC)."""
    if df.empty or "timestamp" not in df.columns:
        return df
    window_h = hours if hours is not None else analytics_lookback_hours()
    cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=window_h)
    ts = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    trimmed = df.loc[ts >= cutoff]
    return trimmed


def analytics_methodology() -> dict[str, Any]:
    """Describe how pandas levers are computed — included in LLM context and API responses."""
    days = analytics_lookback_days()
    return {
        "lookback_days": days,
        "lookback_hours": analytics_lookback_hours(),
        "zone_temperatures": (
            f"Zone day/night averages use the last {days} days of feather poll data; "
            "occupied hours from OFDD_OCCUPIED_START_HOUR/END_HOUR (weekdays)."
        ),
        "recovery_rates": (
            f"Recovery °F/min is the mean warm-up slope after supply-fan start events in the last {days} days, "
            "only while the fan command/speed is on; each fan cycle uses up to 30 minutes of zone temperature."
        ),
        "device_poll_health": (
            f"Per-equipment online health uses the same {days}-day feather window: a point is stale when "
            "gaps exceed ~2.5× the median poll interval. If every polled point on equipment is stale or "
            "FDD-flagged, the device is treated as offline; one bad sensor is a point-level problem."
        ),
        "flaky_devices": (
            "Flaky = frequent online/offline transitions (stale↔fresh) per day inferred from poll timestamps."
        ),
        "zone_energy_research": (
            "Deterministic flags (minimal_setback, near_zero_recovery, unoccupied heat drift, stale/FDD sensors) "
            "feed the building-insight LLM via zone_temps.research — the model must cross-check poll health before "
            "claiming energy savings or broken sensors."
        ),
    }


def methodology_prompt_blurb() -> str:
    m = analytics_methodology()
    return (
        f"Analytics window: last {m['lookback_days']} days of BACnet→feather historian. "
        f"{m['zone_temperatures']} {m['recovery_rates']} {m['device_poll_health']}"
    )
