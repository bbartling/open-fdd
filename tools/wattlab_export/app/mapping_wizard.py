"""Deprecated shim — import from open_fdd.analytics.mapping_wizard instead."""
from __future__ import annotations

import warnings

warnings.warn(
    "tools.wattlab_export.app.mapping_wizard is deprecated; use open_fdd.analytics.mapping_wizard",
    DeprecationWarning,
    stacklevel=2,
)

from open_fdd.analytics.mapping_wizard import *  # noqa: F401,F403
