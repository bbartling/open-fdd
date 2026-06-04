"""Zone temperature research signals for building insight / agent LLM context.

Cross-checks zone day/night averages, recovery rates, unoccupied heat drift,
and device poll + FDD sensor health — then emits structured flags the LLM must
interpret (energy savings, stuck sensors, HVAC effectiveness).
"""

from __future__ import annotations

import os
from typing import Any

import pandas as pd

from .operational_analytics import analytics_lookback_days
from .timeseries_api import plot_column_name

NEAR_ZERO_RECOVERY_FPM = 0.05
MIN_SETBACK_DELTA_F = 1.5
FLAT_UNOCCUPIED_SLOPE_FPH = 0.03
FLATLINE_STD_F = 0.15


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _column_point_health(device_snapshot: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Map feather column → poll/FDD health from device_poll_health snapshot."""
    out: dict[str, dict[str, Any]] = {}
    if not device_snapshot:
        return out
    for eq in device_snapshot.get("equipment") or []:
        if not isinstance(eq, dict):
            continue
        for pt in eq.get("points") or []:
            if not isinstance(pt, dict):
                continue
            col = str(pt.get("column") or "").strip()
            if col:
                out[col] = {
                    "stale": pt.get("stale"),
                    "has_fdd": pt.get("has_fdd"),
                    "valid_ratio": pt.get("valid_ratio"),
                    "flips_per_day": pt.get("flips_per_day"),
                    "equipment_name": eq.get("equipment_name"),
                }
    return out


def _unoccupied_slopes(
    zone_df: pd.DataFrame,
    zone_columns: list[str],
    *,
    occupied_mask: pd.Series | None,
) -> dict[str, float]:
    """Mean °F/h slope during unoccupied samples (positive = gaining heat)."""
    if zone_df.empty or "timestamp" not in zone_df.columns:
        return {}
    ts = pd.to_datetime(zone_df["timestamp"], utc=True, errors="coerce")
    if occupied_mask is None or len(occupied_mask) != len(zone_df):
        return {}
    slopes: dict[str, float] = {}
    for col in zone_columns:
        if col not in zone_df.columns:
            continue
        mask = ~occupied_mask
        seg = zone_df.loc[mask, ["timestamp", col]].copy()
        seg[col] = pd.to_numeric(seg[col], errors="coerce")
        seg = seg.dropna()
        if len(seg) < 8:
            continue
        hours = (seg["timestamp"].iloc[-1] - seg["timestamp"].iloc[0]).total_seconds() / 3600.0
        if hours < 1.0:
            continue
        delta = float(seg[col].iloc[-1] - seg[col].iloc[0])
        slopes[col] = round(delta / hours, 4)
    return slopes


def _zone_std_unoccupied(zone_df: pd.DataFrame, col: str, occupied_mask: pd.Series) -> float | None:
    if col not in zone_df.columns:
        return None
    s = pd.to_numeric(zone_df.loc[~occupied_mask, col], errors="coerce").dropna()
    if len(s) < 6:
        return None
    return float(s.std())


def build_zone_energy_research(
    zone_snapshot: dict[str, Any],
    device_snapshot: dict[str, Any] | None = None,
    *,
    zone_df: pd.DataFrame | None = None,
    occupied_mask: pd.Series | None = None,
) -> dict[str, Any]:
    """Structured research bundle for API + LLM (deterministic pandas; LLM interprets)."""
    near_zero = _env_float("OFDD_NEAR_ZERO_RECOVERY_FPM", NEAR_ZERO_RECOVERY_FPM)
    min_setback = _env_float("OFDD_MIN_SETBACK_DELTA_F", MIN_SETBACK_DELTA_F)
    flat_slope = _env_float("OFDD_FLAT_UNOCCUPIED_SLOPE_FPH", FLAT_UNOCCUPIED_SLOPE_FPH)

    zones = [z for z in (zone_snapshot.get("zones") or []) if isinstance(z, dict)]
    systems = [s for s in (zone_snapshot.get("systems") or []) if isinstance(s, dict)]
    col_health = _column_point_health(device_snapshot)

    recovery_rates = [
        float(s["median_recovery_f_per_min"])
        for s in systems
        if s.get("median_recovery_f_per_min") is not None
    ]
    site_median_recovery = (
        sorted(recovery_rates)[len(recovery_rates) // 2] if recovery_rates else None
    )

    zone_columns = [str(z.get("column") or "") for z in zones if z.get("column")]
    unoccupied_slopes = (
        _unoccupied_slopes(zone_df, zone_columns, occupied_mask=occupied_mask)
        if zone_df is not None and occupied_mask is not None
        else {}
    )

    per_zone: list[dict[str, Any]] = []
    minimal_setback_zones: list[str] = []
    near_zero_recovery_zones: list[str] = []
    suspicious_sensors: list[str] = []
    gaining_heat: list[str] = []
    losing_heat: list[str] = []

    for z in zones:
        col = str(z.get("column") or "")
        label = str(z.get("label") or col)
        day = z.get("day_avg_f")
        night = z.get("night_avg_f")
        setback = None
        if day is not None and night is not None:
            setback = round(float(day) - float(night), 2)
        rec = z.get("recovery_f_per_min")
        health = col_health.get(col) or {}
        slope = unoccupied_slopes.get(col)
        std_u = (
            _zone_std_unoccupied(zone_df, col, occupied_mask)
            if zone_df is not None and occupied_mask is not None
            else None
        )

        flags: list[str] = []
        if setback is not None and abs(setback) < min_setback:
            flags.append("minimal_setback")
            minimal_setback_zones.append(label)
        if rec is not None and float(rec) < near_zero:
            flags.append("near_zero_recovery")
            near_zero_recovery_zones.append(label)
        elif site_median_recovery is not None and site_median_recovery < near_zero:
            if rec is None:
                flags.append("no_fan_recovery_signal")
        if slope is not None:
            if slope > flat_slope:
                flags.append("unoccupied_heat_gain")
                gaining_heat.append(label)
            elif slope < -flat_slope:
                flags.append("unoccupied_heat_loss")
                losing_heat.append(label)
        if std_u is not None and std_u < FLATLINE_STD_F and (setback is not None and abs(setback) < min_setback):
            flags.append("flat_unoccupied_profile")
        if health.get("stale"):
            flags.append("poll_stale")
            suspicious_sensors.append(label)
        if health.get("has_fdd"):
            flags.append("fdd_active")
            if label not in suspicious_sensors:
                suspicious_sensors.append(label)
        if health.get("valid_ratio") is not None and float(health["valid_ratio"]) < 0.5:
            flags.append("sparse_samples")
            if label not in suspicious_sensors:
                suspicious_sensors.append(label)

        per_zone.append(
            {
                "label": label,
                "column": col,
                "setback_delta_f": setback,
                "recovery_f_per_min": rec,
                "unoccupied_slope_f_per_h": slope,
                "unoccupied_std_f": round(std_u, 3) if std_u is not None else None,
                "sensor_health": health or None,
                "flags": flags,
            }
        )

    site_flags: list[str] = []
    if site_median_recovery is not None and site_median_recovery < near_zero:
        site_flags.append("site_near_zero_recovery")
    if len(minimal_setback_zones) >= max(3, len(zones) // 3):
        site_flags.append("widespread_minimal_setback")
    if len(zones) >= 4 and len(minimal_setback_zones) >= 0.5 * len(zones):
        site_flags.append("likely_no_overnight_setback")

    opportunities: list[dict[str, str]] = []
    if "site_near_zero_recovery" in site_flags or "widespread_minimal_setback" in site_flags:
        opportunities.append(
            {
                "topic": "energy_setback",
                "signal": (
                    f"Day/night zone averages differ by <{min_setback}°F for many sensors and "
                    f"warm-up after fan start is ~{site_median_recovery or 0:.2f}°F/min — "
                    "zones may not be setting back overnight."
                ),
                "suggestion": (
                    "Review occupied/unoccupied schedules, zone setpoints, and optimal start; "
                    "widening night setback often saves reheat/cooling energy."
                ),
            }
        )
    if suspicious_sensors:
        opportunities.append(
            {
                "topic": "sensor_integrity",
                "signal": f"{len(suspicious_sensors)} zone sensor(s) stale, FDD-flagged, or flat.",
                "suggestion": "Validate BACnet bindings and replace or remap stuck zone temp points before tuning schedules.",
            }
        )
    if gaining_heat and not losing_heat and "widespread_minimal_setback" in site_flags:
        opportunities.append(
            {
                "topic": "overnight_load",
                "signal": "Unoccupied periods show net heat gain without matching setback.",
                "suggestion": "Check simultaneous heating sources, faulty economizer, or schedules holding day setpoints at night.",
            }
        )

    llm_tasks = _llm_research_tasks(
        site_median_recovery=site_median_recovery,
        site_flags=site_flags,
        minimal_setback_zones=minimal_setback_zones,
        near_zero_recovery_zones=near_zero_recovery_zones,
        suspicious_sensors=suspicious_sensors,
        opportunities=opportunities,
        near_zero_threshold=near_zero,
        min_setback=min_setback,
    )

    return {
        "lookback_days": zone_snapshot.get("lookback_days") or analytics_lookback_days(),
        "site_median_recovery_f_per_min": site_median_recovery,
        "thresholds": {
            "near_zero_recovery_f_per_min": near_zero,
            "minimal_setback_delta_f": min_setback,
            "flat_unoccupied_slope_f_per_h": flat_slope,
        },
        "site_flags": site_flags,
        "minimal_setback_zone_count": len(minimal_setback_zones),
        "near_zero_recovery_zone_count": len(near_zero_recovery_zones),
        "minimal_setback_zones": minimal_setback_zones[:12],
        "near_zero_recovery_zones": near_zero_recovery_zones[:12],
        "suspicious_sensors": suspicious_sensors[:12],
        "unoccupied_heat_gain_zones": gaining_heat[:8],
        "unoccupied_heat_loss_zones": losing_heat[:8],
        "zones": per_zone[:24],
        "opportunities": opportunities,
        "llm_research_tasks": llm_tasks,
        "interpretation_guide": (
            "Use site_flags and per-zone flags with device_poll_health. "
            "Near-zero recovery with minimal setback usually means zones stay near occupied temperature overnight — "
            "investigate schedules before blaming HVAC capacity. "
            "Cross-check flat profiles with stale/FDD sensors before recommending energy changes."
        ),
    }


def _llm_research_tasks(
    *,
    site_median_recovery: float | None,
    site_flags: list[str],
    minimal_setback_zones: list[str],
    near_zero_recovery_zones: list[str],
    suspicious_sensors: list[str],
    opportunities: list[dict[str, str]],
    near_zero_threshold: float,
    min_setback: float,
) -> list[str]:
    tasks: list[str] = []
    if site_median_recovery is not None and site_median_recovery < near_zero_threshold:
        tasks.append(
            f"Recovery rate ~{site_median_recovery:.2f}°F/min is below {near_zero_threshold}°F/min: "
            "explain whether zones are not warming after fan start, fan signal is wrong, or setback is absent."
        )
    if "widespread_minimal_setback" in site_flags or "likely_no_overnight_setback" in site_flags:
        tasks.append(
            f"Day vs night averages differ by less than {min_setback}°F across many zones — "
            "comment on possible missing overnight setback and energy savings if schedules were tightened."
        )
    if suspicious_sensors:
        tasks.append(
            "Correlate zone sensors flagged stale/FDD/flat with poll health — "
            "recommend fixing sensors before operational conclusions."
        )
    if opportunities:
        tasks.append(
            "Prioritize opportunities[] topics (energy_setback, sensor_integrity, overnight_load) "
            "in plain English with cautious wording (verify on site)."
        )
    if not tasks:
        tasks.append(
            "Summarize zone comfort vs efficiency: setback spread, recovery, and any offline zone hardware."
        )
    return tasks


def slim_research_for_llm(research: dict[str, Any]) -> dict[str, Any]:
    """Compact research object for building-insight JSON context."""
    return {
        "site_flags": research.get("site_flags") or [],
        "site_median_recovery_f_per_min": research.get("site_median_recovery_f_per_min"),
        "minimal_setback_zone_count": research.get("minimal_setback_zone_count"),
        "near_zero_recovery_zone_count": research.get("near_zero_recovery_zone_count"),
        "minimal_setback_zones": (research.get("minimal_setback_zones") or [])[:6],
        "suspicious_sensors": (research.get("suspicious_sensors") or [])[:6],
        "opportunities": (research.get("opportunities") or [])[:4],
        "llm_research_tasks": (research.get("llm_research_tasks") or [])[:5],
        "interpretation_guide": str(research.get("interpretation_guide") or "")[:500],
    }
