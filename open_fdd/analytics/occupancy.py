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
    "discharge_air_temperature": "Saturday",
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
    #: the site's occupied zone temperature range {lo_c, hi_c} in degC (5.0.22, zone_band.py); None = the 70-75 F default
    zone_band: dict[str, float] | None = None

    def __post_init__(self) -> None:
        if not self.days:
            self.days = {
                d: DaySchedule(occupied=(d not in {"sat", "sun"}), start="06:00", end="18:00")
                for d in DAYS
            }

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "timezone": self.timezone,
            "days": {
                k: {"occupied": v.occupied, "start": v.start, "end": v.end}
                for k, v in self.days.items()
            },
        }
        if self.zone_band is not None:
            out["zone_band"] = dict(self.zone_band)
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> OccupancySchedule:
        if not data:
            return cls()
        days: dict[str, DaySchedule] = {}
        raw_days = data.get("days") or {}
        for d in DAYS:
            row = raw_days.get(d) or {}
            days[d] = DaySchedule(
                occupied=bool(row.get("occupied", d not in {"sat", "sun"})),
                start=str(row.get("start", "06:00")),
                end=str(row.get("end", "18:00")),
            )
        # 5.0.22: an unusable stored band is dropped (None = the 70-75 F default), like the JS read path
        from open_fdd.analytics.zone_band import resolve_band

        band = resolve_band(data.get("zone_band")) if data.get("zone_band") is not None else None
        saved = {"lo_c": band["lo_c"], "hi_c": band["hi_c"]} if band and band["source"] == "saved" else None
        return cls(days=days, timezone=str(data.get("timezone") or "America/Chicago"), zone_band=saved)


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
    # A day whose end <= start runs past midnight INTO THE NEXT DAY (Mon 22:00-06:00 = Mon 22:00 .. Tue 06:00), the
    # same as nf-app/static/occupancy.js calendarSchedule (#1636): the hook's synthesized occupancy_status and this mask agree.
    windows = []
    for d in DAYS:
        day = schedule.days.get(d, DaySchedule(occupied=False))
        if not day.occupied:
            windows.append(None)
            continue
        sh, sm = _parse_hhmm(day.start)
        eh, em = _parse_hhmm(day.end)
        windows.append((sh * 60 + sm, eh * 60 + em))
    minutes = local.hour * 60 + local.minute
    out = []
    for dow, mins in zip(local.dayofweek, minutes):
        i = int(dow)                                    # Mon=0
        today, yesterday = windows[i], windows[(i - 1) % 7]
        occ = False
        if today is not None:
            start_m, end_m = today
            occ = start_m <= mins < end_m if end_m > start_m else mins >= start_m
        if not occ and yesterday is not None and yesterday[1] <= yesterday[0]:
            occ = mins < yesterday[1]                   # the spill of yesterday's overnight shift
        out.append(occ)
    return pd.Series(out, index=index, dtype=bool)


def default_hook_schedule() -> dict[str, Any]:
    """The hook's fallback occupancy when a site has no saved calendar and no NF schedule.

    Monday–Friday 07:00–17:00 in America/Chicago (50 h/week). Twin of ``nf-app/static/schedule.js``
    ``defaultSchedule``. The Overview calendar default (06:00–18:00, 60 h/week) is a different document.
    """
    return {
        "timezone": "America/Chicago",
        "days": {
            d: {"occupied": d not in {"sat", "sun"}, "start": "07:00", "end": "17:00"}
            for d in DAYS
        },
    }


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
    """Attach occupancy_status from weekly calendar when missing (or overwrite=True)."""
    out = df.copy()
    if "occupancy_status" in out.columns and out["occupancy_status"].notna().any() and not overwrite:
        return out
    if not isinstance(out.index, pd.DatetimeIndex):
        return out
    mask = occupied_mask(out.index, schedule)
    out["occupancy_status"] = mask.map(lambda x: "occupancy_status" if x else "unoccupied")
    return out
