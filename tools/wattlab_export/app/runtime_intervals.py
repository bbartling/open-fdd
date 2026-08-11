"""Deprecated shim — import from open_fdd.analytics.runtime_intervals instead."""
from __future__ import annotations

import warnings

warnings.warn(
    "tools.wattlab_export.app.runtime_intervals is deprecated; use open_fdd.analytics.runtime_intervals",
    DeprecationWarning,
    stacklevel=2,
)

from open_fdd.analytics.runtime_intervals import *  # noqa: F401,F403
