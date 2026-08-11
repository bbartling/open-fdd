"""Deprecated shim — import from open_fdd.analytics.site_model instead."""
from __future__ import annotations

import warnings

warnings.warn(
    "tools.wattlab_export.app.site_model is deprecated; use open_fdd.analytics.site_model",
    DeprecationWarning,
    stacklevel=2,
)

from open_fdd.analytics.site_model import *  # noqa: F401,F403
