"""Site occupancy weekly schedule — generic Mon–Sun open/close times for SCHED-1 overlays."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DAY_LABELS = {
    "mon": "Monday",
    "tue": "Tuesday",
    "wed": "Wednesday",
    "thu": "Thursday",
    "fri": "Friday",
    "sat": "Saturday",
    "sun": "Sunday",
}


@dataclass
class DaySchedule:
    occupied: bool = True
    start: str = "06:00"  # HH:MM local
    end: str = "18:00"


@dataclass
class OccupancySchedule:
    """Weekly occupancy calendar. Times are wall-clock on the series index timezone."""

    days: dict[str, DaySchedule] = field(default_factory=dict)
    timezone: str = "America/Chicago"

    def __post_init__(self) -> None:
        if not self.days:
            self.days = {
                d: DaySchedule(occupied=(d not in {"sat", "sun"}), start="06:00", end="18:00")
                for d in DAYS
            }

    def to_dict(self) -> dict[str, Any]:
        return {
            "timezone": self.timezone,
            "days": {
                k: {"occupied": v.occupied, "start": v.start, "end": v.end}
                for k, v in self.days.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> OccupancySchedule:
        if not data:
            return cls()
        days: dict[str, DaySchedule] = {}
        raw_days = data.get("days") or {}
        for d in DAYS:
            # Legacy sessions may have mis-named Saturday as "discharge-air-temp"
            row = raw_days.get(d) or (raw_days.get("discharge-air-temp") if d == "sat" else {}) or {}
            days[d] = DaySchedule(
                occupied=bool(row.get("occupied", d not in {"sat", "sun"})),
                start=str(row.get("start", "06:00")),
                end=str(row.get("end", "18:00")),
            )
        return cls(days=days, timezone=str(data.get("timezone") or "America/Chicago"))


def _parse_hhmm(text: str) -> tuple[int, int]:
    parts = str(text).strip().split(":")
    h = int(parts[0]) if parts else 0
    m = int(parts[1]) if len(parts) > 1 else 0
    return h, m


def occupied_mask(index: pd.DatetimeIndex, schedule: OccupancySchedule) -> pd.Series:
    """True when timestamp falls inside the weekly occupied window."""
    if not isinstance(index, pd.DatetimeIndex) or len(index) == 0:
        return pd.Series(dtype=bool)
    # Align to schedule timezone for weekday/time checks
    try:
        local = index.tz_convert(schedule.timezone) if index.tz is not None else index.tz_localize("UTC").tz_convert(schedule.timezone)
    except Exception:
        local = index
    day_keys = local.dayofweek.map(lambda i: DAYS[int(i)])  # Mon=0
    minutes = local.hour * 60 + local.minute
    out = []
    for dk, mins in zip(day_keys, minutes):
        day = schedule.days.get(str(dk), DaySchedule(occupied=False))
        if not day.occupied:
            out.append(False)
            continue
        sh, sm = _parse_hhmm(day.start)
        eh, em = _parse_hhmm(day.end)
        start_m, end_m = sh * 60 + sm, eh * 60 + em
        if end_m <= start_m:
            # overnight window
            out.append(mins >= start_m or mins < end_m)
        else:
            out.append(start_m <= mins < end_m)
    return pd.Series(out, index=index, dtype=bool)


def occupied_hours_per_week(schedule: OccupancySchedule) -> float:
    """Nominal occupied hours in one Mon–Sun week from the calendar (for bare-min runtime lines)."""
    total = 0.0
    for d in DAYS:
        day = schedule.days.get(d) or DaySchedule(occupied=False)
        if not day.occupied:
            continue
        sh, sm = _parse_hhmm(day.start)
        eh, em = _parse_hhmm(day.end)
        start_m, end_m = sh * 60 + sm, eh * 60 + em
        if end_m <= start_m:
            mins = (24 * 60 - start_m) + end_m
        else:
            mins = end_m - start_m
        total += mins / 60.0
    return float(total)


def apply_schedule_occ_mode(df: pd.DataFrame, schedule: OccupancySchedule, *, overwrite: bool = False) -> pd.DataFrame:
    """Attach occ_mode from weekly calendar when missing (or overwrite=True)."""
    out = df.copy()
    if "occupied" in out.columns and out["occupied"].notna().any() and not overwrite:
        return out
    if not isinstance(out.index, pd.DatetimeIndex):
        return out
    mask = occupied_mask(out.index, schedule)
    out["occupied"] = mask.map(lambda x: "occupied" if x else "unoccupied")
    return out
