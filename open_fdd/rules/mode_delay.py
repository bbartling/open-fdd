"""Effective mode-delay holdoff shared by the pandas oracle and harness (#1459).

Single Python definition of the product rule implemented in
``sql/fdd/render_rule.py`` and ``crates/fdd_rules/src/params.rs``:

* effective delay (min) = max(MODE_DELAY_MIN, STARTUP_DELAY_MIN)
* holdoff rows = max(1, ceil(delay_min * 60 / poll_seconds))
* a sample is mode-stable only when the fan was on for every sample in the
  trailing ``rows`` window (``ROWS BETWEEN rows-1 PRECEDING AND CURRENT ROW``).

Missing parameters raise; there is no fallback value.
"""

from __future__ import annotations

import math

import pandas as pd

# Product default (sql/fdd/runtime_defaults.json MODE_DELAY_MIN, params.rs).
# tests/qualification/test_mode_delay_shared.py pins this to both sources.
PRODUCT_MODE_DELAY_MIN_DEFAULT = 10.0


def effective_mode_delay_min(params: dict) -> float:
    """max(mode_delay_min, startup_delay_min); ValueError naming any missing param."""
    missing = [name for name in ("mode_delay_min", "startup_delay_min") if name not in params]
    if missing:
        raise ValueError(f"effective_mode_delay_min: missing required param(s) {', '.join(missing)}")
    mode = float(params["mode_delay_min"])
    startup = float(params["startup_delay_min"])
    for name, value in (("mode_delay_min", mode), ("startup_delay_min", startup)):
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"{name} must be finite and >= 0, got {value}")
    return max(mode, startup)


def mode_delay_rows(delay_min: float, poll_seconds: float) -> int:
    """Holdoff window length in samples (>= 1)."""
    if not math.isfinite(poll_seconds) or poll_seconds < 1:
        raise ValueError(f"poll_seconds must be finite and >= 1, got {poll_seconds}")
    if not math.isfinite(delay_min) or delay_min < 0:
        raise ValueError(f"delay_min must be finite and >= 0, got {delay_min}")
    return max(1, math.ceil(delay_min * 60.0 / poll_seconds))


def fan_restart_stable(fan_on: pd.Series, rows: int) -> pd.Series:
    """True where no fan-off sample occurs in the trailing ``rows`` samples."""
    off = (~fan_on.astype(bool)).astype(int)
    return off.rolling(rows, min_periods=1).sum().eq(0)
