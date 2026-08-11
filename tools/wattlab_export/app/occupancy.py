"""Deprecated shim — import from open_fdd.analytics.occupancy instead."""
from __future__ import annotations

import warnings

warnings.warn(
    "tools.wattlab_export.app.occupancy is deprecated; use open_fdd.analytics.occupancy",
    DeprecationWarning,
    stacklevel=2,
)

from open_fdd.analytics.occupancy import *  # noqa: F401,F403
