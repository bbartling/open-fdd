"""Deprecated shim — import from open_fdd.analytics.daytypes instead."""
from __future__ import annotations

import warnings

warnings.warn(
    "tools.wattlab_export.app.daytypes is deprecated; use open_fdd.analytics.daytypes",
    DeprecationWarning,
    stacklevel=2,
)

from open_fdd.analytics.daytypes import *  # noqa: F401,F403
