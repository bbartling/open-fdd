"""Open-FDD analytics helpers (oracle / vibe19 library surface)."""

from open_fdd.analytics.poll import infer_poll_seconds
from open_fdd.analytics.runtime_intervals import (
    UNLIMITED_GAP_SECONDS,
    hours_under_mask,
    interval_durations,
)

__all__ = [
    "UNLIMITED_GAP_SECONDS",
    "hours_under_mask",
    "infer_poll_seconds",
    "interval_durations",
]
