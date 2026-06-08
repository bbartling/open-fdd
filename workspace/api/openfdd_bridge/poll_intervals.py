"""Standard driver poll intervals — BACnet, Modbus, and JSON API."""

from __future__ import annotations

# 1, 5, 15, 30 minutes, and 1 hour only.
POLL_INTERVALS_S = (60, 300, 900, 1800, 3600)
POLL_LABELS = {
    60: "1 min",
    300: "5 min",
    900: "15 min",
    1800: "30 min",
    3600: "1 hour",
}


def snap_poll_interval(seconds: int) -> int:
    """Map legacy or invalid intervals to the nearest standard choice."""
    try:
        value = int(seconds)
    except (TypeError, ValueError):
        return 0
    if value <= 0:
        return 0
    if value in POLL_INTERVALS_S:
        return value
    # Prefer the longer standard interval when two choices are equally close (e.g. 10 min → 15 min).
    return min(POLL_INTERVALS_S, key=lambda s: (abs(s - value), -s))


def poll_interval_choices() -> list[dict[str, int | str]]:
    return [{"seconds": s, "label": POLL_LABELS[s]} for s in POLL_INTERVALS_S]
