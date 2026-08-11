"""Compatibility shims. The ``vibe19`` extra is deprecated for the 4.3 series."""

from __future__ import annotations

import warnings

_VIBE19_EXTRA_REMOVED_IN = "5.0"

_VIBE19_MSG = (
    "The pip extra 'open-fdd[vibe19]' is deprecated and will be removed in "
    f"open-fdd {_VIBE19_EXTRA_REMOVED_IN}. Install 'open-fdd[reporting]' "
    "(findings/docs) or 'open-fdd[analytics]' / 'open-fdd[oracle]' instead."
)


def warn_deprecated_vibe19_extra() -> None:
    warnings.warn(_VIBE19_MSG, DeprecationWarning, stacklevel=3)


def maybe_warn_vibe19_from_env() -> None:
    import os

    extra = (os.environ.get("OPEN_FDD_REQUESTED_EXTRA") or "").strip().lower()
    if extra == "vibe19":
        warn_deprecated_vibe19_extra()
