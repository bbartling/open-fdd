"""Deprecated import path for the retired product-generation extra name.

Importing this module emits ``DeprecationWarning``. Prefer
``open_fdd.rules`` / ``open_fdd.analytics`` / ``open_fdd.reporting``.
Removed in open-fdd 5.0.
"""

from __future__ import annotations

from open_fdd.compat import warn_deprecated_vibe19_extra

warn_deprecated_vibe19_extra()
