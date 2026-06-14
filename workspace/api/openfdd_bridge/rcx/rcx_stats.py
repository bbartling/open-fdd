"""Read-only trend statistics for RCx reports (no pandas)."""

from __future__ import annotations

from datetime import datetime
from typing import Any


def _parse_ts(raw: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _hours_span(timestamps: list[Any]) -> float:
    if len(timestamps) < 2:
        return 0.0
    start = _parse_ts(timestamps[0])
    end = _parse_ts(timestamps[-1])
    if not start or not end:
        return 0.0
    return max(0.0, (end - start).total_seconds() / 3600.0)


def _numeric_stats(values: list[Any]) -> dict[str, float | int | None]:
    nums = [float(v) for v in values if v is not None]
    if not nums:
        return {"count": 0, "min": None, "max": None, "mean": None}
    return {
        "count": len(nums),
        "min": round(min(nums), 3),
        "max": round(max(nums), 3),
        "mean": round(sum(nums) / len(nums), 3),
    }


def _fault_hours(timestamps: list[Any], flags: list[int]) -> float:
    if len(timestamps) < 2 or not flags:
        return 0.0
    total = 0.0
    for i in range(1, min(len(timestamps), len(flags))):
        if not flags[i - 1]:
            continue
        t0 = _parse_ts(timestamps[i - 1])
        t1 = _parse_ts(timestamps[i])
        if t0 and t1:
            total += max(0.0, (t1 - t0).total_seconds() / 3600.0)
    return round(total, 2)


def summarize_readings(
    readings: dict[str, Any],
    *,
    chart_id: str = "",
    title: str = "",
) -> dict[str, Any]:
    """Dataset statistics similar to legacy FaultCodeOneReport.summarize_fault_times."""
    timestamps = readings.get("timestamps") or []
    series = readings.get("series") if isinstance(readings.get("series"), dict) else {}
    labels = readings.get("labels") if isinstance(readings.get("labels"), dict) else {}
    total_hours = round(_hours_span(timestamps), 2)
    total_days = round(total_hours / 24.0, 2) if total_hours else 0.0

    series_stats: dict[str, dict[str, Any]] = {}
    for col, vals in series.items():
        if not isinstance(vals, list):
            continue
        series_stats[str(labels.get(col) or col)] = _numeric_stats(vals)

    fault_hours = 0.0
    fault_plots = readings.get("fault_plots") if isinstance(readings.get("fault_plots"), dict) else {}
    for flags in fault_plots.values():
        if isinstance(flags, list):
            fault_hours += _fault_hours(timestamps, [int(f or 0) for f in flags])
    fault_hours = round(fault_hours, 2)
    fault_pct = round((fault_hours / total_hours) * 100.0, 2) if total_hours > 0 else 0.0

    bullets: list[str] = []
    if total_days:
        bullets.append(f"Dataset span: {total_days} day(s) (~{total_hours} h)")
    if fault_hours:
        bullets.append(f"Estimated fault-active time: {fault_hours} h ({fault_pct}% of window)")
    else:
        bullets.append("No fault overlay flags in this window for selected rules.")
    for name, st in list(series_stats.items())[:4]:
        if st.get("count"):
            bullets.append(
                f"{name}: min {st.get('min')}, max {st.get('max')}, mean {st.get('mean')} "
                f"({st.get('count')} samples)"
            )

    return {
        "chart_id": chart_id,
        "title": title,
        "total_days": total_days,
        "total_hours": total_hours,
        "fault_hours": fault_hours,
        "fault_percent": fault_pct,
        "series_stats": series_stats,
        "stats_bullets": bullets,
        "row_count": int(readings.get("row_count") or len(timestamps)),
    }
