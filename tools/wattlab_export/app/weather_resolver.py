"""Deprecated shim — import from open_fdd.analytics.weather_resolver instead."""
from __future__ import annotations

import warnings

warnings.warn(
    "tools.wattlab_export.app.weather_resolver is deprecated; use open_fdd.analytics.weather_resolver",
    DeprecationWarning,
    stacklevel=2,
)

from open_fdd.analytics.weather_resolver import *  # noqa: F401,F403
