"""Deprecated shim — import from open_fdd.analytics.units instead."""
from __future__ import annotations

import warnings

warnings.warn(
    "tools.wattlab_export.app.units is deprecated; use open_fdd.analytics.units",
    DeprecationWarning,
    stacklevel=2,
)

from open_fdd.analytics.units import *  # noqa: F401,F403
