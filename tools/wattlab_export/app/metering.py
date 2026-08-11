"""Deprecated shim — import from open_fdd.analytics.metering instead."""
from __future__ import annotations

import warnings

warnings.warn(
    "tools.wattlab_export.app.metering is deprecated; use open_fdd.analytics.metering",
    DeprecationWarning,
    stacklevel=2,
)

from open_fdd.analytics.metering import *  # noqa: F401,F403
