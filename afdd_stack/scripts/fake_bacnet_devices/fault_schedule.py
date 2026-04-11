"""
Deterministic fault schedule for fake BACnet devices — aligned with FDD rules.

Used by fake_ahu_faults.py and fake_vav_faults.py so faults occur at known times.
Used by long_term_bacnet_scrape_test.py to compute expected faults and verify Open FDD.

Schedule is by wall-clock minute-of-hour (UTC) so it repeats every hour and the test
does not need the device start time. Flatline window in sensor_flatline.yaml is 40
samples; at 1-min scrape that's 40 minutes, so we use 40 minutes of flatline per hour.

Minute-of-hour (UTC) 0-59:
  - 0-9:   normal
  - 10-49: flatline (40 min) -> expect flatline_flag
  - 50-54: out-of-bounds (5 min) -> expect bad_sensor_flag
  - 55-59: normal
"""

from datetime import datetime, timezone
from typing import Literal

Mode = Literal["normal", "flatline", "bounds"]

# Bounds: sensor_bounds.yaml SAT [40, 150] °F; ZoneTemp [40, 100] °F
OUT_OF_BOUNDS_VALUE = 180.0  # above high bound for both


def minute_of_hour_utc() -> int:
    """Current minute within the hour (0-59), UTC."""
    return datetime.now(timezone.utc).minute


def scheduled_mode(minute: int | None = None) -> Mode:
    """
    Return the fault mode for the given minute (0-59), or current UTC minute if None.
    """
    if minute is None:
        minute = minute_of_hour_utc()
    if 10 <= minute <= 49:
        return "flatline"
    if 50 <= minute <= 54:
        return "bounds"
    return "normal"


def expected_fault_windows_utc(start_dt: datetime, end_dt: datetime) -> dict[str, list[tuple[datetime, datetime]]]:
    """
    Given a UTC time range, return expected fault windows for assertion.

    Returns:
        {"flatline_flag": [(start, end), ...], "bad_sensor_flag": [(start, end), ...]}
    All datetimes are timezone-aware UTC.
    """
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=timezone.utc)
    if end_dt.tzinfo is None:
        end_dt = end_dt.replace(tzinfo=timezone.utc)

    flatline_windows: list[tuple[datetime, datetime]] = []
    bounds_windows: list[tuple[datetime, datetime]] = []

    # Walk hour by hour in range; for each hour, add 10-49 as flatline and 50-54 as bounds
    from datetime import timedelta

    t = start_dt.replace(minute=0, second=0, microsecond=0)
    while t < end_dt:
        hour_end = t + timedelta(hours=1)
        # Flatline: minute 10-49
        fl_start = t.replace(minute=10, second=0, microsecond=0)
        fl_end = t.replace(minute=50, second=0, microsecond=0)
        if fl_start < end_dt and fl_end > start_dt:
            flatline_windows.append(
                (max(fl_start, start_dt), min(fl_end, end_dt))
            )
        # Bounds: minute 50-54
        bd_start = t.replace(minute=50, second=0, microsecond=0)
        bd_end = t.replace(minute=55, second=0, microsecond=0)
        if bd_start < end_dt and bd_end > start_dt:
            bounds_windows.append(
                (max(bd_start, start_dt), min(bd_end, end_dt))
            )
        t = hour_end

    return {
        "flatline_flag": flatline_windows,
        "bad_sensor_flag": bounds_windows,
    }
