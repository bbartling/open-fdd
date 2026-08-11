"""Deprecated shim — import from open_fdd.analytics.role_map instead."""
from __future__ import annotations

import warnings

warnings.warn(
    "tools.wattlab_export.app.role_map is deprecated; use open_fdd.analytics.role_map",
    DeprecationWarning,
    stacklevel=2,
)

from open_fdd.analytics.role_map import *  # noqa: F401,F403
